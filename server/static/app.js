// Dock phone web app.
//
// Shows Dock's face, the focus timer, cards and the shortcut pad, and provides
// tap-to-talk (the simulated Alexa+ voice mode). With ?screen=mac the same page runs
// in the Mac bubble (agent/dock_agent/bubble.py).

const $ = (id) => document.getElementById(id);
const ADDRESS_URL = window.DOCK_ADDRESS_URL || "";
const statusEl = $("status");
const face = $("face");
const cardsEl = $("cards");
let socket = null;
let serverUrl = "";
let connected = false;
let failedTries = 0;
let voiceState = "";  // "", "listening", "thinking" or "speaking"
let savedThisWeek = "";
let celebrateUntil = 0;
const MAC = new URLSearchParams(location.search).get("screen") === "mac";
// Native bridge: WebKit on the Mac, pywebview on Windows (queued until it's ready).
const windowsQueue = [];
window.addEventListener("pywebviewready", () => windowsQueue.splice(0).forEach((m) => window.pywebview.api.post(m)));
const native = window.webkit?.messageHandlers?.dock
  || (MAC ? { postMessage: (m) => (window.pywebview?.api?.post ? window.pywebview.api.post(m) : windowsQueue.push(m)) } : null);
let phonesDocked = 0;  // Mac mode: phones connected besides this bubble
// Identifies this screen's own messages.
const SCREEN_ID = Math.random().toString(36).slice(2);
if (MAC) document.body.classList.add("mac");

function store(key, value) { try { localStorage.setItem(key, value); } catch {} }
function stored(key) { try { return localStorage.getItem(key) || ""; } catch { return ""; } }

// ---- pairing token ----
// Passed after "#" so it never reaches the web host.

const token = (() => {
  const fromHash = new URLSearchParams(location.hash.slice(1)).get("token");
  const fromQuery = new URLSearchParams(location.search).get("token");
  if (fromHash) {
    store("dock-token", fromHash);
    history.replaceState(null, "", location.pathname);
  }
  return fromHash || fromQuery || stored("dock-token");
})();

// ---- connection ----

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

// Message handlers by kind (focus.js adds its own).
const messageHandlers = {};

function send(message) {
  if (socket && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(message));
}

// ---- views ----

function setView(view) {
  document.body.dataset.view = view;
  document.querySelectorAll(".view-tab").forEach((t) => t.classList.toggle("active", t.dataset.view === view));
  store("dock-view", view);
  updateStage();
}
document.querySelectorAll(".view-tab").forEach((tab) => tab.addEventListener("click", () => setView(tab.dataset.view)));
if (stored("dock-view") === "pad") setView("pad");

// ---- stage: face, timer or cards ----

function visiblePanels() {
  return [...cardsEl.children].filter((p) => !p.hidden && !p.classList.contains("leaving"));
}

function updateStage() {
  const count = visiblePanels().length;
  cardsEl.dataset.count = count;
  const focus = typeof focusInfo === "function" ? focusInfo() : { live: false };
  document.body.dataset.stage = count ? "cards" : focus.live ? "timer" : "face";
  $("timer-moment").textContent = focus.live && focus.faceMoment ? focus.line : "";
  $("timer-scene").dataset.mood = focus.live && focus.faceMoment ? focus.mood : "";
  updateFace(focus);
  if (MAC) tellBubble();
}

// Mac mode: tell the bubble window whether to show and how tall to be.
function tellBubble() {
  const shown = visiblePanels().length > 0;
  const height = shown ? Math.ceil(cardsEl.getBoundingClientRect().height) + 16 : 0;
  if (tellBubble.last === `${shown}:${height}`) return;
  tellBubble.last = `${shown}:${height}`;
  native?.postMessage({ show: shown, height });
}
if (MAC) new ResizeObserver(() => tellBubble()).observe(cardsEl);
if (MAC) window.addEventListener("load", () => native?.postMessage({ ready: true }));

new MutationObserver(updateStage).observe(cardsEl, { subtree: true, childList: true, attributes: true, attributeFilter: ["hidden"] });

function showPanel(panel) {
  panel.classList.remove("leaving");
  panel.hidden = false;
  panel.shownAt = Date.now();
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

// Closing a card closes it on every screen.
function dismiss(panel, then) {
  if (panel.id) send({ kind: "close_card", id: panel.id });
  closePanel(panel, then);
}

// Answers and info cards close themselves after a while, on every screen.
function hideLater(panel, ms, { everywhere = true } = {}) {
  clearTimeout(panel.hideTimer);
  panel.hideTimer = setTimeout(() => (everywhere ? dismiss(panel) : closePanel(panel)), ms);
}

cardsEl.addEventListener("click", (event) => {
  const panel = event.target.closest(".panel");
  if (!panel) return;
  if (!event.target.closest("button, input, label") && hush()) return;
  if (event.target.closest(".close") || (panel.classList.contains("transient") && !event.target.closest("button"))) dismiss(panel);
});

// ---- face ----

function updateFace(focus) {
  let mood = "happy", line = "", detail = "";
  if (voiceState === "listening" || (!voiceState && listeningElsewhere)) { mood = "listening"; line = "Listening…"; }
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
    if (!["happy", "sleepy", "offline"].includes(mood)) wake();
  }
  const lineEl = $("face-line");
  const idle = !line && !focus?.mood && voiceState === "" && connected;
  $("face-scene").classList.toggle("idle", idle);
  if (idle) {
    lineEl.replaceChildren(...(savedThisWeek
      ? ["Dock saved you ", Object.assign(document.createElement("b"), { textContent: savedThisWeek }), " this week"]
      : ["Tap me and ask anything"]));
  } else {
    lineEl.textContent = line;
  }
  $("face-detail").textContent = detail;
}

// Blink and glance around when idle.
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

// Tapping the stage starts listening and opens the Mac chat box.
$("stage").addEventListener("click", (event) => {
  if (!event.target.closest(".panel, .chip, button, input, a")) typeOrTalk();
});

// While Dock listens or talks, a tap anywhere stops it.
document.addEventListener("click", (event) => {
  if (MAC || event.target.closest("button, input, textarea, select, a, label, dialog")) return;
  if (hush()) { event.stopPropagation(); event.preventDefault(); }
}, true);

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
  document.body.dataset.voice = state || (listeningElsewhere ? "listening" : "");
  updateStage();
}

// The computer is listening: mirror it on the phone.
let listeningElsewhere = false;
let listeningElsewhereTimer = null;
function showListeningElsewhere(on) {
  listeningElsewhere = on;
  clearTimeout(listeningElsewhereTimer);
  if (on) { wake(); listeningElsewhereTimer = setTimeout(() => showListeningElsewhere(false), 30000); }  // fallback in case "stopped" never arrives
  setVoice(voiceState);
}

// ---- shortcuts as keys ----

function shortcutView(shortcut) {
  const wrap = document.createElement("span");
  if (!shortcut) return wrap;
  if (/^(Ctrl|Alt|Shift|Win)\+/.test(shortcut)) {
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

// ---- cards ----

// While a request is being answered, hold its cards until the reply arrives.
let asking = null;
function holdForAnswer(show) {
  if (!asking) return false;
  asking.held.push(show);
  return true;
}

// Replay a card's entrance animation.
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
  $("card").classList.toggle("long", (title || "").length > 70);
  $("card-shortcut").replaceChildren(...(shortcut ? [shortcutView(shortcut)] : []));
  $("card-detail").textContent = detail || "";
  showPanel($("card"));
  hideLater($("card"), shortcut ? 12000 : Math.min(30000, 5000 + ((title || "").length + (detail || "").length) * 40));
}

// "✓ Show Ruler": a done card with the shortcut, plus a short sound.
function showDone(done) {
  if (holdForAnswer(() => showDone(done))) return;
  const { title, shortcut, detail } = done;
  $("card").classList.remove("long");
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
  try {  // two soft notes, generated
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

function showToast({ text }) {
  showDone({ title: text.replace(/^✓\s*/, "") });
}

function showTip(tip) {
  if (holdForAnswer(() => showTip(tip))) return;
  const { title, shortcut, detail, sound } = tip;
  if (sound) doneSound();
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

// ---- time saved ----

function showSavings({ week }) {
  savedThisWeek = week || "";
  $("saved-week").textContent = savedThisWeek;
  $("saved").hidden = !savedThisWeek;
  updateStage();
}

// ---- "Try saying" examples ----

const chip = (text) => Object.assign(document.createElement("button"), { type: "button", className: "chip", textContent: text });

function showExamples(app, examples) {
  if (!examples || !examples.length) return;
  $("try-chips").replaceChildren(...examples.map(chip));
}

// General suggestions next to the face: briefing, workspaces, tidy-up.
let workspaceNames = [];
function generalTips() {
  const spaces = workspaceNames.slice(0, 2).map((name) => `Open my ${name} workspace`);
  return ["Brief me on my to-dos and email", ...spaces, "Tidy up my downloads",
          "Save these windows as a workspace", "What's on my calendar today?"].slice(0, 4);
}

function showFaceTips(examples) {
  const few = examples.slice(0, 4);
  const half = Math.ceil(few.length / 2);
  $("face-tips-left").replaceChildren(...few.slice(0, half).map(chip));
  $("face-tips-right").replaceChildren(...few.slice(half).map(chip));
}
showFaceTips(generalTips());

// Tapping an example asks Dock.
for (const id of ["try-chips", "face-tips-left", "face-tips-right"]) {
  $(id).addEventListener("click", (event) => {
    const tapped = event.target.closest(".chip");
    if (!tapped) return;
    closeTyping();
    ask(tapped.textContent, { spoken: true });
  });
}

// ---- shortcut pad ----

// "⇧⌘B" -> ["⇧", "⌘", "B"]; "Ctrl+Shift+S" -> ["Ctrl", "Shift", "S"]
function shortcutKeys(shortcut) {
  if (!shortcut) return [];
  if (shortcut.includes("+") && shortcut.length > 1) return shortcut.split("+").filter(Boolean);
  const modifiers = shortcut.match(/^[⌃⌥⇧⌘]*/)[0];
  return [...modifiers, shortcut.slice(modifiers.length)].filter(Boolean);
}

function showPad({ app, buttons, examples }) {
  showExamples(app, examples);
  $("pad-app").textContent = buttons.length ? app : `No shortcuts for ${app}`;
  $("pad").replaceChildren(...buttons.map((button) => {
    const el = Object.assign(document.createElement("button"), { type: "button", className: "pad-button" });
    const title = Object.assign(document.createElement("span"), { className: "pad-title", textContent: button.title });
    const keys = Object.assign(document.createElement("span"), { className: "pad-keys" });
    keys.append(...shortcutKeys(button.shortcut).map((key) => Object.assign(document.createElement("kbd"), { textContent: key })));
    el.append(title, keys);
    el.addEventListener("click", () => {
      send({ kind: "press", path: button.path });
      el.classList.add("pressed");
      setTimeout(() => el.classList.remove("pressed"), 400);
    });
    return el;
  }));
}

// ---- Downloads tidy-up ----

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

// Long lists scroll inside the card, with a fade at the bottom.
function showMoreHint(list) {
  requestAnimationFrame(() => list.classList.toggle("more", list.scrollTop + list.clientHeight < list.scrollHeight - 2));
}
["plan-moves", "downloads-list", "mail-list", "mail-plan-list"].forEach((id) => $(id).addEventListener("scroll", () => showMoreHint($(id))));

$("plan-move").addEventListener("click", () => {
  const items = [...document.querySelectorAll("#plan-moves input:checked")].map((box) => Number(box.value));
  if (items.length) send({ kind: "move", items });
  dismiss($("plan"));
});
$("plan-cancel").addEventListener("click", () => dismiss($("plan")));

// ---- folder suggestions ----

function makeButton(text, className, onClick) {
  const el = Object.assign(document.createElement("button"), { type: "button", textContent: text, className });
  el.addEventListener("click", onClick);
  return el;
}

function suggestionItem({ name, question, folder, newFolder, why, buttons }) {
  const item = document.createElement("li");
  const where = Object.assign(document.createElement("div"), { className: "download-to" });
  // allow wrapping after "/"
  if (folder) where.append(question, Object.assign(document.createElement("b"), { textContent: folder.replaceAll("/", "/\u200b") }), newFolder ? " (new folder)?" : "?");
  else where.textContent = question;
  const actions = Object.assign(document.createElement("div"), { className: "row" });
  actions.append(...buttons.map(([text, className, onClick]) => makeButton(text, className, () => onClick(item))));
  item.append(Object.assign(document.createElement("div"), { className: "download-name", textContent: name }), where);
  if (why) item.append(Object.assign(document.createElement("div"), { className: "move-why", textContent: why }));
  item.append(actions);
  return item;
}

// Remove one suggestion (the card goes with the last one).
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
      ["Other…", "secondary other", () => openTyping(`Put ${file} in `)],
      ["Not now", "secondary", (el) => { send({ kind: "keep_download", file }); removeItem(el); }],
    ],
  });
  item.dataset.file = file;
  addItem(item);
}

// Save dialog open: "Save it in …?".
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

// Suggestions are off: ask first.
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

// × means "Not now" for every file on the card.
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

// ---- speech ----

// Speak in sentence-sized pieces (Chrome cuts long utterances). `done` runs at the end.
let macSpeechDone = null;
window.speechDone = () => { const done = macSpeechDone; macSpeechDone = null; setVoice(""); done?.(); };

// Muted: show answers without speaking; `done` still runs.
let muted = stored("dock-muted") === "1";
function showMuted() {
  $("mute-button").classList.toggle("on", muted);
  $("mute-button").setAttribute("aria-pressed", String(muted));
  $("mute-button").setAttribute("aria-label", muted ? "Unmute Dock" : "Mute Dock");
}
showMuted();
$("mute-button").addEventListener("click", () => {
  muted = !muted;
  store("dock-muted", muted ? "1" : "0");
  if (muted && window.speechSynthesis) speechSynthesis.cancel();
  showMuted();
});

function speak(text, done) {
  if (muted) {
    const id = (speak.id = (speak.id || 0) + 1);
    setTimeout(() => { if (speak.id === id) done?.(); }, Math.min(15000, 4000 + text.length * 50));
    return;
  }
  if (MAC) {  // Mac mode: voice_out.py speaks, then calls speechDone()
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
      if (speak.id !== id) return;
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

// ---- email ----

// One email row: sender, time, gist and an optional to-do button.
function mailItem(m) {
  const item = document.createElement("li");
  if (m.urgent) item.classList.add("urgent");
  const top = Object.assign(document.createElement("div"), { className: "mail-from" });
  top.append(m.from, Object.assign(document.createElement("span"), { className: "mail-when", textContent: m.when }));
  item.append(top, Object.assign(document.createElement("div"), { className: "mail-gist", textContent: m.gist || m.subject }));
  if (m.todo) {
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

// Morning briefing card. ask: the Brief me / Not now offer.
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
$("briefing-no").addEventListener("click", () => { send({ kind: "briefing", yes: false }); dismiss($("briefing")); });

// Inbox clean-up checklist; nothing moves until Clean up.
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
  dismiss($("mail-plan"));
});
for (const id of ["mail-plan-no"]) $(id).addEventListener("click", () => { send({ kind: "mail_cleanup_cancel" }); dismiss($("mail-plan")); });
$("mail-plan").querySelector(".close").addEventListener("click", () => send({ kind: "mail_cleanup_cancel" }));

// ---- writing help ----

// Nothing changes until the user picks Replace, Insert below or Change more.
function showWriting({ app, parts, title }) {
  if (holdForAnswer(() => showWriting({ app, parts, title }))) return;
  $("writing-title").textContent = `${title} · ${app}`;
  $("writing-text").replaceChildren(...parts.map(([kind, text]) =>
    kind ? Object.assign(document.createElement(kind === "add" ? "ins" : "del"), { textContent: text }) : document.createTextNode(text)));
  replay($("writing"));
  showPanel($("writing"));
}
const useWriting = (where) => { send({ kind: "writing_use", where }); dismiss($("writing")); };
$("writing-replace").addEventListener("click", () => useWriting("replace"));
$("writing-below").addEventListener("click", () => useWriting("below"));
$("writing").querySelector(".close").addEventListener("click", () => send({ kind: "writing_use", where: "cancel" }));
$("writing-more").addEventListener("click", () => {
  if (MAC) send({ kind: "open_mac_chat" });
  else listen();
});

// ---- search offer ----

let offeredSearch = "";
function showSearchOffer({ query, why }) {
  if (holdForAnswer(() => showSearchOffer({ query, why }))) return;
  offeredSearch = query;
  $("search-why").textContent = why ? `${why} · Search Google?` : "Search Google?";
  $("search-query").textContent = query;
  replay($("search"));
  showPanel($("search"));
}
$("search-go").addEventListener("click", () => { send({ kind: "search_go", go: true, query: offeredSearch }); dismiss($("search")); });
$("search-no").addEventListener("click", () => { send({ kind: "search_go", go: false }); dismiss($("search")); });
$("search").querySelector(".close").addEventListener("click", () => send({ kind: "search_go", go: false }));

// ---- recap ----

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

function showRecap(recap) {
  if (holdForAnswer(() => showRecap(recap))) return;
  const { day, apps, summary } = recap;
  $("recap-day").textContent = day;
  $("recap-summary").textContent = summary || "";
  const most = Math.max(1, ...apps.map((a) => a.minutes));
  $("recap-apps").replaceChildren(...apps.map((a) => barRow(a.app, a.minutes / most, minutesText(a.minutes))));
  showPanel($("recap"));
  hideLater($("recap"), 90000);
}

// ---- asking Dock ----

// Spoken requests get spoken replies; typed ones are only shown. Quiet commands get
// a check mark and a sound. Slow answers get a short waiting line first.
const BRIEFING_ASK = /\b(good morning|brief me|my briefing|catch me up)\b/i;
const GREET_AFTER_MS = 2000;
const WAIT_LINE_AFTER_MS = 2000;
const GREETINGS = [
  "Good morning! Let me check your day.",
  "Morning! Pulling up your day.",
  "Good morning! One sec, checking your calendar and email.",
  "Hey, good morning! Let's see what's on today.",
  "Morning! Grabbing your plan for today.",
];
const WAIT_LINES = {
  question: ["Let me look.", "Let me check.", "Good question, one sec.", "Looking into it."],
  other: ["One sec.", "On it.", "Working on it.", "Just a moment."],
};
const QUESTION = /^(what|where|how|why|when|who|which|is|are|do|does|can|could|should|did)\b|\?\s*$/i;
let demoMode = false;  // test label: skip the waiting line
const pickOne = (lines) => lines[Math.floor(Math.random() * lines.length)];

async function ask(text, { spoken }) {
  const me = startAnswer(text);
  let answer, quiet = false;
  let greeting = null;
  const briefing = BRIEFING_ASK.test(text);
  const line = briefing ? pickOne(GREETINGS) : pickOne(WAIT_LINES[QUESTION.test(text) ? "question" : "other"]);
  const greet = spoken && !(briefing && demoMode) ? setTimeout(() => {
    greeting = new Promise((said) => speak(line, () => { setVoice("thinking"); said(); }));
  }, briefing ? GREET_AFTER_MS : WAIT_LINE_AFTER_MS) : null;
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
  clearTimeout(greet);
  if (greeting) {
    await greeting;
    if (briefing) answer = answer.replace(/^Good morning[.!]?\s*/i, "");
  }
  finishAnswer(me, text, answer, quiet, { speakHere: spoken });
}

// Other screens mirror the request; only the screen that was asked speaks.
function startAnswer(text) {
  const me = (asking = { held: [] });
  showAnswer(text, "", true);
  setVoice("thinking");
  return me;
}

function finishAnswer(me, text, answer, quiet, { speakHere, spokenElsewhere = false }) {
  if (asking === me) asking = null;
  setVoice("");
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
  else if (spokenElsewhere) hideLater(shown, Math.max(6000, answer.length * 80), { everywhere: false });
  else if (!withCard) hideLater($("answer"), Math.min(15000, 5000 + answer.length * 50));
}

let othersAsking = null;
const otherAnswers = {
  asking: ({ from, text }) => {
    if (from === SCREEN_ID) return;
    if (listeningElsewhere) showListeningElsewhere(false);
    othersAsking = startAnswer(text);
  },
  answered: ({ from, text, reply, quiet, spoken }) => {
    if (from === SCREEN_ID || !othersAsking) return;
    const me = othersAsking;
    othersAsking = null;
    finishAnswer(me, text, reply, quiet, { speakHere: false, spokenElsewhere: spoken });
  },
};

// Speech finished: close the card here and on the other screens.
const AFTER_SPEAKING_MS = 900;
function finishedSpeaking(panel) {
  hideLater(panel, panel.classList.contains("long") ? 10000 : AFTER_SPEAKING_MS);
  send({ kind: "speech_done", from: SCREEN_ID });
}

// ---- Mac mode: called by agent/dock_agent/talk.py ----

// "Listening…" with the words so far; null hides it.
window.macListening = (words) => {
  if (words === null) { closePanel($("answer")); return; }
  showAnswer(words, "Listening", true);
  setVoice("listening");
};

// Chat box under the menu bar.
window.macCompose = (open) => {
  toldTyping = false;
  if (!open) { closePanel($("compose")); return; }
  $("compose-tips").replaceChildren(...[...$("try-chips").children].slice(0, 4).map((c) => chip(c.textContent)));
  showPanel($("compose"));
  setTimeout(() => $("compose-input").focus(), 50);
};

// Show the mic button state.
let macHearing = false;
window.macMic = (on) => {
  macHearing = on;
  $("compose-mic").classList.toggle("on", on);
  send({ kind: "listening", on, from: SCREEN_ID });
};

let toldTyping = false;
$("compose-input").addEventListener("input", () => {
  if (toldTyping) return;
  toldTyping = true;
  send({ kind: "mac_typing" });
  if (voiceState === "listening") native?.postMessage({ listen: "cancel" });
});

// Close the chat box first so the user's app gets the keyboard back.
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
  if (voiceState === "listening") native?.postMessage({ listen: "cancel" });
  if (!$("compose").hidden) native?.postMessage({ compose: false });
});

// Ask Dock what was said.
window.macAsk = (text) => {
  if (!text) { setVoice(""); closePanel($("answer")); return; }
  if (!$("compose").hidden) sendFromChatBox(text, true);
  else ask(text, { spoken: true });
};

// ---- typing ----

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
  send({ kind: "open_mac_chat" });
  listen({ alongsideMac: true });
}

function macChat() {}

$("type-button").addEventListener("click", () => { openTyping(); listen({ alongsideTyping: true }); });
$("chat-close").addEventListener("click", () => { stopListening(); closeTyping(); });
$("chat-mic").addEventListener("click", () => { closeTyping(); listen(); });
// Typing stops listening.
chatInput.addEventListener("input", () => { if (voiceState === "listening") stopListening(); });
$("chat").addEventListener("submit", (event) => {
  event.preventDefault();
  const text = chatInput.value.trim();
  if (!text) return;
  closeTyping();
  ask(text, { spoken: false });
});

// ---- tap to talk ----

const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;

let recognition = null;

// Listen once. alongsideTyping / alongsideMac: close the keyboard or Mac chat box when speech starts.
function listen({ alongsideTyping = false, alongsideMac = false } = {}) {
  if (voiceState === "listening") return;
  if (!Recognition) {
    if (!alongsideTyping) {
      showAnswer("", "This browser can't do speech recognition. Try Chrome, or type instead.");
      hideLater($("answer"), 8000, { everywhere: false });
    }
    return;
  }
  speechSynthesis.cancel();
  recognition = new Recognition();
  recognition.lang = "en-US";
  recognition.interimResults = true;
  recognition.onstart = () => {
    setVoice("listening");
    // No face visible: show a small listening card.
    if (document.body.dataset.stage !== "face" || document.body.dataset.view === "pad") showAnswer("", "Listening", true);
  };
  recognition.onend = () => { if (voiceState === "listening") setVoice(""); recognition = null; };
  recognition.onresult = (event) => {
    const words = [...event.results].map((r) => r[0].transcript).join(" ").trim();
    if (!words) return;
    if (document.body.classList.contains("typing")) closeTyping();
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
    if (event.error !== "no-speech" && event.error !== "aborted" && !alongsideTyping && !alongsideMac) {
      showAnswer("", `Microphone problem: ${event.error}`);
      hideLater($("answer"), 8000, { everywhere: false });
    }
  };
  try {
    recognition.start();
    setVoice("listening");
  } catch {
    recognition = null;
  }
}

// Test remote (remote.html): the tapped phrase is used as the transcript on the listening screen.
const REMOTE_WORD_MS = 170;
function heardFromRemote(text) {
  if (MAC) {
    if (!macHearing) return;
    native?.postMessage({ listen: "cancel" });
    setTimeout(() => window.macListening(""), 150);
    setTimeout(() => window.macAsk(text), 800);
  } else if (voiceState === "listening") {
    if (recognition) {
      recognition.onresult = recognition.onerror = recognition.onend = null;
      recognition.abort();
      recognition = null;
    }
    const words = text.split(/\s+/);
    words.forEach((_, n) => setTimeout(() => showAnswer(words.slice(0, n + 1).join(" "), "Listening", true), n * REMOTE_WORD_MS));
    setTimeout(() => {
      send({ kind: "close_mac_chat" });
      ask(text, { spoken: true });
    }, words.length * REMOTE_WORD_MS + 350);
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

// ---- screen: keep awake, dim when idle ----

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

// Request full screen on tap (not needed when installed as an app).
function goFullScreen() {
  if (MAC || document.fullscreenElement || !document.documentElement.requestFullscreen) return;
  if (matchMedia("(display-mode: fullscreen)").matches) return;
  document.documentElement.requestFullscreen({ navigationUI: "hide" }).catch(() => {});
}

document.addEventListener("pointerdown", () => {
  if (!MAC && !audio && window.AudioContext) { try { audio = new AudioContext(); } catch {} }
  wake();
  keepAwake();
}, true);
document.addEventListener("pointerup", goFullScreen, true);
document.addEventListener("click", goFullScreen, true);

// Report display mode to the server log for debugging.
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
  // Reset stray scroll offsets that push the face off center (phone, face only).
  if (!MAC && document.body.dataset.stage === "face" && document.body.dataset.view === "face"
      && !document.body.classList.contains("typing")) {
    if (window.scrollY || document.documentElement.scrollTop) window.scrollTo(0, 0);
    if ($("main").scrollTop) $("main").scrollTop = 0;
  }
}, 1000);

// ---- sheets ----

document.querySelectorAll(".sheet").forEach((sheet) => {
  sheet.querySelector(".close").addEventListener("click", () => sheet.close());
  sheet.addEventListener("click", (event) => { if (event.target === sheet) sheet.close(); });
});
$("settings-button").addEventListener("click", () => $("settings-sheet").showModal());

$("folder-suggestions").addEventListener("change", (event) => {
  send({ kind: "set_folder_suggestions", on: event.target.checked });
});

function showSettings({ folder_suggestions }) {
  $("folder-suggestions").checked = Boolean(folder_suggestions);
}

// ---- install as an app ----

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
if ("serviceWorker" in navigator && !MAC) navigator.serviceWorker.register("sw.js").catch(() => {});

Object.assign(messageHandlers, {
  card: showCard, done: showDone, toast: showToast, tip: showTip, mail: showMail, mail_plan: showMailPlan, briefing: showBriefing,
  writing: showWriting, writing_done: () => closePanel($("writing")),
  search_offer: showSearchOffer, search_done: () => closePanel($("search")),
  briefing_done: () => { if (!$("briefing-ask").hidden) closePanel($("briefing")); }, mail_plan_done: () => closePanel($("mail-plan")), pad: showPad, plan: showPlan, download: showDownload, download_done: hideDownload,
  save_panel: showSavePanel, save_panel_done: hideSavePanel, save_ask: showSaveAsk, save_ask_done: hideSaveAsk,
  settings: showSettings, read: startReading, recap: showRecap,
  close_card: ({ id }) => {
    const panel = document.getElementById(id);
    if (panel?.classList.contains("panel") && Date.now() - (panel.shownAt || 0) > 800) closePanel(panel);
  },
  savings: showSavings,
  say: ({ text, show = true }) => {
    if (show) showAnswer("", text);
    if (MAC && phonesDocked) {
      if (show) hideLater($("answer"), Math.max(6000, text.length * 80));
      return;
    }
    speak(text, () => finishedSpeaking($("answer")));
  },
  ...otherAnswers,
  speech_done: ({ from }) => {
    if (from === SCREEN_ID || asking || voiceState) return;
    for (const id of ["card", "answer"]) if (!$(id).hidden) hideLater($(id), AFTER_SPEAKING_MS, { everywhere: false });
  },
  // Reload when a newer version of the page is available.
  version: ({ id }) => {
    if (!window.pageVersion) { window.pageVersion = id; return; }
    if (id === window.pageVersion) return;
    const reloadWhenIdle = () => (voiceState || asking || document.body.classList.contains("typing")
      ? setTimeout(reloadWhenIdle, 3000) : location.reload());
    reloadWhenIdle();
  },
  mac_chat: macChat,
  stop_listening: () => { if (!MAC) stopListening(); },
  listening: ({ on, from }) => { if (!MAC && from !== SCREEN_ID) showListeningElsewhere(Boolean(on)); },
  heard: ({ text }) => heardFromRemote(text),
  workspaces: ({ names }) => { workspaceNames = names || []; showFaceTips(generalTips()); },
  screens: ({ phones }) => { phonesDocked = phones; },
  platform: ({ platform, talk_key, demo }) => {
    demoMode = Boolean(demo);
    document.body.dataset.platform = platform;
    $("compose-hint").textContent = `Talk or type · ${talk_key} opens this anywhere · Esc closes`;
  },
});

// Connect once focus.js has loaded.
window.addEventListener("load", () => { updateStatus(); connect(); if (!MAC) keepAwake(); });
