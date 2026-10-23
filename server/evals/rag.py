"""RAG eval: retrieval (hit@1, hit@5, MRR) for vector, keyword and hybrid search,
plus answer accuracy and "not found" handling. Builds a temporary index; Dock
doesn't need to be running. About $0.02 per run.

    uv run python -m evals.rag
"""

import asyncio
import statistics
import tempfile
import time
from pathlib import Path

from dock_server import tracing
from dock_server.library import TOP, Library
from evals.rag_corpus import ITEMS, QUESTIONS

RESULTS = Path(__file__).resolve().parent / "results"


def rank_of(hits: list[dict], ref: str) -> int:
    """Rank of the right source (1 = top), or 0 if missing."""
    refs = list(dict.fromkeys(h["source"]["ref"] for h in hits))
    return refs.index(ref) + 1 if ref in refs else 0


async def main() -> None:
    tracing.ON = False
    with tempfile.TemporaryDirectory() as folder:
        library = Library(hub=None, path=Path(folder) / "library.db")
        started = time.perf_counter()
        tokens = library.add(ITEMS)
        print(f"Indexed {len(ITEMS)} items ({tokens} tokens) in {time.perf_counter() - started:.1f} s\n")

        answerable = [q for q in QUESTIONS if q[1]]
        retrieval = {}
        for mode in ("vector", "keyword", "hybrid"):
            ranks = [rank_of(library.search(q, top=TOP, mode=mode), ref) for q, ref, _ in answerable]
            retrieval[mode] = {
                "hit@1": sum(r == 1 for r in ranks) / len(ranks),
                "hit@5": sum(1 <= r <= 5 for r in ranks) / len(ranks),
                "mrr": statistics.mean(1 / r if r else 0 for r in ranks),
            }

        rows, seconds = [], []
        for question, ref, must in QUESTIONS:
            t = time.perf_counter()
            result = await library.answer(question)
            seconds.append(time.perf_counter() - t)
            if ref:
                ok = result["found"] and all(m.lower() in result["text"].lower() for m in must)
                cited = ref in [s["ref"] for s in result["sources"]]
            else:
                ok, cited = not result["found"], True
            rows.append({"question": question, "ok": ok, "cited": cited, "answer": result["text"]})
            print(f"{'✓' if ok else '✗'}{'' if cited else ' (wrong source)'} {question!r:58} -> {result['text'][:110]}")

    unanswerable = [r for (q, ref, _), r in zip(QUESTIONS, rows) if not ref]
    answered = [r for (q, ref, _), r in zip(QUESTIONS, rows) if ref]
    lines = [f"Corpus: {len(ITEMS)} items (files, email, notes, calendar) · {len(QUESTIONS)} questions "
             f"({len(unanswerable)} with no answer)",
             "Retrieval (the right source ranked):"]
    lines += [f"  {mode:8} hit@1 {m['hit@1']:.0%} · hit@5 {m['hit@5']:.0%} · MRR {m['mrr']:.2f}" for mode, m in retrieval.items()]
    lines += [f"Answers: {sum(r['ok'] for r in answered)}/{len(answered)} correct, "
              f"{sum(r['cited'] for r in answered)}/{len(answered)} cite the right source",
              f"No-answer questions: {sum(r['ok'] for r in unanswerable)}/{len(unanswerable)} said not found (no made-up answers)",
              f"Speed: median {statistics.median(seconds):.2f} s per question (embed + search + answer)"]
    summary = "\n".join(lines)
    print("\n" + summary)
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "RAG-LATEST.md").write_text(f"# Latest search eval ({time.strftime('%Y-%m-%d %H:%M')})\n\n```text\n{summary}\n```\n")


if __name__ == "__main__":
    asyncio.run(main())
