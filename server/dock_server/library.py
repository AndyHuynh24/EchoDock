"""Search over the user's documents, email, notes and calendar (RAG).

Sources are chunked, embedded with Titan Text Embeddings v2 and stored in SQLite
(sqlite-vec for vectors, FTS5 for keywords). Vector and keyword results are merged
with reciprocal rank fusion, and the model answers only from the top chunks, with
citations. Indexing starts on first use and refreshes every 30 minutes.
Everything is stored locally in .data/library.db.
"""

import asyncio
import re
import sqlite3
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Literal
from urllib.parse import quote

import sqlite_vec
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from dock_server import bedrock, tracing
from dock_server.hub import Hub
from dock_server.state import DATA_DIR
from dock_server.tools.computer import run_on_computer

DB_FILE = DATA_DIR / "library.db"
CHUNK_CHARS = 1200
OVERLAP_CHARS = 200
EMAIL_DAYS = 120
MAX_EMAILS = 400
EVENT_DAYS = 60
REFRESH_MINUTES = 30
CANDIDATES = 30
TOP = 6
PARALLEL = 4  # concurrent embedding calls
REMEMBER_SECONDS = 600

Kind = Literal["any", "file", "email", "note", "event"]

ANSWER_SYSTEM = (
    "You answer a question using only the numbered excerpts below, which come from the "
    "user's own files, email, notes and calendar. Reply in one or two short sentences that "
    "will be spoken aloud, then the excerpt numbers you used, like [2]. Give the exact detail "
    "they asked for (the date, the number, the password, the name). If excerpts disagree, "
    "prefer the newest. If the excerpts don't contain the answer, reply exactly: NOT FOUND. "
    "Never guess or use outside knowledge."
)

STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "are", "was", "were", "be", "my", "me",
    "i", "you", "your", "it", "this", "that", "what", "whats", "when", "where", "who", "how", "which", "do",
    "does", "did", "can", "could", "about", "from", "with", "at", "by", "say", "said", "tell", "find", "get",
    "have", "has", "many", "much", "there", "any", "some",
}


def chunks(text: str, size: int = CHUNK_CHARS, overlap: int = OVERLAP_CHARS) -> list[str]:
    """Split text into overlapping chunks of about `size` characters, at paragraph or sentence breaks."""
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    pieces, start = [], 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            cut = max(text.rfind("\n\n", start + size // 2, end), text.rfind(". ", start + size // 2, end))
            if cut > start:
                end = cut + 1
        pieces.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return [p for p in pieces if p]


def _header(item: dict) -> str:
    """Prefix a chunk with its source."""
    if item["kind"] == "file":
        return f"File: {item['folder']}/{item['title']} (changed {item['at'][:10]})"
    if item["kind"] == "email":
        return f"Email from {item['who']}, subject \"{item['title']}\", {item['at'][:16]}"
    if item["kind"] == "event":
        return f"Calendar event: {item['title']}"
    return "Dock note"


QUESTION = re.compile(r"(what|when|where|who|why|how|which|is|are|was|were|do|does|did|can|could|should|will)\b", re.IGNORECASE)


def _spoken_source(source: dict) -> str:
    if source["kind"] == "file":
        return f"your file {source['title']}"
    if source["kind"] == "email":
        return f"{source['who']}'s email, \"{source['title']}\""
    return "your calendar" if source["kind"] == "event" else "your notes"


def _keyword_query(question: str) -> str:
    words = [w for w in re.findall(r"[a-z0-9]{2,}", question.lower()) if w not in STOPWORDS]
    return " OR ".join(f'"{w}"' for w in dict.fromkeys(words))


SCHEMA = f"""
CREATE TABLE IF NOT EXISTS sources (id INTEGER PRIMARY KEY, kind TEXT, ref TEXT UNIQUE, title TEXT, who TEXT,
                                    at TEXT, folder TEXT, link TEXT, version TEXT);
CREATE TABLE IF NOT EXISTS chunks (id INTEGER PRIMARY KEY, source_id INTEGER, text TEXT);
CREATE INDEX IF NOT EXISTS chunks_by_source ON chunks(source_id);
CREATE VIRTUAL TABLE IF NOT EXISTS chunk_words USING fts5(text);
CREATE VIRTUAL TABLE IF NOT EXISTS chunk_vectors USING vec0(embedding float[{bedrock.EMBED_DIMENSIONS}] distance_metric=cosine);
"""


class Library:
    def __init__(self, hub: Hub, mail=None, notes=None, calendar=None, path=DB_FILE):
        self.hub, self.mail, self.notes, self.calendar = hub, mail, notes, calendar
        self.path = path
        self._db: sqlite3.Connection | None = None
        self._lock = threading.Lock()
        self.building = False
        self.progress = {"read": 0, "total": 0}
        self.last_sources: list[dict] = []
        self.last_at = 0.0
        self._watch: asyncio.Task | None = None

    # ---- database ----

    def db(self) -> sqlite3.Connection:
        if self._db is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            db = sqlite3.connect(self.path, check_same_thread=False)
            db.enable_load_extension(True)
            sqlite_vec.load(db)
            db.enable_load_extension(False)
            db.executescript(SCHEMA)
            self._db = db
        return self._db

    def counts(self) -> dict:
        with self._lock:
            return dict(self.db().execute("SELECT kind, COUNT(*) FROM sources GROUP BY kind").fetchall())

    def _versions(self) -> dict[str, str]:
        with self._lock:
            return dict(self.db().execute("SELECT ref, version FROM sources").fetchall())

    def _delete(self, source_id: int) -> None:
        db = self.db()
        ids = [r[0] for r in db.execute("SELECT id FROM chunks WHERE source_id = ?", [source_id])]
        if ids:
            marks = ",".join("?" * len(ids))
            db.execute(f"DELETE FROM chunk_vectors WHERE rowid IN ({marks})", ids)
            db.execute(f"DELETE FROM chunk_words WHERE rowid IN ({marks})", ids)
        db.execute("DELETE FROM chunks WHERE source_id = ?", [source_id])
        db.execute("DELETE FROM sources WHERE id = ?", [source_id])

    def forget(self, kind: str, keep: set[str]) -> int:
        """Drop sources of this kind that no longer exist."""
        with self._lock:
            gone = [(i, ref) for i, ref in self.db().execute("SELECT id, ref FROM sources WHERE kind = ?", [kind])
                    if ref not in keep]
            for source_id, _ in gone:
                self._delete(source_id)
            self.db().commit()
        return len(gone)

    def add(self, items: list[dict]) -> int:
        """Chunk, embed and store items. Returns the number of tokens embedded."""
        pieces = [(item, f"{_header(item)}\n{piece}") for item in items for piece in chunks(item["text"])[:60]]
        with ThreadPoolExecutor(PARALLEL) as pool:
            vectors = list(pool.map(lambda p: _embed_quietly(p[1]), pieces))
        by_item, failed = defaultdict(list), set()
        for (item, text), vector in zip(pieces, vectors):
            if vector:
                by_item[item["ref"]].append((text, vector))
            else:
                failed.add(item["ref"])
        with self._lock:
            db = self.db()
            for item in items:
                old = db.execute("SELECT id FROM sources WHERE ref = ?", [item["ref"]]).fetchone()
                if old:
                    self._delete(old[0])
                cursor = db.execute(
                    "INSERT INTO sources (kind, ref, title, who, at, folder, link, version) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    [item["kind"], item["ref"], item["title"], item.get("who", ""), item.get("at", ""),
                     item.get("folder", ""), item.get("link", ""), "" if item["ref"] in failed else item["version"]])
                for text, vector in by_item[item["ref"]]:
                    chunk_id = db.execute("INSERT INTO chunks (source_id, text) VALUES (?, ?)",
                                          [cursor.lastrowid, text]).lastrowid
                    db.execute("INSERT INTO chunk_words (rowid, text) VALUES (?, ?)", [chunk_id, text])
                    db.execute("INSERT INTO chunk_vectors (rowid, embedding) VALUES (?, ?)",
                               [chunk_id, sqlite_vec.serialize_float32(vector)])
            db.commit()
        return sum(len(text) for found in by_item.values() for text, _ in found) // 4

    # ---- collecting ----

    async def refresh(self) -> dict:
        """Index new or changed sources and drop removed ones."""
        if self.building:
            return {}
        self.building = True
        started, tokens, added = time.perf_counter(), 0, defaultdict(int)
        try:
            known = await asyncio.to_thread(self._versions)
            for kind, collect in (("note", self._notes), ("event", self._events),
                                  ("email", self._emails), ("file", self._documents)):
                try:
                    current, changed = await collect(known)
                except Exception as e:
                    print(f"Library: couldn't read {kind}s this time: {e!r}")
                    continue
                self.progress = {"read": 0, "total": len(changed)}
                for start in range(0, len(changed), 20):
                    batch = changed[start:start + 20]
                    tokens += await asyncio.to_thread(self.add, batch)
                    added[kind] += len(batch)
                    self.progress["read"] += len(batch)
                await asyncio.to_thread(self.forget, kind, current)
        finally:
            self.building = False
        seconds = time.perf_counter() - started
        tracing.step(type="model", purpose="indexing", model=bedrock.EMBED_MODEL_ID, seconds=round(seconds, 3),
                     input=tokens, output=0, cache_read=0, cache_write=0, tokens_per_sec=0,
                     cost=round(tracing.cost(bedrock.EMBED_MODEL_ID, {"inputTokens": tokens}), 6))
        print(f"Library: read {dict(added)} in {seconds:.0f} s (~{tokens} tokens embedded)")
        return dict(added)

    async def _documents(self, known: dict) -> tuple[set[str], list[dict]]:
        listed = (await self.hub.ask_agent("list_documents", timeout=60))["documents"]
        current = {f"file:{d['path']}": d for d in listed}
        stale = [d for ref, d in current.items() if known.get(ref) != str(d["modified"])]
        changed = []
        for start in range(0, len(stale), 20):
            batch = stale[start:start + 20]
            texts = (await self.hub.ask_agent("document_texts", timeout=90, paths=[d["path"] for d in batch]))["texts"]
            for d in batch:
                changed.append({"kind": "file", "ref": f"file:{d['path']}", "title": d["name"], "folder": d["folder"],
                                "at": datetime.fromtimestamp(d["modified"]).isoformat(timespec="minutes"),
                                "link": d["path"], "version": str(d["modified"]),
                                "text": texts.get(d["path"]) or d["name"]})
        return set(current), changed

    async def _emails(self, known: dict) -> tuple[set[str], list[dict]]:
        if not (self.mail and self.mail.connected):
            raise ValueError("email isn't connected")
        uids, messages = await asyncio.to_thread(self.mail.for_search, EMAIL_DAYS, MAX_EMAILS,
                                                 {r[6:] for r, v in known.items() if r.startswith("email:") and v})
        changed = [{"kind": "email", "ref": f"email:{m['uid']}", "title": m["subject"], "who": m["from"],
                    "at": m["date"], "version": m["uid"],
                    "link": "https://mail.google.com/mail/u/0/#search/rfc822msgid%3A" + quote(m["id"].strip("<>")),
                    "text": f"From: {m['from']} <{m['address']}>\nSubject: {m['subject']}\n\n{m['text']}"}
                   for m in messages]
        return {f"email:{u}" for u in uids}, changed

    async def _notes(self, known: dict) -> tuple[set[str], list[dict]]:
        items = []
        for note in (self.notes.items if self.notes else []):
            status = "done" if note.get("done") else "to do"
            text = f"Note ({status}): {note['text']}" + (f". Due {note['due']}" if note.get("due") else "")
            items.append({"kind": "note", "ref": f"note:{note['id']}", "title": note["text"][:80],
                          "at": note.get("added", ""), "version": text, "text": text})
        return {i["ref"] for i in items}, [i for i in items if known.get(i["ref"]) != i["version"]]

    async def _events(self, known: dict) -> tuple[set[str], list[dict]]:
        if not (self.calendar and self.calendar.connected):
            raise ValueError("the calendar isn't connected")
        now = datetime.now()
        events = await asyncio.to_thread(self.calendar.events, now - timedelta(days=EVENT_DAYS), now + timedelta(days=EVENT_DAYS))
        items = []
        for e in events:
            when = e["start"].strftime("%A, %B %d, %Y") + ("" if e.get("all_day") else e["start"].strftime(", %I:%M %p"))
            text = f"Calendar event: {e['title']}. When: {when}." + (f" Where: {e['where']}." if e.get("where") else "")
            items.append({"kind": "event", "ref": f"event:{e['id']}", "title": e["title"],
                          "at": e["start"].isoformat(timespec="minutes"), "link": e.get("link", ""),
                          "version": text, "text": text})
        return {i["ref"] for i in items}, [i for i in items if known.get(i["ref"]) != i["version"]]

    def ensure_watch(self) -> None:
        """Refresh every REFRESH_MINUTES once search has been used."""
        if self._watch is None and self.path.exists():
            self._watch = asyncio.get_running_loop().create_task(self._refresh_often())

    async def _refresh_often(self) -> None:
        while True:
            try:
                await self.refresh()
            except Exception as e:
                print(f"Library refresh failed: {e!r}")
            await asyncio.sleep(REFRESH_MINUTES * 60)

    # ---- search ----

    def search(self, question: str, kind: str = "any", since_days: int = 0, top: int = TOP,
               mode: str = "hybrid") -> list[dict]:
        """Top chunks for the question: vector + keyword search merged with RRF.
        mode "vector" or "keyword" uses one method (for evals).
        """
        vector = sqlite_vec.serialize_float32(bedrock.embed(question)) if mode != "keyword" else None
        words = _keyword_query(question) if mode != "vector" else ""
        wanted = CANDIDATES * (3 if kind != "any" or since_days else 1)
        with self._lock:
            db = self.db()
            by_meaning = [r[0] for r in db.execute(
                "SELECT rowid FROM chunk_vectors WHERE embedding MATCH ? AND k = ? ORDER BY distance", [vector, wanted])] if vector else []
            by_words = [r[0] for r in db.execute(
                "SELECT rowid FROM chunk_words WHERE chunk_words MATCH ? ORDER BY rank LIMIT ?", [words, wanted])] if words else []
            score = defaultdict(float)
            for ranked in (by_meaning, by_words):
                for rank, chunk_id in enumerate(ranked):
                    score[chunk_id] += 1 / (60 + rank)
            if not score:
                return []
            marks = ",".join("?" * len(score))
            rows = db.execute(f"""SELECT c.id, c.text, s.kind, s.ref, s.title, s.who, s.at, s.folder, s.link
                                  FROM chunks c JOIN sources s ON s.id = c.source_id WHERE c.id IN ({marks})""",
                              list(score)).fetchall()
        since = (datetime.now() - timedelta(days=since_days)).isoformat() if since_days else ""
        hits, per_source = [], defaultdict(int)
        for chunk_id, text, *source in sorted(rows, key=lambda r: -score[r[0]]):
            source = dict(zip(("kind", "ref", "title", "who", "at", "folder", "link"), source))
            if (kind != "any" and source["kind"] != kind) or (since and source["at"] < since):
                continue
            if per_source[source["ref"]] >= 2:
                continue
            per_source[source["ref"]] += 1
            hits.append({"text": text, "source": source, "score": round(score[chunk_id], 4)})
            if len(hits) == top:
                break
        return hits

    async def answer(self, question: str, kind: str = "any", since_days: int = 0) -> dict:
        hits = await asyncio.to_thread(self.search, question, kind, since_days)
        if not hits:
            return {"text": "I couldn't find anything about that in your files, email or notes.", "sources": [], "found": False}
        excerpts = "\n\n".join(f"[{n}] {h['text']}" for n, h in enumerate(hits, start=1))
        prompt = f"Today is {datetime.now():%A, %B %d, %Y}.\nQuestion: {question}\n\nExcerpts:\n{excerpts}"
        reply = await asyncio.to_thread(bedrock.ask, prompt, ANSWER_SYSTEM, 250, bedrock.SMART_MODEL_ID, purpose="rag answer")
        if "NOT FOUND" in reply or not reply.strip():
            return {"text": "I couldn't find that in your files, email or notes.", "sources": [], "found": False}
        cited = [int(n) for group in re.findall(r"\[([\d,\s]+)\]", reply) for n in re.findall(r"\d+", group)]
        cited = [n for n in dict.fromkeys(cited) if 1 <= n <= len(hits)] or [1]
        sources = list({hits[n - 1]["source"]["ref"]: hits[n - 1]["source"] for n in cited}.values())
        text = re.sub(r"\s*\[[\d,\s]+\]", "", reply).strip()
        return {"text": text, "sources": sources, "found": True}

    def voice_context(self) -> str:
        if not self.last_sources or time.time() - self.last_at > REMEMBER_SECONDS:
            return ""
        listed = "; ".join(f"{n}. {_spoken_source(s)}" for n, s in enumerate(self.last_sources, start=1))
        return (f" Dock just answered from: {listed}. \"Open it\", \"show me that email\" or \"open the file\" means "
                "search_my_stuff with open_source 1 (or the number they say).")

    def register(self, mcp: MCPServer) -> None:
        @mcp.tool()
        async def search_my_stuff(question: str = "", kind: Kind = "any", since_days: int = 0, open_source: int = 0) -> str:
            """Answer a question from the user's own documents, email, notes and
            calendar, and say where the answer came from: "what's the Wi-Fi password
            the landlord sent?", "when is the CS589 project due?", "how many late days
            do I get in stat 310?", "what's my flight confirmation number?", "what did
            the professor say about the midterm?". Use it for facts written in their
            own files or messages. Not for opening a file by name (find_files), new or
            unread email (check_email) or what's on the schedule (get_schedule).
            kind: only one kind of source. since_days: only recent ones (e.g. 7).
            open_source: N opens source N of the last answer ("open it", "show me that email")."""
            # A real question is answered even if the model also asked to open something.
            if open_source and not QUESTION.match(question.strip()):
                return await self._open(open_source)
            if not question.strip():
                raise ToolError("What should I look for?")
            if not self.path.exists() or (not self.counts() and not self.building):
                asyncio.get_running_loop().create_task(self.refresh())
                self.ensure_watch()
                await self.hub.push_phone("card", title="Reading your stuff for search",
                                          detail="Your documents, recent email, notes and calendar. It stays on this computer.")
                return ("I'm reading your documents, email and notes for the first time, so I can answer "
                        "questions like that. It takes a few minutes. Ask me again in a bit.")
            if self.building and sum(self.counts().values()) < 20:
                return f"I'm still reading your stuff ({self.progress['read']} of {self.progress['total']} done). Ask me again in a minute."
            result = await self.answer(question, kind, since_days)
            self.last_sources, self.last_at = result["sources"], time.time()
            if not result["found"]:
                return result["text"]
            source = result["sources"][0]
            await self.hub.push_phone("card", title=result["text"][:600],
                                      detail="From " + " · ".join(_spoken_source(s) for s in result["sources"][:3])
                                      + ' · Say "open it" to open it')
            return f"{result['text']} Say open it to open it."

    async def _open(self, number: int) -> str:
        if not self.last_sources or time.time() - self.last_at > REMEMBER_SECONDS:
            raise ToolError("Ask me a question about your stuff first.")
        if not 1 <= number <= len(self.last_sources):
            raise ToolError(f"I only used {len(self.last_sources)} sources for that answer.")
        source = self.last_sources[number - 1]
        if source["kind"] == "file":
            await run_on_computer(self.hub, "open_path", path=source["link"], show_in_finder=False)
        elif source["link"]:
            await run_on_computer(self.hub, "open_url", url=source["link"])
        else:
            return f"That was from {_spoken_source(source)}, which I can't open."
        await self.hub.push_phone("toast", text=f"✓ Opened {source['title'][:40]}")
        return f"Opened {_spoken_source(source)}."


def _embed_quietly(text: str) -> list[float] | None:
    """Embed one chunk; a failure doesn't stop the rest."""
    try:
        return bedrock.embed(text, trace=False)
    except Exception as e:
        print(f"Couldn't embed a chunk: {e!r}")
        return None
