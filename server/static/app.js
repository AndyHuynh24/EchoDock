// Dock phone web app.
// - The stage shows one thing at a time: Dock's face (idle), the focus timer,
//   or cards (answers, suggestions, questions) big in the middle. When the
//   last card goes away, the face (or the timer) comes back.
// - Shortcuts view: smaller buttons for the app in front on the Mac, with the
//   cards and "Try saying" examples above them.
// - Tap to talk is the simulated Alexa+: speech-to-text in the browser, the
//   server picks and runs Dock tools, and the reply is spoken here.
//
// Mac mode (?screen=mac): the same page runs in the Mac's menu-bar bubble
// (agent/dock_agent/bubble.py). It shows only the cards, the Mac speaks the
// answers, and when a phone is docked, the cards go there instead.
//
// Where the server is: opened from the Mac's own address, it's this page's
// address. Installed from Dock's fixed web app address (config.js sets
// DOCK_ADDRESS_URL), it reads the Mac's current address from address.json,
// so the app keeps working when that address changes.

const $ = (id) => document.getElementById(id);
const ADDRESS_URL = window.DOCK_ADDRESS_URL || "";
const statusEl = $("status");
const face = $("face");
const cardsEl = $("cards");
let socket = null;
let serverUrl = "";
let connected = false;
let failedTries = 0;    // reconnect attempts in a row that didn't work
let voiceState = "";    // "", "listening", "thinking" or "speaking"
let savedThisWeek = "";
let celebrateUntil = 0;
const MAC = new URLSearchParams(location.search).get("screen") === "mac";
// The desktop app's window around this page: WebKit on the Mac, WebView2 (pywebview) on
// Windows. pywebview's bridge only exists once the page has loaded, so messages wait for it.
const windowsQueue = [];
window.addEventListener("pywebviewready", () => windowsQueue.splice(0).forEach((m) => window.pywebview.api.post(m)));
const native = window.webkit?.messageHandlers?.dock
  || (MAC ? { postMessage: (m) => (window.pywebview?.api?.post ? window.pywebview.api.post(m) : windowsQueue.push(m)) } : null);
let phonesDocked = 0;  // (Mac mode) phones connected besides this bubble
// Every screen (the phone, the Mac bubble) shows the same cards; this one's id
// tells its own messages apart from the other screens' (see ask()).
const SCREEN_ID = Math.random().toString(36).slice(2);
if (MAC) document.body.classList.add("mac");

function store(key, value) { try { localStorage.setItem(key, value); } catch {} }
function stored(key) { try { return localStorage.getItem(key) || ""; } catch { return ""; } }

// ---- The pairing token ----
// The QR code puts it after "#" (never sent to the web host) or "?" (older links).

const token = (() => {
  const fromHash = new URLSearchParams(location.hash.slice(1)).get("token");
  const fromQuery = new URLSearchParams(location.search).get("token");
  if (fromHash) {
    store("dock-token", fromHash);
    history.replaceState(null, "", location.pathname);  // keep it out of the address bar
  }
  return fromHash || fromQuery || stored("dock-token");
})();

// ---- Connection to the server ----

async function findServer() {
  if (!ADDRESS_URL) return location.origin;
  const response = await fetch(`${ADDRESS_URL}?t=${Date.now()}`, { cache: "no-store" });
  const { url } = await response.json();
  store("dock-server", url);
  return url;
}

async function connect() {
  if (!token) { updateStatus(); return; }
  try { serverUrl = await findServer(); } catch { serverUrl = serverUrl || stored("dock-server"); }
  if (!serverUrl) { retry(); return; }
  socket = new WebSocket(`${serverUrl.replace(/^http/, "ws")}/ws/phone?token=${encodeURIComponent(token)}${MAC ? "&screen=mac" : ""}`);
  socket.onopen = () => { failedTries = 0; connected = true; updateStatus(); reportScreen(); };
  socket.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (messageHandlers[message.kind]) messageHandlers[message.kind](message);
  };
  // Phones drop connections often (screen off, Wi-Fi changes), so retry.
  socket.onclose = () => { connected = false; retry(); };
}

function retry() {
  failedTries += 1;
  updateStatus();
  setTimeout(connect, 2000);
}

function cantReachText() {
  return ADDRESS_URL ? "Can't reach your Mac. Is Dock running there?"
    : "Can't reach Dock. On the Mac, open localhost:8000/setup and scan the new QR code.";
}

function updateStatus() {
  statusEl.hidden = connected || !token || failedTries === 0;
  statusEl.textContent = failedTries < 15 ? "Reconnecting…" : "Can't reach your Mac";
  $("settings-status").textContent = !token ? "Not paired yet."
    : connected ? `Connected to your Mac (${new URL(serverUrl).host}).`
    : failedTries < 15 ? "Looking for your Mac…" : cantReachText();
  updateStage();
}

// What to do with each kind of message from the server. focus.js adds its own.
const messageHandlers = {};

function send(message) {
  if (socket && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(message));
}

// ---- Views: Dock (face) and Shortcuts ----

function setView(view) {
  document.body.dataset.view = view;
  document.querySelectorAll(".view-tab").forEach((t) => t.classList.toggle("active", t.dataset.view === view));
  store("dock-view", view);
  updateStage();
}
document.querySelectorAll(".view-tab").forEach((tab) => tab.addEventListener("click", () => setView(tab.dataset.view)));
if (stored("dock-view") === "pad") setView("pad");

// ---- The stage: face, timer or cards ----

function visiblePanels() {
  return [...cardsEl.children].filter((p) => !p.hidden && !p.classList.contains("leaving"));
}

function updateStage() {
  const count = visiblePanels().length;
  cardsEl.dataset.count = count;
  const focus = typeof focusInfo === "function" ? focusInfo() : { live: false };
  // During focus the timer stays (no face): "Away", "Back to …?" and "Welcome back!" show under it.
  document.body.dataset.stage = count ? "cards" : focus.live ? "timer" : "face";
  $("timer-moment").textContent = focus.live && focus.faceMoment ? focus.line : "";
  $("timer-scene").dataset.mood = focus.live && focus.faceMoment ? focus.mood : "";
  updateFace(focus);
  if (MAC) tellBubble();
}

// (Mac mode) Tell the bubble window whether to show, and how tall to be.
function tellBubble() {
  const shown = visiblePanels().length > 0;
  const height = shown ? Math.ceil(cardsEl.getBoundingClientRect().height) + 16 : 0;
  if (tellBubble.last === `${shown}:${height}`) return;
  tellBubble.last = `${shown}:${height}`;
  native?.postMessage({ show: shown, height });
}
if (MAC) new ResizeObserver(() => tellBubble()).observe(cardsEl);
if (MAC) window.addEventListener("load", () => native?.postMessage({ ready: true }));

// Watch the cards: whenever one appears or goes away, the stage updates.
new MutationObserver(updateStage).observe(cardsEl, { subtree: true, childList: true, attributes: true, attributeFilter: ["hidden"] });

function showPanel(panel) {
  panel.classList.remove("leaving");
  panel.hidden = false;
}

// Slide a card away, then hide it.
function closePanel(panel, then) {
  clearTimeout(panel.hideTimer);
  if (panel.hidden) { then?.(); return; }
  panel.classList.add("leaving");
  updateStage();
  setTimeout(() => {
    if (panel.classList.contains("leaving")) { panel.hidden = true; panel.classList.remove("leaving"); }
    then?.();
    updateStage();
  }, 220);
}

// Answers and info cards go away by themselves after a while.
function hideLater(panel, ms) {
  clearTimeout(panel.hideTimer);
  panel.hideTimer = setTimeout(() => closePanel(panel), ms);
}

cardsEl.addEventListener("click", (event) => {
  const panel = event.target.closest(".panel");
  if (!panel) return;
  if (!event.target.closest("button, input, label") && hush()) return;
  // × closes a card; tapping an answer or info card closes it too.
  if (event.target.closest(".close") || (panel.classList.contains("transient") && !event.target.closest("button"))) closePanel(panel);
});

// ---- The face ----

function updateFace(focus) {
  let mood = "happy", line = "", detail = "";
  if (voiceState === "listening") { mood = "listening"; line = "Listening…"; }
  else if (voiceState === "thinking") mood = "thinking";
  else if (voiceState === "speaking") mood = "speaking";
  else if (!token) { mood = "sleepy"; line = "Scan the QR code on your Mac to pair"; detail = "Open localhost:8000/setup on the Mac."; }
  else if (!connected && failedTries > 0) { mood = "offline"; line = failedTries < 15 ? "Reconnecting…" : cantReachText(); }
  else if (focus?.mood) ({ mood, line = "", detail = "" } = focus);
  else if (Date.now() < celebrateUntil) mood = "celebrate";
  if (face.dataset.mood !== mood) {
    face.classList.remove(`mood-${face.dataset.mood}`);
    face.classList.add(`mood-${mood}`);
    face.dataset.mood = mood;
    if (!["happy", "sleepy", "offline"].includes(mood)) wake();  // e.g. "Welcome back!" lights the screen up
  }
  const lineEl = $("face-line");
  const idle = !line && !focus?.mood && voiceState === "" && connected;
  $("face-scene").classList.toggle("idle", idle);  // shows the suggestions next to the face
  if (idle) {
    // Idle: one short, friendly line.
    lineEl.replaceChildren(...(savedThisWeek
      ? ["Dock saved you ", Object.assign(document.createElement("b"), { textContent: savedThisWeek }), " this week"]
      : ["Tap me and ask anything"]));
  } else {
    lineEl.textContent = line;
  }
  $("face-detail").textContent = detail;
}

// Blink now and then, and glance around when idle.
(function blink() {
  if (!["sleepy", "offline", "celebrate", "paused"].includes(face.dataset.mood)) {
    face.classList.add("blink");
    setTimeout(() => face.classList.remove("blink"), 140);
  }
  setTimeout(blink, 2500 + Math.random() * 3500);
})();
(function glance() {
  const looks = face.querySelectorAll(".look");
  if (face.dataset.mood === "happy" && document.body.dataset.stage === "face") {
    const x = (Math.random() < 0.5 ? -1 : 1) * (6 + Math.random() * 6);
    looks.forEach((l) => { l.style.transform = `translate(${x}px, ${Math.random() * 6 - 3}px)`; });
    setTimeout(() => looks.forEach((l) => { l.style.transform = ""; }), 1400);
  }
  setTimeout(glance, 6000 + Math.random() * 6000);
})();

// Tap the face (or anywhere around it): the phone is the trigger. The chat box
// opens on the Mac (to type with the Mac's keyboard) AND the phone listens.
// Typing on the Mac stops the listening; talking closes the Mac's box. With
// no Mac connected, the phone's own typing box opens instead.
// (Anywhere on the stage outside a card: the face, the focus timer, or the empty
// space while a card slides away.)
$("stage").addEventListener("click", (event) => {
  if (!event.target.closest(".panel, .chip, button, input, a")) typeOrTalk();
});

// While Dock listens or talks, a tap anywhere stops it (not only on its card,
// which can be small; buttons and text boxes still do their own thing).
document.addEventListener("click", (event) => {
  if (MAC || event.target.closest("button, input, textarea, select, a, label, dialog")) return;
  if (hush()) { event.stopPropagation(); event.preventDefault(); }
}, true);

// Tap again while Dock listens: cancel. Tap while it talks: stop talking.
// Returns true if it stopped something.
function hush() {
  if (voiceState === "listening") {
    if (MAC) native?.postMessage({ listen: "cancel" });
    else { stopListening(); send({ kind: "close_mac_chat" }); }
    closePanel($("answer"));
    return true;
  }
  if (voiceState === "speaking") { stopSpeaking(); return true; }
  return false;
}

function setVoice(state) {
  voiceState = state;
  document.body.dataset.voice = state;
  updateStage();
}

// ---- Shortcuts drawn as keys ----

function shortcutView(shortcut) {
  const wrap = document.createElement("span");
  if (!shortcut) return wrap;
  if (/^(Ctrl|Alt|Shift|Win)\+/.test(shortcut)) {  // Windows: "Ctrl+Shift+S"
    wrap.className = "keys";
    wrap.append(...shortcut.split(/\+(?=.)/).map((k) => Object.assign(document.createElement("kbd"), { textContent: k })));
    return wrap;
  }
  if (!/^[⌃⌥⇧⌘]/.test(shortcut)) { wrap.textContent = shortcut; return wrap; }
  wrap.className = "keys";
  const keys = [];
  let rest = shortcut;
  while (rest && "⌃⌥⇧⌘".includes(rest[0])) { keys.push(rest[0]); rest = rest.slice(1); }
  if (rest) keys.push(rest);
  wrap.append(...keys.map((k) => Object.assign(document.createElement("kbd"), { textContent: k })));
  return wrap;
}

// ---- Cards ----

// While Dock is answering a request, its cards wait for the reply, so the card,
// the voice and the arrow on screen all show up together, and the card takes
// the place of the "thinking" answer (one thing on screen, not two).
let asking = null;  // { held: [show functions] } for the request being answered
function holdForAnswer(show) {
  if (!asking) return false;
  asking.held.push(show);
  return true;
}

// Play a card's "coming out of the face" animation again if it's already showing.
function replay(panel) {
  if (panel.hidden) return;
  panel.style.animation = "none";
  void panel.offsetWidth;
  panel.style.animation = "";
}

function showCard(card) {
  if (holdForAnswer(() => showCard(card))) return;
  const { title, shortcut, detail } = card;
  $("card").classList.remove("done");
  replay($("card"));
  $("card-title").textContent = title || "";
  $("card-shortcut").replaceChildren(...(shortcut ? [shortcutView(shortcut)] : []));
  $("card-detail").textContent = detail || "";
  showPanel($("card"));
  // A shortcut to learn stays a while; other news goes quickly.
  hideLater($("card"), shortcut ? 12000 : Math.min(15000, 5000 + (detail || "").length * 40));
}

// Something Dock just did ("✓ Show Ruler"): a check, the name, and the
// shortcut for next time. No talking, just a short sound (see ask()).
function showDone(done) {
  if (holdForAnswer(() => showDone(done))) return;
  const { title, shortcut, detail } = done;
  $("card").classList.add("done");
  replay($("card"));
  $("card-title").textContent = title || "Done";
  $("card-shortcut").replaceChildren(...(shortcut ? [shortcutView(shortcut)] : []));
  $("card-detail").textContent = detail || "";
  showPanel($("card"));
  hideLater($("card"), shortcut ? 3500 : 2200);
}

let audio = null;
function doneSound() {
  if (MAC) { native?.postMessage({ sound: "done" }); return; }
  try {  // two soft notes, made here (no sound file to load)
    audio = audio || new AudioContext();
    audio.resume?.();
    const now = audio.currentTime;
    [[880, 0], [1318.5, 0.09]].forEach(([frequency, at]) => {
      const tone = audio.createOscillator();
      const volume = audio.createGain();
      tone.frequency.value = frequency;
      volume.gain.setValueAtTime(0.0001, now + at);
      volume.gain.exponentialRampToValueAtTime(0.22, now + at + 0.02);
      volume.gain.exponentialRampToValueAtTime(0.0001, now + at + 0.35);
      tone.connect(volume).connect(audio.destination);
      tone.start(now + at);
      tone.stop(now + at + 0.4);
    });
  } catch {}
}

// "✓ Split Clip", for things that just worked: the ✓ card, the same on every screen.
function showToast({ text }) {
  showDone({ title: text.replace(/^✓\s*/, "") });
}

// Shortcut coach: when the user keeps asking for (or clicking) the same item,
// and when they use a shortcut Dock taught them.
function showTip(tip) {
  if (holdForAnswer(() => showTip(tip))) return;
  const { title, shortcut, detail, sound } = tip;
  if (sound) doneSound();  // (e.g. an email that's let through during focus)
  $("tip-title").textContent = title || "";
  $("tip-shortcut").replaceChildren(...(shortcut ? [shortcutView(shortcut)] : []));
  $("tip-detail").textContent = detail || "";
  if (shortcut === "🎉") celebrateUntil = Date.now() + 4000;
  showPanel($("tip"));
  hideLater($("tip"), shortcut === "🎉" ? 5000 : 15000);
}

function showAnswer(you, text, thinking = false) {
  $("answer-you").textContent = you ? `“${you}”` : "";
  $("answer-text").textContent = text;
  $("answer-text").classList.toggle("thinking", thinking);
  clearTimeout($("answer").hideTimer);
  showPanel($("answer"));
}

// ---- Time saved ----

function showSavings({ week }) {
  savedThisWeek = week || "";
  $("saved-week").textContent = savedThisWeek;
  $("saved").hidden = !savedThisWeek;
  updateStage();
}

// ---- "Try saying" examples for the app in front ----

const chip = (text) => Object.assign(document.createElement("button"), { type: "button", className: "chip", textContent: text });

function showExamples(app, examples) {
  if (!examples || !examples.length) return;
  $("try-chips").replaceChildren(...examples.map(chip));
  showFaceTips(examples);
}

// Up to four of them next to the face: two on each side in landscape.
function showFaceTips(examples) {
  const few = examples.slice(0, 4);
  const half = Math.ceil(few.length / 2);
  $("face-tips-left").replaceChildren(...few.slice(0, half).map(chip));
  $("face-tips-right").replaceChildren(...few.slice(half).map(chip));
}
showFaceTips([...$("try-chips").children].map((c) => c.textContent));

// Tapping an example asks Dock, as if it was said out loud.
for (const id of ["try-chips", "face-tips-left", "face-tips-right"]) {
  $(id).addEventListener("click", (event) => {
    const tapped = event.target.closest(".chip");
    if (!tapped) return;
    closeTyping();
    ask(tapped.textContent, { spoken: true });
  });
}

// ---- Shortcut pad ----

function showPad({ app, buttons, examples }) {
  showExamples(app, examples);
  $("pad-app").textContent = buttons.length ? app : `No shortcuts for ${app}`;
  $("pad").replaceChildren(...buttons.map((button) => {
    const el = Object.assign(document.createElement("button"), { type: "button", className: "pad-button" });
    const title = Object.assign(document.createElement("span"), { className: "pad-title", textContent: button.title });
    // Kept plain: the name, and its shortcut as small text.
    const shortcut = Object.assign(document.createElement("span"), { className: "pad-shortcut", textContent: button.shortcut || "" });
    el.append(title, shortcut);
    el.addEventListener("click", () => {
      send({ kind: "press", path: button.path });
      el.classList.add("pressed");
      setTimeout(() => el.classList.remove("pressed"), 400);
    });
    return el;
  }));
}

// ---- Tidy Downloads checklist ----

function showPlan({ moves, questions }) {
  $("plan-moves").replaceChildren(...moves.map((move, index) => {
    const item = document.createElement("li");
    const box = Object.assign(document.createElement("input"), { type: "checkbox", checked: true, value: index, id: `move-${index}` });
    const label = Object.assign(document.createElement("label"), { htmlFor: box.id });
    const why = Object.assign(document.createElement("div"), { className: "move-why", textContent: move.why || "" });
    label.append(`${move.file} → ${move.to}${move.new_folder ? " (new folder)" : ""}`, why);
    item.append(box, label);
    return item;
  }));
  $("plan-questions").replaceChildren(...questions.map((q) => Object.assign(document.createElement("li"), { textContent: q })));
  $("plan-move").hidden = moves.length === 0;
  if (moves.length || questions.length) showPanel($("plan"));
  showMoreHint($("plan-moves"));
}

// A long list scrolls inside its card (so the buttons stay in view); a fade
// at the bottom shows there's more below.
function showMoreHint(list) {
  requestAnimationFrame(() => list.classList.toggle("more", list.scrollTop + list.clientHeight < list.scrollHeight - 2));
}
["plan-moves", "downloads-list", "mail-list", "mail-plan-list"].forEach((id) => $(id).addEventListener("scroll", () => showMoreHint($(id))));

$("plan-move").addEventListener("click", () => {
  const items = [...document.querySelectorAll("#plan-moves input:checked")].map((box) => Number(box.value));
  if (items.length) send({ kind: "move", items });
  closePanel($("plan"));
});
$("plan-cancel").addEventListener("click", () => closePanel($("plan")));

// ---- New downloads and Save windows: "Put it in …?" ----

function makeButton(text, className, onClick) {
  const el = Object.assign(document.createElement("button"), { type: "button", textContent: text, className });
  el.addEventListener("click", onClick);
  return el;
}

function suggestionItem({ name, question, folder, newFolder, why, buttons }) {
  const item = document.createElement("li");
  const where = Object.assign(document.createElement("div"), { className: "download-to" });
  // Long folder paths may wrap after a "/", not in the middle of a name.
  if (folder) where.append(question, Object.assign(document.createElement("b"), { textContent: folder.replaceAll("/", "/\u200b") }), newFolder ? " (new folder)?" : "?");
  else where.textContent = question;
  const actions = Object.assign(document.createElement("div"), { className: "row" });
  actions.append(...buttons.map(([text, className, onClick]) => makeButton(text, className, () => onClick(item))));
  item.append(Object.assign(document.createElement("div"), { className: "download-name", textContent: name }), where);
  if (why) item.append(Object.assign(document.createElement("div"), { className: "move-why", textContent: why }));
  item.append(actions);
  return item;
}

// Take one suggestion off the card (the whole card slides away with the last one).
function removeItem(item) {
  if ($("downloads-list").children.length <= 1) {
    closePanel($("downloads"), () => { item.remove(); updateDownloads(); });
  } else {
    item.remove();
    updateDownloads();
  }
}

function addItem(item) {
  $("downloads-list").prepend(item);
  updateDownloads();
}

function showDownload({ file, to, new_folder, why }) {
  hideDownload({ file });
  const item = suggestionItem({
    name: file, question: "Put it in ", folder: to, newFolder: new_folder, why,
    buttons: [
      ["Move", "primary", (el) => { send({ kind: "move_download", file }); removeItem(el); }],
      // Other: start a sentence for the user to finish.
      ["Other…", "secondary other", () => openTyping(`Put ${file} in `)],
      ["Not now", "secondary", (el) => { send({ kind: "keep_download", file }); removeItem(el); }],
    ],
  });
  item.dataset.file = file;
  addItem(item);
}

// A Save window is open on the Mac: "Save it in …? Save here / Not now".
function showSavePanel({ file, to, new_folder, why, app }) {
  hideSavePanel();
  const item = suggestionItem({
    name: `Saving ${file}`, question: "Save it in ", folder: to, newFolder: new_folder, why: [app, why].filter(Boolean).join(" · "),
    buttons: [
      ["Save here", "primary", (el) => { send({ kind: "save_here" }); removeItem(el); }],
      ["Not now", "secondary", (el) => { send({ kind: "dismiss_save" }); removeItem(el); }],
    ],
  });
  item.dataset.save = "yes";
  addItem(item);
}

// Suggestions are off: a Save window is open, so ask before using AI on it.
function showSaveAsk({ file, app }) {
  hideSaveAsk();
  const item = suggestionItem({
    name: `Saving ${file}` + (app ? ` in ${app}` : ""), question: "Want Dock to suggest a folder?",
    buttons: [
      ["Yes", "primary", (el) => { send({ kind: "save_ask", yes: true }); removeItem(el); }],
      ["No", "secondary", (el) => { send({ kind: "save_ask", yes: false }); removeItem(el); }],
    ],
  });
  item.dataset.save = "ask";
  addItem(item);
}

function removeWhere(test) {
  const items = [...$("downloads-list").children].filter(test);
  items.forEach((item) => removeItem(item));
}
function hideSaveAsk() { removeWhere((item) => item.dataset.save === "ask"); }
function hideSavePanel() { removeWhere((item) => item.dataset.save); }
function hideDownload({ file }) { removeWhere((item) => item.dataset.file === file); }

// × on the card: "Not now" (or "No") for every file on it.
$("downloads").querySelector(".close").addEventListener("click", (event) => {
  event.stopPropagation();
  [...$("downloads-list").children].forEach((item) => item.querySelector(".row button:last-child")?.click());
});

function updateDownloads() {
  const items = [...$("downloads-list").children];
  showMoreHint($("downloads-list"));
  if (items.length) showPanel($("downloads"));
  else if (!$("downloads").classList.contains("leaving")) $("downloads").hidden = true;
  $("downloads").querySelector(".eyebrow").textContent =
    items.length > 1 ? "Where should these go?" : items[0]?.dataset.save ? "Where to save" : "New download";
}

// ---- Reading out loud ----

// Chrome stops long utterances early, so speak in sentence-sized pieces.
// The face talks while the phone speaks. `done` runs when it has finished.
let macSpeechDone = null;
window.speechDone = () => { const done = macSpeechDone; macSpeechDone = null; setVoice(""); done?.(); };

function speak(text, done) {
  if (MAC) {  // the Mac speaks it (voice_out.py), then calls speechDone()
    macSpeechDone = done;
    setVoice("speaking");
    native?.postMessage({ say: text });
    return;
  }
  speechSynthesis.cancel();
  const pieces = text.match(/[^.!?\n]+[.!?]*\s*/g) || [text];
  const chunks = [];
  let chunk = "";
  for (const piece of pieces) {
    if ((chunk + piece).length > 200 && chunk.trim()) { chunks.push(chunk); chunk = ""; }
    chunk += piece;
  }
  if (chunk.trim()) chunks.push(chunk);
  if (!chunks.length || !window.speechSynthesis) { done?.(); return; }
  const id = (speak.id = (speak.id || 0) + 1);
  chunks.forEach((c, n) => {
    const utterance = new SpeechSynthesisUtterance(c);
    if (n === 0) utterance.onstart = () => { if (speak.id === id) setVoice("speaking"); };
    if (n === chunks.length - 1) utterance.onend = utterance.onerror = () => {
      if (speak.id !== id) return;  // a newer speech replaced this one
      setVoice("");
      done?.();
    };
    speechSynthesis.speak(utterance);
  });
}

function stopSpeaking() {
  speak.id = (speak.id || 0) + 1;
  macSpeechDone = null;
  if (MAC) native?.postMessage({ hush: true });
  else speechSynthesis.cancel();
  setVoice("");
  closePanel($("reading"));
}

function startReading({ title, text }) {
  $("reading-title").textContent = title;
  showPanel($("reading"));
  speak(text, () => closePanel($("reading")));
}

$("reading-stop").addEventListener("click", stopSpeaking);

// ---- Email: "what did I miss?" ----

// One email in a list: sender, time, what it's about, and "+ Add to list" for its to-do.
function mailItem(m) {
  const item = document.createElement("li");
  if (m.urgent) item.classList.add("urgent");
  const top = Object.assign(document.createElement("div"), { className: "mail-from" });
  top.append(m.from, Object.assign(document.createElement("span"), { className: "mail-when", textContent: m.when }));
  item.append(top, Object.assign(document.createElement("div"), { className: "mail-gist", textContent: m.gist || m.subject }));
  if (m.todo) {
    // A to-do with a deadline goes on the calendar (with the Google sign-in), else on Dock's list.
    const calendar = m.todo_where === "calendar";
    const label = calendar ? `＋ Add “${m.todo}” to my calendar · due ${m.todo_when}` : `＋ Add “${m.todo}” to my list`;
    item.append(makeButton(label, "secondary small", (event) => {
      send({ kind: "mail_todo", text: m.todo });
      event.currentTarget.replaceWith(Object.assign(document.createElement("div"), { className: "move-why",
        textContent: calendar ? "✓ On your calendar" : "✓ Added to your list" }));
    }));
  }
  return item;
}

function showMail(mail) {
  if (holdForAnswer(() => showMail(mail))) return;
  const { title, items } = mail;
  $("mail-title").textContent = title;
  $("mail-list").replaceChildren(...items.map(mailItem));
  $("mail-rest").textContent = mail.rest || "";
  showPanel($("mail"));
  showMoreHint($("mail-list"));
  hideLater($("mail"), 60000);
}

// The morning briefing: "Today", "Email", "On your list". ask: the morning offer
// (Brief me / Not now); otherwise the full briefing, with the important emails.
function showBriefing(briefing) {
  if (holdForAnswer(() => showBriefing(briefing))) return;
  const { title, sections, ask } = briefing;
  $("briefing-title").textContent = title;
  $("briefing-sections").replaceChildren(...sections.map((section) => {
    const block = Object.assign(document.createElement("div"), { className: "briefing-section" });
    block.append(Object.assign(document.createElement("div"), { className: "eyebrow", textContent: section.title }));
    if (section.mail?.length) {
      block.append(Object.assign(document.createElement("ul"), { className: "briefing-mail" }));
      block.lastChild.append(...section.mail.map(mailItem));
    }
    for (const line of section.lines || []) block.append(Object.assign(document.createElement("div"), { className: "briefing-line", textContent: line }));
    return block;
  }));
  $("briefing-ask").hidden = !ask;
  replay($("briefing"));
  showPanel($("briefing"));
  if (!ask) hideLater($("briefing"), 120000);
}
$("briefing-yes").addEventListener("click", () => { send({ kind: "briefing", yes: true }); $("briefing-ask").hidden = true; });
$("briefing-no").addEventListener("click", () => { send({ kind: "briefing", yes: false }); closePanel($("briefing")); });

// "Clean up my inbox": what Dock would do, ticked; nothing moves until Clean up.
function showMailPlan(plan) {
  if (holdForAnswer(() => showMailPlan(plan))) return;
  $("mail-plan-list").replaceChildren(...plan.items.map((m, index) => {
    const item = document.createElement("li");
    const box = Object.assign(document.createElement("input"), { type: "checkbox", checked: true, value: index, id: `mail-move-${index}` });
    const label = Object.assign(document.createElement("label"), { htmlFor: box.id });
    label.append(Object.assign(document.createElement("b"), { textContent: m.from }), ` · ${m.subject}`,
                 Object.assign(document.createElement("div"), { className: "move-why", textContent: m.to === "Trash" ? `${m.kind} → Trash` : `→ ${m.to}` }));
    item.append(box, label);
    if (m.can_unsubscribe) {
      item.append(makeButton("Unsubscribe", "secondary small", (event) => {
        send({ kind: "mail_unsubscribe", n: index });
        event.currentTarget.disabled = true;
        event.currentTarget.textContent = "Unsubscribing…";
      }));
    }
    return item;
  }));
  showPanel($("mail-plan"));
  showMoreHint($("mail-plan-list"));
}
$("mail-plan-go").addEventListener("click", () => {
  send({ kind: "mail_cleanup", items: [...document.querySelectorAll("#mail-plan-list input:checked")].map((b) => Number(b.value)) });
  closePanel($("mail-plan"));
});
for (const id of ["mail-plan-no"]) $(id).addEventListener("click", () => { send({ kind: "mail_cleanup_cancel" }); closePanel($("mail-plan")); });
$("mail-plan").querySelector(".close").addEventListener("click", () => send({ kind: "mail_cleanup_cancel" }));

// ---- Writing help: the suggestion, with what changed marked ----

// Nothing changes in the user's text until they choose: Replace, Insert below,
// or Change more (say or type what else to change: the suggestion updates).
function showWriting({ app, parts, title }) {
  if (holdForAnswer(() => showWriting({ app, parts, title }))) return;
  $("writing-title").textContent = `${title} · ${app}`;
  $("writing-text").replaceChildren(...parts.map(([kind, text]) =>
    kind ? Object.assign(document.createElement(kind === "add" ? "ins" : "del"), { textContent: text }) : document.createTextNode(text)));
  replay($("writing"));
  showPanel($("writing"));
}
const useWriting = (where) => { send({ kind: "writing_use", where }); closePanel($("writing")); };
$("writing-replace").addEventListener("click", () => useWriting("replace"));
$("writing-below").addEventListener("click", () => useWriting("below"));
$("writing").querySelector(".close").addEventListener("click", () => send({ kind: "writing_use", where: "cancel" }));
$("writing-more").addEventListener("click", () => {  // the card stays: the next answer changes it
  if (MAC) send({ kind: "open_mac_chat" });
  else listen();
});

// ---- "Search Google for …?": nothing opens until the user taps Search ----

let offeredSearch = "";
function showSearchOffer({ query, why }) {
  if (holdForAnswer(() => showSearchOffer({ query, why }))) return;
  offeredSearch = query;
  $("search-why").textContent = why ? `${why} · Search Google?` : "Search Google?";
  $("search-query").textContent = query;
  replay($("search"));
  showPanel($("search"));
}
$("search-go").addEventListener("click", () => { send({ kind: "search_go", go: true, query: offeredSearch }); closePanel($("search")); });
$("search-no").addEventListener("click", () => { send({ kind: "search_go", go: false }); closePanel($("search")); });
$("search").querySelector(".close").addEventListener("click", () => send({ kind: "search_go", go: false }));

// ---- Day recap ----

function minutesText(m) {
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60} min`;
}

function barRow(label, fraction, time) {
  const row = Object.assign(document.createElement("div"), { className: "bar-row" });
  const bar = Object.assign(document.createElement("div"), { className: "bar" });
  bar.style.width = `${fraction * 100}%`;
  row.append(Object.assign(document.createElement("span"), { textContent: label }), bar,
             Object.assign(document.createElement("span"), { className: "bar-time", textContent: time }));
  return row;
}

function showRecap({ day, apps, files, summary }) {
  $("recap-day").textContent = day;
  $("recap-summary").textContent = summary || "";
  const most = Math.max(1, ...apps.map((a) => a.minutes));
  $("recap-apps").replaceChildren(...apps.map((a) => barRow(a.app, a.minutes / most, minutesText(a.minutes))));
  $("recap-files").replaceChildren(...files.map((f) => Object.assign(document.createElement("li"), { textContent: f.name })));
  showPanel($("recap"));
  hideLater($("recap"), 90000);
}

// ---- Asking Dock (typed or spoken) ----

// Spoken requests get a spoken reply; typed ones are only shown. Commands that
// just happened ("quiet") get a ✓ card and a short sound, never talk.
async function ask(text, { spoken }) {
  const me = startAnswer(text);
  let answer, quiet = false;
  try {
    const response = await fetch(`${serverUrl}/api/voice`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Authorization": `Bearer ${token}` },
      body: JSON.stringify({ text, spoken, screen: SCREEN_ID }),
    });
    const result = await response.json();
    answer = result.reply || "Sorry, something went wrong.";
    quiet = Boolean(result.quiet);
  } catch {
    answer = "I can't reach your Mac right now.";
  }
  finishAnswer(me, text, answer, quiet, { speakHere: spoken });
}

// The other screens show the same request (the server tells them, "asking" and
// "answered"): the same "thinking" answer, then the same card. Only the screen
// that was asked speaks or plays the sound; the others' card goes when it has
// finished speaking ("speech_done").
function startAnswer(text) {
  const me = (asking = { held: [] });
  showAnswer(text, "", true);
  setVoice("thinking");
  return me;
}

function finishAnswer(me, text, answer, quiet, { speakHere, spokenElsewhere = false }) {
  if (asking === me) asking = null;
  setVoice("");
  // One thing on screen: this request's card if it has one, else the answer.
  const withCard = me.held.length > 0;
  if (withCard || quiet) {
    $("answer").hidden = true;
    me.held.forEach((show) => show());
    if (!me.held.length) showDone({ title: answer.replace(/^Done:?\s*/, "").replace(/\.$/, "") });
  } else {
    me.held.forEach((show) => show());
    showAnswer(text, answer);
  }
  const shown = withCard || quiet ? $("card") : $("answer");
  if (quiet) { if (speakHere) doneSound(); }
  else if (speakHere && $("reading").hidden) speak(answer, () => finishedSpeaking(shown));
  else if (spokenElsewhere) hideLater(shown, Math.max(6000, answer.length * 80));  // (or sooner: speech_done)
  else if (!withCard) hideLater($("answer"), Math.min(15000, 5000 + answer.length * 50));
}

let othersAsking = null;  // the request another screen is waiting on
const otherAnswers = {
  asking: ({ from, text }) => {
    if (from === SCREEN_ID) return;
    othersAsking = startAnswer(text);
  },
  answered: ({ from, text, reply, quiet, spoken }) => {
    if (from === SCREEN_ID || !othersAsking) return;
    const me = othersAsking;
    othersAsking = null;
    finishAnswer(me, text, reply, quiet, { speakHere: false, spokenElsewhere: spoken });
  },
};

// Dock has finished saying it: the card goes too, right away (it's in sync with
// the voice), and on the other screens.
const AFTER_SPEAKING_MS = 900;
function finishedSpeaking(panel) {
  hideLater(panel, AFTER_SPEAKING_MS);
  send({ kind: "speech_done", from: SCREEN_ID });  // the other screens' card goes too
}

// ---- Talking on the Mac (Mac mode): called by agent/dock_agent/talk.py ----

// Hold the talk key: "Listening…" and the words so far. null: stop showing it.
window.macListening = (words) => {
  if (words === null) { closePanel($("answer")); return; }
  showAnswer(words, "Listening", true);  // (the dots are animated)
  setVoice("listening");
};

// The chat box (click Dock's face in the menu bar): type, or click the microphone.
window.macCompose = (open) => {
  toldTyping = false;
  if (!open) { closePanel($("compose")); return; }
  $("compose-tips").replaceChildren(...[...$("try-chips").children].slice(0, 4).map((c) => chip(c.textContent)));
  showPanel($("compose"));
  setTimeout(() => $("compose-input").focus(), 50);
};

// The microphone button shows when Dock is listening (talk.py calls this).
window.macMic = (on) => { $("compose-mic").classList.toggle("on", on); };

let toldTyping = false;
$("compose-input").addEventListener("input", () => {
  if (toldTyping) return;
  toldTyping = true;
  send({ kind: "mac_typing" });  // the phone stops listening
  if (voiceState === "listening") native?.postMessage({ listen: "cancel" });  // ...and so does this computer
});

// Sending closes the chat box first, so the app's own window has the keyboard
// focus again: "split the screen" must act on that window, not on Dock's box.
function sendFromChatBox(text, spoken) {
  $("compose-input").value = "";
  if (!$("compose").hidden) native?.postMessage({ compose: false });
  setTimeout(() => ask(text, { spoken }), 150);
}

$("compose-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const text = $("compose-input").value.trim();
  if (text) sendFromChatBox(text, false);
});
$("compose-mic").addEventListener("click", () => native?.postMessage({ listen: "toggle" }));
$("compose-settings").addEventListener("click", () => native?.postMessage({ settings: true }));
$("compose-tips").addEventListener("click", (event) => {
  const tapped = event.target.closest(".chip");
  if (tapped) sendFromChatBox(tapped.textContent, true);
});
document.addEventListener("keydown", (event) => {
  if (!MAC || event.key !== "Escape") return;
  if (voiceState === "listening") native?.postMessage({ listen: "cancel" });  // (stop listening too)
  if (!$("compose").hidden) native?.postMessage({ compose: false });
});

// Let go: ask Dock what was said (the answer is shown and spoken).
window.macAsk = (text) => {
  if (!text) { setVoice(""); closePanel($("answer")); return; }
  if (!$("compose").hidden) sendFromChatBox(text, true);  // (talked from the chat box)
  else ask(text, { spoken: true });
};

// ---- Typing ----

const chatInput = $("chat-input");

function openTyping(text = "") {
  document.body.classList.add("typing");
  $("chat").hidden = false;
  chatInput.value = text;
  chatInput.focus();
}

function closeTyping() {
  document.body.classList.remove("typing");
  $("chat").hidden = true;
  chatInput.blur();
}

function typeOrTalk() {
  send({ kind: "open_mac_chat" });  // (the answer comes back as "mac_chat")
  listen({ alongsideMac: true });
}

// The Mac's answer: its chat box is open (type there), or there's no Mac.
function macChat({ ok }) {
  if (MAC) return;
  if (ok) showToast({ text: "⌨ Type on your Mac, or just talk" });
  else openTyping();
}

$("type-button").addEventListener("click", () => { openTyping(); listen({ alongsideTyping: true }); });
$("chat-close").addEventListener("click", () => { stopListening(); closeTyping(); });
$("chat-mic").addEventListener("click", () => { closeTyping(); listen(); });
// The first key typed means "I'm typing": stop listening.
chatInput.addEventListener("input", () => { if (voiceState === "listening") stopListening(); });
$("chat").addEventListener("submit", (event) => {
  event.preventDefault();
  const text = chatInput.value.trim();
  if (!text) return;
  closeTyping();
  ask(text, { spoken: false });
});

// ---- Tap to talk ----

const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;

let recognition = null;

// Listen once. alongsideTyping: the phone's typing box is open too, so its
// keyboard closes as soon as the user starts talking. alongsideMac: the Mac's
// chat box is open, so it closes when the user starts talking.
function listen({ alongsideTyping = false, alongsideMac = false } = {}) {
  if (voiceState === "listening") return;
  if (!Recognition) {
    if (!alongsideTyping) {
      showAnswer("", "This browser can't do speech recognition. Try Chrome, or type instead.");
      hideLater($("answer"), 8000);
    }
    return;
  }
  speechSynthesis.cancel();
  recognition = new Recognition();
  recognition.lang = "en-US";
  recognition.interimResults = true;  // (to notice talking as it starts)
  recognition.onstart = () => {
    setVoice("listening");
    // No face on screen to show it (the focus timer, or the Shortcuts view): a small card does.
    if (document.body.dataset.stage !== "face" || document.body.dataset.view === "pad") showAnswer("", "Listening", true);
  };
  recognition.onend = () => { if (voiceState === "listening") setVoice(""); recognition = null; };
  recognition.onresult = (event) => {
    const words = [...event.results].map((r) => r[0].transcript).join(" ").trim();
    if (!words) return;
    if (document.body.classList.contains("typing")) closeTyping();  // talking: put the keyboard away
    if (alongsideMac) { send({ kind: "close_mac_chat" }); alongsideMac = false; }
    const last = event.results[event.results.length - 1];
    if (last.isFinal) {
      recognition.onresult = null;
      ask(words, { spoken: true });
    } else {
      showAnswer(words, "Listening", true);
    }
  };
  recognition.onerror = (event) => {
    if (voiceState === "listening") setVoice("");
    // (With the typing box open, typing still works, so don't make a fuss.)
    if (event.error !== "no-speech" && event.error !== "aborted" && !alongsideTyping && !alongsideMac) {
      showAnswer("", `Microphone problem: ${event.error}`);
      hideLater($("answer"), 8000);
    }
  };
  try {
    recognition.start();
    setVoice("listening");  // (right away, so a quick second tap already cancels it)
  } catch {
    recognition = null;
  }
}

function stopListening() {
  if (recognition) {
    recognition.onresult = null;
    recognition.abort();
    recognition = null;
  }
  if (voiceState === "listening") setVoice("");
  if (!$("answer").hidden && $("answer-text").classList.contains("thinking")) closePanel($("answer"));
}

$("talk").addEventListener("click", () => { if (!hush()) { closeTyping(); listen(); } });

// ---- Screen: always on, dimmed while nothing happens ----
// Browsers can't change the real brightness, so the page itself goes dark.
// A tap on a dimmed screen wakes it and does what a tap always does (talk).

const DIM_AFTER_MS = 45000;
let lastActivity = Date.now();

let wakeLock = null;
async function keepAwake() {
  if (wakeLock && !wakeLock.released) return;
  try { wakeLock = await navigator.wakeLock?.request("screen"); } catch {}
}
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") keepAwake(); });

function wake() {
  lastActivity = Date.now();
  if (document.body.classList.contains("dim")) document.body.classList.remove("dim");
}

// Full screen, so Dock also fills the strip beside the camera in landscape.
// Browsers only allow it right after a tap, so ask on taps until it sticks.
function goFullScreen() {
  if (MAC || document.fullscreenElement || !document.documentElement.requestFullscreen) return;
  document.documentElement.requestFullscreen({ navigationUI: "hide" }).catch(() => {});
}

document.addEventListener("pointerdown", () => {
  if (!MAC && !audio && window.AudioContext) { try { audio = new AudioContext(); } catch {} }
  wake();
  keepAwake();  // some browsers only allow it after a tap
}, true);
// (On a touch screen a tap only "counts" when the finger lifts, so ask then.)
document.addEventListener("pointerup", goFullScreen, true);
document.addEventListener("click", goFullScreen, true);

// Tell Dock how the screen is shown (full screen or not, the camera notch), so
// problems like a black bar beside the camera can be seen in Dock's log.
function screenInfo() {
  const probe = document.createElement("div");
  probe.style.cssText = "position:fixed;visibility:hidden;padding:env(safe-area-inset-top) env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left)";
  document.body.append(probe);
  const pad = getComputedStyle(probe);
  const insets = [pad.paddingTop, pad.paddingRight, pad.paddingBottom, pad.paddingLeft].map((v) => parseInt(v) || 0);
  probe.remove();
  const mode = ["fullscreen", "standalone", "minimal-ui", "browser"].find((m) => matchMedia(`(display-mode: ${m})`).matches);
  return { kind: "screen_info", mode, fullscreen: !!document.fullscreenElement, view: [innerWidth, innerHeight],
           screen: [screen.width, screen.height], insets, angle: screen.orientation?.angle ?? 0 };
}
let screenTimer = null;
function reportScreen() {
  clearTimeout(screenTimer);
  screenTimer = setTimeout(() => { if (!MAC) send(screenInfo()); }, 800);
}
window.addEventListener("resize", reportScreen);
document.addEventListener("fullscreenchange", reportScreen);
document.addEventListener("keydown", wake, true);

setInterval(() => {
  const busy = document.body.dataset.stage === "cards" || voiceState || document.querySelector("dialog[open]")
    || $("face").dataset.mood === "worried";
  if (busy) lastActivity = Date.now();
  document.body.classList.toggle("dim", !MAC && Date.now() - lastActivity > DIM_AFTER_MS);
}, 1000);

// ---- Sheets: Focus and Settings ----

document.querySelectorAll(".sheet").forEach((sheet) => {
  sheet.querySelector(".close").addEventListener("click", () => sheet.close());
  // Tapping the dark area around the sheet closes it.
  sheet.addEventListener("click", (event) => { if (event.target === sheet) sheet.close(); });
});
$("settings-button").addEventListener("click", () => $("settings-sheet").showModal());

// Automatic folder suggestions are off unless the user turns them on (each uses AI).
$("folder-suggestions").addEventListener("change", (event) => {
  send({ kind: "set_folder_suggestions", on: event.target.checked });
});

function showSettings({ folder_suggestions }) {
  $("folder-suggestions").checked = Boolean(folder_suggestions);
}

// ---- Installing Dock as an app ----

let installPrompt = null;
const installed = matchMedia("(display-mode: standalone)").matches || navigator.standalone;
if (installed) $("install-help").textContent = "Dock is installed on this phone.";
window.addEventListener("beforeinstallprompt", (event) => {
  event.preventDefault();
  installPrompt = event;
  $("install").hidden = false;
});
$("install").addEventListener("click", async () => {
  if (!installPrompt) return;
  installPrompt.prompt();
  await installPrompt.userChoice;
  installPrompt = null;
  $("install").hidden = true;
});
window.addEventListener("appinstalled", () => {
  $("install").hidden = true;
  $("install-help").textContent = "Dock is installed. Open it from your home screen.";
});
// (The Mac bubble is always next to its server, so it needs no offline copy.)
if ("serviceWorker" in navigator && !MAC) navigator.serviceWorker.register("sw.js").catch(() => {});

Object.assign(messageHandlers, {
  card: showCard, done: showDone, toast: showToast, tip: showTip, mail: showMail, mail_plan: showMailPlan, briefing: showBriefing,
  writing: showWriting, writing_done: () => closePanel($("writing")),
  search_offer: showSearchOffer, search_done: () => closePanel($("search")),
  briefing_done: () => { if (!$("briefing-ask").hidden) closePanel($("briefing")); }, mail_plan_done: () => closePanel($("mail-plan")), pad: showPad, plan: showPlan, download: showDownload, download_done: hideDownload,
  save_panel: showSavePanel, save_panel_done: hideSavePanel, save_ask: showSaveAsk, save_ask_done: hideSaveAsk,
  settings: showSettings, read: startReading, recap: showRecap,
  savings: showSavings,
  say: ({ text, show = true }) => {
    if (show) showAnswer("", text);  // (show false: a card on screen already shows it)
    if (MAC && phonesDocked) {  // the docked phone says it; the bubble shows it until then
      if (show) hideLater($("answer"), Math.max(6000, text.length * 80));
      return;
    }
    speak(text, () => finishedSpeaking($("answer")));
  },
  ...otherAnswers,
  // Another screen finished saying its answer: this screen's card for it goes now.
  speech_done: ({ from }) => {
    if (from === SCREEN_ID || asking || voiceState) return;
    for (const id of ["card", "answer"]) if (!$(id).hidden) hideLater($(id), AFTER_SPEAKING_MS);
  },
  // A newer version of this page is on the server: reload (when nothing is going on).
  version: ({ id }) => {
    if (!window.pageVersion) { window.pageVersion = id; return; }
    if (id === window.pageVersion) return;
    const reloadWhenIdle = () => (voiceState || asking || document.body.classList.contains("typing")
      ? setTimeout(reloadWhenIdle, 3000) : location.reload());
    reloadWhenIdle();
  },
  mac_chat: macChat,
  stop_listening: () => { if (!MAC) stopListening(); },
  screens: ({ phones }) => { phonesDocked = phones; },
  // Which computer Dock runs on: the talk key differs (⌥ Space on a Mac, Alt+Space on Windows).
  platform: ({ platform, talk_key }) => {
    document.body.dataset.platform = platform;
    $("compose-hint").textContent = `Talk or type · ${talk_key} opens this anywhere · Esc closes`;
  },
});

// Connect once focus.js has loaded too, so no message arrives before its handlers exist.
window.addEventListener("load", () => { updateStatus(); connect(); if (!MAC) keepAwake(); });
