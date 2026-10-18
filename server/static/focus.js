// Dock phone web app: focus mode.
// Started from the small Focus button (top left) or by voice. During a session
// the stage shows the countdown ring; the face only comes back when it has
// something to say: you stepped away, you drifted off task, or welcome back.
// The assistant keeps working during a session.
// The server keeps the real session clock; this page counts the seconds
// between updates, and uses the front camera to tell
// the server "at desk" or "away". The video never leaves the phone: face
// detection (MediaPipe) runs right here in the browser.

const MEDIAPIPE = "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14";
const FACE_MODEL = "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite";
const CHECK_EVERY_MS = 500;
const AWAY_AFTER_MS = 15000; // no face for this long means "away"
const RING = 2 * Math.PI * 90;

let focusState = { state: "idle" };
let receivedAt = Date.now();
let chosenMinutes = 50;
let nudge = null;        // { text, detail } while drifting
let welcomeUntil = 0;    // show "Welcome back!" until then
let doneAt = 0;

const isLive = (s = focusState.state) => ["running", "away", "paused"].includes(s);

// What the stage should show for focus mode (app.js asks this).
function focusInfo() {
  const s = focusState;
  if (isLive()) {
    if (s.state === "away") return { live: true, faceMoment: true, mood: "sleepy", line: "Away · timer paused", detail: s.goal };
    if (s.drifting) return { live: true, faceMoment: true, mood: "worried", line: nudge?.text || `Back to ${s.goal}?`, detail: nudge?.detail || "" };
    if (Date.now() < welcomeUntil) return { live: true, faceMoment: true, mood: "celebrate", line: "Welcome back!", detail: s.goal };
    return { live: true, faceMoment: false };
  }
  if (s.state === "break") return { live: false, mood: "celebrate", line: "Break time", detail: "Stretch, drink some water." };
  if (s.state === "done" && Date.now() - doneAt < 8000) return { live: false, mood: "celebrate", line: "Nice work!", detail: s.goal };
  return { live: false };
}

// ---- the Focus sheet ----

$("focus-button").addEventListener("click", () => {
  render();
  $("focus-sheet").showModal();
});

document.querySelectorAll("#focus-lengths .chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    document.querySelectorAll("#focus-lengths .chip").forEach((c) => c.classList.toggle("selected", c === chip));
    chosenMinutes = Number(chip.dataset.minutes);
    $("focus-custom").value = "";
  });
});

$("focus-custom").addEventListener("input", () => {
  document.querySelectorAll("#focus-lengths .chip").forEach((c) => c.classList.remove("selected"));
  chosenMinutes = Number($("focus-custom").value) || 0;
});

$("focus-go").addEventListener("click", () => {
  send({ kind: "start_focus", goal: $("focus-goal-input").value.trim(), minutes: chosenMinutes });
  $("focus-sheet").close();
});
$("focus-week").addEventListener("click", () => { send({ kind: "week_report" }); $("focus-sheet").close(); });
$("focus-pause").addEventListener("click", () => send({ kind: focusState.state === "paused" ? "resume_focus" : "pause_focus" }));
$("focus-end").addEventListener("click", () => { send({ kind: "end_focus" }); $("focus-sheet").close(); });
$("focus-camera").addEventListener("change", (event) => {
  if (!isLive()) return;
  if (event.target.checked) startCamera();
  else { stopCamera(); send({ kind: "presence", present: true }); }
});

$("report-yes").addEventListener("click", () => { send({ kind: "focus_finished", completed: true }); $("report-ask").hidden = true; });
$("report-no").addEventListener("click", () => { send({ kind: "focus_finished", completed: false }); $("report-ask").hidden = true; });
$("report-break").addEventListener("click", () => send({ kind: "start_break" }));
$("report-again").addEventListener("click", () => {
  closePanel($("focus-report"));
  send({ kind: "start_focus", goal: focusState.goal || "", minutes: Math.round((focusState.planned || 0) / 60) });
});

try { if (localStorage.getItem("dock-focus-tip-seen")) $("focus-tip").hidden = true; } catch {}

// ---- the timer ----

function clock(seconds) {
  seconds = Math.max(0, Math.round(seconds));
  const h = Math.floor(seconds / 3600), m = Math.floor((seconds % 3600) / 60), s = seconds % 60;
  return (h ? `${h}:${String(m).padStart(2, "0")}` : `${m}`) + `:${String(s).padStart(2, "0")}`;
}

function render() {
  const s = focusState;
  const live = isLive();
  const extra = s.state === "running" ? (Date.now() - receivedAt) / 1000 : 0;
  const focused = (s.focused || 0) + extra;
  const left = s.planned ? s.planned - focused : null;

  // The Focus button shows the time left while a session runs.
  const button = $("focus-button");
  button.classList.toggle("live", live && s.state !== "away");
  button.classList.toggle("away", s.state === "away");
  $("focus-button-text").textContent = !live ? (s.state === "break" ? "Break" : "Focus")
    : s.state === "away" ? "Away" : clock(left ?? focused);
  // (Mac mode) the countdown goes next to Dock's face in the menu bar.
  const menuBarText = live ? $("focus-button-text").textContent : s.state === "break" ? "Break" : "";
  if (MAC && render.menuBar !== menuBarText) { render.menuBar = menuBarText; native?.postMessage({ focus: menuBarText }); }

  // The sheet: start a session, or control the one running.
  $("focus-start").hidden = live;
  $("focus-live").hidden = !live;

  if (live) {
    $("focus-time").textContent = clock(left ?? focused);
    $("focus-state").textContent = s.state === "paused" ? "Paused" : left !== null ? "left" : "focused";
    $("focus-goal").textContent = s.goal;
    $("timer-scene").classList.toggle("paused", s.state === "paused");
    // Planned sessions: the ring empties as time runs out. Open-ended: it fills each hour.
    const fraction = left !== null ? Math.max(0, left) / s.planned : (focused % 3600) / 3600;
    $("timer-progress").style.strokeDashoffset = RING * (1 - fraction);
    $("sheet-goal").textContent = s.goal;
    const stats = [`${clock(focused)} focused`];
    if (left !== null) stats.push(`${clock(left)} left`);
    if (s.away > 0) stats.push(`${Math.round(s.away / 60)} min away`);
    if (s.drift > 0) stats.push(`${Math.round(s.drift / 60)} min drifting`);
    $("focus-stats").textContent = stats.join(" · ");
    $("focus-pause").textContent = s.state === "paused" ? "Resume" : "Pause";
  }
  if (s.state === "break") {
    $("break-left").textContent = `${clock((s.break_left || 0) - (Date.now() - receivedAt) / 1000)} left`;
  } else if (!$("focus-break").hidden) {
    closePanel($("focus-break"));
  }
  updateStage();
}
setInterval(render, 1000);

messageHandlers.focus = (message) => {
  const was = focusState.state;
  focusState = message;
  receivedAt = Date.now();
  const live = isLive();
  if (live && !isLive(was) && !MAC) {
    closePanel($("focus-report"));
    closePanel($("week"));
    if ($("focus-sheet").open) $("focus-sheet").close();
    setView("face");
    keepAwake();
    if ($("focus-camera").checked) startCamera();
    try { localStorage.setItem("dock-focus-tip-seen", "1"); } catch {}
  }
  if (was === "away" && message.state === "running") welcomeUntil = Date.now() + 4000;
  if (message.state === "done" && was !== "done") doneAt = Date.now();
  if (!message.drifting) nudge = null;
  if (!live && isLive(was)) stopCamera();
  render();
};

messageHandlers.nudge = ({ text, detail }) => {
  nudge = { text, detail };
  render();
};

// ---- report, break and week ----

messageHandlers.focus_report = (r) => {
  $("report-title").textContent = r.goal;
  const lines = [`Focused ${r.focused_min} min · on task ${r.on_task_pct}%`];
  if (r.away_min || r.away_count) lines.push(`Away ${r.away_min} min (${r.away_count}×)`);
  if (r.drift_min) lines.push(`Drifting ${r.drift_min} min`);
  if (r.questions) lines.push(`Asked Dock ${r.questions}×`);
  $("report-numbers").replaceChildren(...lines.map((l) => Object.assign(document.createElement("div"), { textContent: l })));
  $("report-apps").textContent = r.apps.length ? "Apps: " + r.apps.map((a) => `${a.app} ${a.minutes} min`).join(", ") : "";
  $("report-files").replaceChildren(...r.files.map((f) => Object.assign(document.createElement("li"), { textContent: f })));
  $("report-ask").hidden = r.completed !== null && r.completed !== undefined;
  showPanel($("focus-report"));
  cards = r.cards || [];
};

let cards = [];
let cardIndex = 0;

function showFlashcard() {
  const empty = cards.length === 0;
  $("flash-empty").hidden = !empty;
  $("flashcard").hidden = empty;
  if (empty) return;
  const card = cards[cardIndex % cards.length];
  $("flash-app").textContent = card.app;
  $("flash-name").textContent = card.name;
  $("flash-answer").replaceChildren(shortcutView(card.shortcut));
  $("flash-answer").hidden = true;
  $("flash-reveal").hidden = false;
  $("flash-next").hidden = true;
}

$("flash-reveal").addEventListener("click", () => {
  $("flash-answer").hidden = false;
  $("flash-reveal").hidden = true;
  $("flash-next").hidden = false;
});
$("flash-next").addEventListener("click", () => { cardIndex += 1; showFlashcard(); });

messageHandlers.flashcards = (message) => {
  cards = message.cards || [];
  cardIndex = 0;
  closePanel($("focus-report"));
  showFlashcard();
  showPanel($("focus-break"));
};

messageHandlers.week_report = (w) => {
  $("week-summary").textContent = w.sessions
    ? `${Math.round(w.total / 6) / 10} h focused · ${w.sessions} sessions · ${w.finished} goals finished · ${w.on_task}% on task`
    : "No sessions yet this week.";
  const most = Math.max(1, ...w.days.map((d) => d.minutes));
  $("week-days").replaceChildren(...w.days.map((d) => barRow(d.day, d.minutes / most, `${d.minutes} min`)));
  $("week-goals").replaceChildren(...w.goals.map((g) => Object.assign(document.createElement("li"), { textContent: `${g.goal}: ${g.minutes} min` })));
  showPanel($("week"));
};

// ---- desk presence with the front camera ----

let detector = null;
let stream = null;
let cameraTimer = null;
let lastFaceAt = Date.now();
let present = true;

function showPresence(text, kind) {
  $("presence-text").textContent = text;
  $("presence-dot").className = kind || "";
}

async function startCamera() {
  if (cameraTimer) return;
  try {
    showPresence("Starting camera…");
    if (!detector) {
      const vision = await import(`${MEDIAPIPE}/vision_bundle.mjs`);
      const files = await vision.FilesetResolver.forVisionTasks(`${MEDIAPIPE}/wasm`);
      detector = await vision.FaceDetector.createFromOptions(files, {
        baseOptions: { modelAssetPath: FACE_MODEL, delegate: "GPU" },
        runningMode: "VIDEO",
      });
    }
    stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "user", width: 320, height: 240 }, audio: false });
    const video = $("camera");
    video.srcObject = stream;
    await video.play();
    lastFaceAt = Date.now();
    present = true;
    showPresence("You're here", "here");
    cameraTimer = setInterval(checkFace, CHECK_EVERY_MS);
  } catch (error) {
    showPresence(error.name === "NotAllowedError" ? "Camera blocked: allow it in Chrome's site settings" : "Camera unavailable");
  }
}

function checkFace() {
  const video = $("camera");
  if (!detector || video.readyState < 2) return;
  const found = detector.detectForVideo(video, performance.now()).detections.length > 0;
  if (found) lastFaceAt = Date.now();
  const nowPresent = Date.now() - lastFaceAt < AWAY_AFTER_MS;
  if (nowPresent !== present) {
    present = nowPresent;
    send({ kind: "presence", present });
    showPresence(present ? "You're here" : "Away", present ? "here" : "away");
  }
}

function stopCamera() {
  clearInterval(cameraTimer);
  cameraTimer = null;
  stream?.getTracks().forEach((track) => track.stop());
  stream = null;
  showPresence("Camera off");
}
