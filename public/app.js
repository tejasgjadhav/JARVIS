/* ═══════════════════════════════════════════════════════════
   J.A.R.V.I.S. — Frontend Core
   ═══════════════════════════════════════════════════════════ */

// ─── State ────────────────────────────────────────────────
const state = {
  model:          'auto',
  history:        [],
  emails:         [],
  gmailConnected: false,
  voiceEnabled:   true,
  // Continuous listening
  continuousOn:   true,   // mic always on, listening for the wake word
  awake:          false,  // true during the 15s command window after "Jarvis"
  isListening:    false,  // recognition currently active
  isHearing:      false,  // user speech detected mid-stream
  isSpeaking:     false,  // TTS currently playing
  selectedVoice:  null,
  recognition:    null,
  // Speaking sidebar
  speakLog:       [],     // [{text, time}]
  sidebarOpen:    false,
  typerTimer:     null,
};

// ─── TTS Streaming Pipeline ───────────────────────────────
const tts = { buf: '', q: [], active: false, done: false, full: '' };

// ─── DOM Refs ─────────────────────────────────────────────
const $ = id => document.getElementById(id);

const clock          = $('clock');
const dateDisplay    = $('dateDisplay');
const chatMessages   = $('chatMessages');
const messageInput   = $('messageInput');
const sendBtn        = $('sendBtn');
const micBtn         = $('micBtn');
const micIcon        = $('micIcon');
const whisperBtn     = $('whisperBtn');
const whisperIcon    = $('whisperIcon');
const voiceStatus    = $('voiceStatus');
const thinkingBar    = $('thinkingBar');
const modelSelector  = $('modelSelector');
const modelIndicator = $('modelIndicator');
const voiceToggleBtn = $('voiceToggleBtn');
const audioLogBtn    = $('audioLogBtn');
const briefingBtn    = $('briefingBtn');
const clearBtn       = $('clearBtn');
const gmailConnectBtn   = $('gmailConnectBtn');
const refreshEmailsBtn  = $('refreshEmailsBtn');
const getDailyBriefBtn  = $('getDailyBriefBtn');
const emailList      = $('emailList');
const emailStats     = $('emailStats');
const unreadCount    = $('unreadCount');
const priorityCount  = $('priorityCount');
const gmailPill      = $('gmailPill');
const voicePill      = $('voicePill');
const analyzeBtn     = $('analyzeBtn');
const buildModelBtn  = $('buildModelBtn');
const reportSymbol   = $('reportSymbol');
const genReportBtn   = $('genReportBtn');
const reportStatus   = $('reportStatus');
const reportResult   = $('reportResult');
const reportVerdict  = $('reportVerdict');
const reportSummary  = $('reportSummary');
const dlExcel        = $('dlExcel');
const dlPdf          = $('dlPdf');
const bgCanvas       = $('bgCanvas');
const vizCanvas      = $('vizCanvas');
const arcReactor     = $('arcReactor');
// Sidebar
const sidebar        = $('speakingSidebar');
const sidebarClose   = $('sidebarClose');
const sbNow          = $('sbNow');
const sbNowText      = $('sbNowText');
const sbCursor       = $('sbCursor');
const sbHistory      = $('sbHistory');
const sbHistLabel    = $('sbHistLabel');

// ─── Init ─────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', async () => {
  updateClock();
  setInterval(updateClock, 1000);
  initBgCanvas();
  initVizCanvas();
  initVoiceSynth();
  initSpeechRecognition();     // always-on continuous listening (original working input)
  setupEventListeners();
  checkUrlFlags();
  checkGmailStatus();

  // Boot welcome
  await sleep(500);
  const bootMsg =
    `${getGreeting()}, Master. J.A.R.V.I.S. is fully operational.\n\n` +
    `All systems online — financial core and voice interface active.\n\n` +
    `Say **"Jarvis"** then your command (e.g. "Jarvis, analysis on Infosys"). ` +
    `The mic opens for 15 seconds each time, and "Jarvis" also interrupts me.`;

  addMessage('jarvis', bootMsg);

  if (state.voiceEnabled) {
    await sleep(300);
    // NB: greeting must NOT contain the wake word, or it self-triggers.
    speak(`${getGreeting()}, Master. All systems online and standing by, Sir.`);
  }
  closeCommandWindow();   // idle: mic on, awaiting the wake word
});

// ─── Clock ────────────────────────────────────────────────
function updateClock() {
  const n = new Date();
  clock.textContent = n.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
  dateDisplay.textContent = n.toLocaleDateString('en-US', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' }).toUpperCase();
}

function getGreeting() {
  const h = new Date().getHours();
  return h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening';
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

// ═══════════════════════════════════════════════════════════
//  CONTINUOUS VOICE RECOGNITION
// ═══════════════════════════════════════════════════════════

function initSpeechRecognition() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) {
    voicePill.textContent = '🚫 NO VOICE API';
    voicePill.style.color = '#ff4422';
    state.continuousOn = false;
    updateMicUI();
    return;
  }

  const rec = new SR();
  rec.continuous      = true;   // ← always-on
  rec.interimResults  = true;
  rec.lang            = 'en-IN';   // Indian English — far better for Indian-accented speech
  rec.maxAlternatives = 1;

  let interimTimeout = null;

  rec.onresult = e => {
    let interim = '', finalText = '';
    for (let i = e.resultIndex; i < e.results.length; i++) {
      e.results[i].isFinal
        ? (finalText += e.results[i][0].transcript)
        : (interim   += e.results[i][0].transcript);
    }

    const raw = (finalText || interim);
    // Accept common mishears of "Jarvis" (cloud STT is unreliable on one short word)
    const hasWake = WAKE_RE.test(raw);
    const isFinal = !!finalText.trim();
    const okLen = s => s.replace(/[^a-z0-9]/gi, '').length >= 2;

    // Show what the recogniser heard while idle, so mis-hears are visible.
    if (!state.awake && !state.isSpeaking && raw.trim()) {
      setVoiceStatus('heard: ' + raw.trim().slice(0, 40));
    }

    // ── While JARVIS is speaking: only "Jarvis" interrupts (and wakes the mic) ──
    if (state.isSpeaking) {
      if (hasWake) {
        speechSynthesis.cancel();
        state.isSpeaking = false;
        sidebar.classList.remove('speaking');
        arcReactor?.classList.remove('speaking');
        openCommandWindow();
        const cmd = stripWake(raw);
        if (isFinal && okLen(cmd)) { sendMessage(cmd); closeCommandWindow(); }
      }
      return;
    }

    // ── Not awake: ignore ALL audio until the wake word "Jarvis" ──
    if (!state.awake) {
      if (hasWake) {
        openCommandWindow();
        const cmd = stripWake(raw);
        if (isFinal && okLen(cmd)) { sendMessage(cmd); closeCommandWindow(); }   // "Jarvis, analyse Infosys"
      }
      return;   // ambient noise / "good morning" → ignored
    }

    // ── Awake (15-second window): capture the command ──
    clearTimeout(interimTimeout);
    const cmd = stripWake(raw).trim();
    if (cmd) { messageInput.value = cmd; setMicState('hearing'); }
    if (isFinal && okLen(cmd)) {
      messageInput.value = '';
      sendMessage(cmd);
      closeCommandWindow();
    } else {
      interimTimeout = setTimeout(() => {
        const val = stripWake(messageInput.value).trim();
        if (val && okLen(val) && state.awake) { messageInput.value = ''; sendMessage(val); closeCommandWindow(); }
      }, 2500);
    }
  };

  rec.onerror = e => {
    if (e.error === 'not-allowed' || e.error === 'service-not-allowed') {
      setVoiceStatus('MIC BLOCKED — allow microphone access');
      state.continuousOn = false;   // can't recover without permission
      return;
    }
    if (e.error === 'aborted') return;   // intentional stop
    // no-speech / network / audio-capture → just keep restarting
    if (state.continuousOn) scheduleRestart(300);
  };

  rec.onend = () => {
    state.isListening = false;
    state.lastRecEnd = Date.now();
    if (state.continuousOn) scheduleRestart(150);   // near-instant restart → minimal listening gap
    else updateMicUI();
  };

  rec.onstart = () => {
    state.isListening = true;
    state.lastRecActivity = Date.now();
    if (state.awake) { setMicState('hearing'); setVoiceStatus('LISTENING — speak your command'); }
    else { setMicState('continuous'); setVoiceStatus('AWAITING WAKE WORD — say “Jarvis”'); }
  };

  state.recognition = rec;
  if (state.continuousOn) scheduleRestart(200);

  // ── Watchdog: keep the mic ALWAYS on. If the recogniser silently dies
  //    (network blip, Chrome's ~60s cap), force it back to life.
  if (!state._micWatchdog) {
    state._micWatchdog = setInterval(() => {
      if (state.continuousOn && !state.isListening && !state.isSpeaking) {
        try { state.recognition.start(); }
        catch (_) { scheduleRestart(200); }
      }
    }, 2500);
  }
}

// ═══════════════════════════════════════════════════════════
//  WHISPER FLOW — push-to-talk, local faster-whisper backend
// ═══════════════════════════════════════════════════════════
let whisperRecorder = null, whisperChunks = [], whisperActive = false, whisperResume = false;

async function toggleWhisper() {
  if (whisperActive) { stopWhisper(); return; }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    // Free the mic from the always-on browser recogniser while we record.
    whisperResume = state.continuousOn;
    if (state.continuousOn) stopContinuousListening();

    whisperChunks = [];
    whisperRecorder = new MediaRecorder(stream);
    whisperRecorder.ondataavailable = e => { if (e.data.size) whisperChunks.push(e.data); };
    whisperRecorder.onstop = async () => {
      stream.getTracks().forEach(t => t.stop());
      const blob = new Blob(whisperChunks, { type: whisperRecorder.mimeType || 'audio/webm' });
      await sendToWhisper(blob);
      if (whisperResume) startContinuousListening();
    };
    whisperRecorder.start();
    whisperActive = true;
    whisperBtn.classList.add('recording');
    whisperIcon.textContent = '⏹';
    setVoiceStatus('WHISPER REC');
  } catch (err) {
    setVoiceStatus('MIC ERROR');
  }
}

function stopWhisper() {
  if (whisperRecorder && whisperRecorder.state !== 'inactive') whisperRecorder.stop();
  whisperActive = false;
  whisperBtn.classList.remove('recording');
  whisperIcon.textContent = '🌀';
}

async function sendToWhisper(blob) {
  setVoiceStatus('TRANSCRIBING…');
  const fd = new FormData();
  fd.append('audio', blob, 'clip.webm');
  try {
    const res = await fetch('/api/transcribe', { method: 'POST', body: fd });
    const data = await res.json();
    if (data.text) {
      messageInput.value = '';
      sendMessage(data.text);
    } else {
      setVoiceStatus(data.error ? 'STT ERROR' : 'NO SPEECH');
    }
  } catch (e) {
    setVoiceStatus('STT FAIL');
  }
}

// ═══ Wake word "Jarvis" → open a 15-second command window ═══
let awakeTimer = null;
const WAKE_WINDOW_MS = 15000;

// Cloud STT mangles one short word — accept close phonetic variants of "Jarvis".
const WAKE_RE = /\b(jarvis|jarvi|jarves|jarvez|jarvix|jervis|jervis|jarwis|jaravis|jharvis|garvis|gervais|jarbis|charvis|travis)\b/i;

function stripWake(t) {
  return (t || '').replace(new RegExp(WAKE_RE.source, 'gi'), ' ')
                  .replace(/^[\s,.:;!-]+/, '').replace(/\s{2,}/g, ' ').trim();
}

function openCommandWindow() {
  state.awake = true;
  clearTimeout(awakeTimer);
  awakeTimer = setTimeout(closeCommandWindow, WAKE_WINDOW_MS);
  setMicState('hearing');
  voicePill.textContent = '● LISTENING (15s)';
  voicePill.className = 'status-pill gmail-on';
  setVoiceStatus('LISTENING — speak your command');
  arcReactor?.classList.add('listening');
}

function closeCommandWindow() {
  state.awake = false;
  clearTimeout(awakeTimer);
  messageInput.value = '';
  setMicState('continuous');
  voicePill.textContent = '● SAY “JARVIS”';
  voicePill.className = 'status-pill';
  setVoiceStatus('AWAITING WAKE WORD');
  arcReactor?.classList.remove('listening');
}

let restartTimeout = null;
function scheduleRestart(delay = 500) {
  clearTimeout(restartTimeout);
  restartTimeout = setTimeout(() => {
    if (!state.continuousOn || state.isListening) return;   // stays alive during TTS for barge-in
    try { state.recognition.start(); } catch (_) {}
  }, delay);
}

function startContinuousListening() {
  state.continuousOn = true;
  setMicState('continuous');
  voicePill.textContent = '● LISTENING';
  voicePill.className = 'status-pill gmail-on';
  scheduleRestart(100);
}

function stopContinuousListening() {
  state.continuousOn = false;
  clearTimeout(restartTimeout);
  try { state.recognition?.stop(); } catch (_) {}
  state.isListening = false;
  setMicState('off');
  voicePill.textContent = '🎙 VOICE OFF';
  voicePill.className = 'status-pill';
  setVoiceStatus('OFF');
  messageInput.placeholder = 'Type your command, Master...';
}

function pauseListeningForSpeech() {
  // Keep the mic LIVE while JARVIS talks so the user can barge in to interrupt.
  setMicState('paused');
  setVoiceStatus('SPEAKING — say anything to interrupt');
  if (state.continuousOn && !state.isListening) scheduleRestart(150);
}

function resumeListeningAfterSpeech() {
  if (!state.continuousOn) return;
  setMicState('continuous');
  setVoiceStatus('LISTENING');
  scheduleRestart(700); // slight pause after speech ends
}

// ─── Mic visual state ─────────────────────────────────────
function setMicState(st) {
  micBtn.classList.remove('continuous', 'hearing', 'paused', 'off', 'listening');
  micIcon.textContent = st === 'off' ? '🔇' : '🎙';
  // reactor pulses blue while actively listening/hearing
  if (arcReactor) arcReactor.classList.toggle('listening', st === 'continuous' || st === 'hearing');

  if (st === 'continuous') {
    micBtn.classList.add('continuous');
    messageInput.placeholder = 'Listening... or type your command, Master.';
  } else if (st === 'hearing') {
    micBtn.classList.add('hearing');
    messageInput.placeholder = 'Hearing you, Master...';
  } else if (st === 'paused') {
    micBtn.classList.add('paused');
  } else if (st === 'off') {
    micBtn.classList.add('off');
    messageInput.placeholder = 'Type your command, Master...';
  }
}

function updateMicUI() {
  if (!state.continuousOn) setMicState('off');
  else if (state.isSpeaking) setMicState('paused');
  else setMicState('continuous');
}

function setVoiceStatus(txt) { voiceStatus.textContent = txt; }

// ═══════════════════════════════════════════════════════════
//  VOICE SYNTHESIS + SPEAKING SIDEBAR
// ═══════════════════════════════════════════════════════════

function initVoiceSynth() {
  const load = () => {
    const voices = speechSynthesis.getVoices();
    const preferred = ['Daniel', 'Google UK English Male', 'Microsoft George', 'Arthur', 'en-GB'];
    for (const p of preferred) {
      const v = voices.find(v => v.name.includes(p) || v.lang === p);
      if (v) { state.selectedVoice = v; break; }
    }
    if (!state.selectedVoice)
      state.selectedVoice = voices.find(v => v.lang.startsWith('en')) || voices[0] || null;
  };
  speechSynthesis.onvoiceschanged = load;
  load();
}

// ═══════════════════════════════════════════════════════════
//  PUSH-TO-TALK — mic records ONLY when you press it, then
//  auto-sends when you stop talking. It never listens on its own,
//  so ambient noise can't become a command. Whisper = accurate STT.
// ═══════════════════════════════════════════════════════════
let vadStream = null, vadAnalyser = null, vadData = null;
let autoVoiceOn = false;                 // true while actively recording (push-to-talk)
let pttRAF = null, pttHadSpeech = false, pttSilenceMs = 0, pttLastTs = 0, pttStartTs = 0;
let avRecorder = null, avChunks = [];
let bargeRAF = null;

const AV_ON = 0.05;              // speech-level threshold (RMS)
const PTT_END_SILENCE = 1200;   // stop after this much trailing silence
const PTT_MAX_MS = 15000;       // hard cap on one utterance

async function initAutoVoice() {
  if (vadAnalyser) return true;
  try {
    vadStream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }
    });
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const src = ctx.createMediaStreamSource(vadStream);
    vadAnalyser = ctx.createAnalyser();
    vadAnalyser.fftSize = 512;
    src.connect(vadAnalyser);
    vadData = new Uint8Array(vadAnalyser.fftSize);
    return true;
  } catch (e) { return false; }
}

function avRms() {
  vadAnalyser.getByteTimeDomainData(vadData);
  let s = 0;
  for (let i = 0; i < vadData.length; i++) { const v = (vadData[i] - 128) / 128; s += v * v; }
  return Math.sqrt(s / vadData.length);
}

// Press to talk (start recording). Pressing while JARVIS speaks also stops it.
async function startAutoVoice() {
  if (autoVoiceOn) return;
  if (!(await initAutoVoice())) { setVoiceStatus('MIC ERROR'); return; }
  if (state.isSpeaking) speechSynthesis.cancel();      // pressing to talk cuts off JARVIS
  autoVoiceOn = true;
  pttHadSpeech = false; pttSilenceMs = 0; pttLastTs = 0; pttStartTs = performance.now();
  avChunks = [];
  try {
    avRecorder = new MediaRecorder(vadStream);
    avRecorder.ondataavailable = e => { if (e.data.size) avChunks.push(e.data); };
    avRecorder.onstop = pttFinish;
    avRecorder.start();
  } catch (e) { autoVoiceOn = false; setVoiceStatus('MIC ERROR'); return; }
  setMicState('hearing');
  arcReactor?.classList.add('listening');
  voicePill.textContent = '● RECORDING';
  voicePill.className = 'status-pill gmail-on';
  setVoiceStatus('RECORDING — speak, pause to send');
  pttLoop();
}

function pttLoop() {
  if (!autoVoiceOn) return;
  const now = performance.now();
  const dt = pttLastTs ? now - pttLastTs : 16;
  pttLastTs = now;
  const level = avRms();
  if (level > AV_ON) { pttHadSpeech = true; pttSilenceMs = 0; }
  else if (pttHadSpeech) { pttSilenceMs += dt; }
  // auto-stop: had speech then trailing silence, or hit the hard cap
  if ((pttHadSpeech && pttSilenceMs > PTT_END_SILENCE) || (now - pttStartTs) > PTT_MAX_MS) {
    stopAutoVoice();
    return;
  }
  pttRAF = requestAnimationFrame(pttLoop);
}

function stopAutoVoice() {
  if (!autoVoiceOn) return;
  autoVoiceOn = false;
  if (pttRAF) cancelAnimationFrame(pttRAF);
  arcReactor?.classList.remove('listening');
  setMicState('off');
  voicePill.textContent = '🎙 PUSH TO TALK';
  voicePill.className = 'status-pill';
  if (avRecorder && avRecorder.state !== 'inactive') avRecorder.stop();   // → pttFinish
}

async function pttFinish() {
  const blob = new Blob(avChunks, { type: avRecorder.mimeType || 'audio/webm' });
  if (!pttHadSpeech || blob.size < 2400) { setVoiceStatus('STANDBY'); return; }  // nothing said
  setVoiceStatus('TRANSCRIBING…');
  try {
    const fd = new FormData();
    fd.append('audio', blob, 'clip.webm');
    const res = await fetch('/api/transcribe', { method: 'POST', body: fd });
    const data = await res.json();
    const text = (data.text || '').trim();
    if (text.replace(/[^a-z0-9]/gi, '').length >= 2) sendMessage(text);
    else setVoiceStatus('NO SPEECH');
  } catch (e) {
    setVoiceStatus('STT FAIL');
  }
}

// Barge-in DURING TTS only: cancel-only (never records/commands), strict + echo-cancelled.
async function startBargeMonitor() {
  if (!(await initAutoVoice())) return;
  let loud = 0;
  // Warm up so the echo canceller locks onto JARVIS's output first, and use a HIGH
  // threshold so JARVIS's own leaked voice never self-cancels — only your clear speech does.
  const startAt = performance.now() + 500;
  const check = () => {
    if (!state.isSpeaking) { bargeRAF = null; return; }
    if (performance.now() >= startAt) {
      if (avRms() > 0.12) { loud++; } else { loud = 0; }    // clear, close user voice only
      if (loud >= 8) {                                       // ~130ms sustained → stop
        speechSynthesis.cancel();
        state.isSpeaking = false;
        sidebar.classList.remove('speaking');
        arcReactor?.classList.remove('speaking');
        bargeRAF = null;
        return;
      }
    }
    bargeRAF = requestAnimationFrame(check);
  };
  bargeRAF = requestAnimationFrame(check);
}

function speak(text) {
  if (!state.voiceEnabled || !text) {
    logToSidebar(text);
    return;
  }

  speechSynthesis.cancel();
  logToSidebar(text);

  const clean = text
    .replace(/J\.A\.R\.V\.I\.S\./g, 'Jarvis')
    .replace(/[#*_`>]/g, '')
    .replace(/\n{2,}/g, '. ')
    .replace(/\n/g, ', ')
    .replace(/={2,}/g, '')
    .replace(/[★⚠️●◆▶]/g, '')
    .substring(0, 900);

  state.spokenClean = clean.toLowerCase();   // for barge-in echo filtering
  const utt = new SpeechSynthesisUtterance(clean);
  if (state.selectedVoice) utt.voice = state.selectedVoice;
  utt.rate   = 0.92;
  utt.pitch  = 0.9;
  utt.volume = 1.0;

  utt.onstart = () => {
    state.isSpeaking = true;
    sidebar.classList.add('speaking');
    arcReactor?.classList.add('speaking');   // reactor flares while JARVIS talks
    // Say "Jarvis" to interrupt — handled by the recogniser in onresult.
  };

  utt.onend = utt.onerror = () => {
    state.isSpeaking = false;
    sidebar.classList.remove('speaking');
    arcReactor?.classList.remove('speaking');
    if (sbCursor) sbCursor.classList.add('done');
    // Resume continuous listening
    if (state.continuousOn) scheduleRestart(500);
    setVoiceStatus(state.continuousOn ? 'LISTENING' : 'STANDBY');
  };

  speechSynthesis.speak(utt);
}

// ─── Speaking Sidebar logic ───────────────────────────────

function logToSidebar(text) {
  if (!text?.trim()) return;

  // Open sidebar automatically the first time
  if (!state.sidebarOpen) openSidebar();

  const display = text
    .replace(/[#*_`]/g, '')
    .replace(/\n+/g, ' ')
    .trim();

  const now = new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });

  // Show "Now Speaking" block with typewriter
  sbNow.style.display = 'block';
  if (sbCursor) sbCursor.classList.remove('done');
  typeWriter(sbNowText, display, 14);

  // Push to history
  state.speakLog.unshift({ text: display, time: now });
  renderSpeakHistory();
}

function typeWriter(el, text, speed = 14, autoHide = true) {
  clearTimeout(state.typerTimer);
  el.textContent = '';
  let i = 0;

  function tick() {
    if (i < text.length) {
      el.textContent += text[i++];
      state.typerTimer = setTimeout(tick, speed);
    } else if (autoHide) {
      setTimeout(() => {
        if (sbNow) sbNow.style.display = 'none';
        renderSpeakHistory();
      }, 1800);
    }
  }
  tick();
}

function renderSpeakHistory() {
  if (!state.speakLog.length) return;
  sbHistLabel.style.display = 'block';

  sbHistory.innerHTML = state.speakLog.slice(0, 20).map((item, i) => `
    <div class="sb-item">
      <div class="sb-item-time">◈ ${item.time}</div>
      <div class="sb-item-text">${escHtml(item.text.substring(0, 220))}${item.text.length > 220 ? '…' : ''}</div>
    </div>`).join('');
}

function openSidebar() {
  state.sidebarOpen = true;
  sidebar.classList.add('open');
  audioLogBtn.classList.add('active');
}

function closeSidebar() {
  state.sidebarOpen = false;
  sidebar.classList.remove('open');
  audioLogBtn.classList.remove('active');
}

function toggleSidebar() {
  state.sidebarOpen ? closeSidebar() : openSidebar();
}

// ═══════════════════════════════════════════════════════════
//  TTS PIPELINE — sentence-level streaming for minimum delay
// ═══════════════════════════════════════════════════════════

function cleanForTTS(s) {
  return s.replace(/J\.A\.R\.V\.I\.S\./g,'Jarvis').replace(/[#*_`>]/g,'').replace(/\n{2,}/g,'. ')
           .replace(/\n/g,', ').replace(/={2,}/g,'').replace(/[★⚠️●◆▶]/g,'').trim().substring(0,900);
}

function ttsReset() {
  speechSynthesis.cancel();
  tts.buf=''; tts.q=[]; tts.active=false; tts.done=false; tts.full='';
}

function ttsFeed(chunk) {
  tts.full += chunk;
  if (!state.voiceEnabled) return;
  tts.buf += chunk;
  for (;;) {
    let bi = -1;
    for (let i = 2; i < tts.buf.length; i++) {
      const c = tts.buf[i-1], n = tts.buf[i];
      if ('.!?…'.includes(c) && (n === ' ' || n === '\n')) { bi = i; break; }
      if (c === '\n' && n === '\n') { bi = i+1; break; }
    }
    if (bi < 0) break;
    const s = tts.buf.slice(0, bi).trim();
    tts.buf = tts.buf.slice(bi);
    if (s.length > 8) tts.q.push(cleanForTTS(s));
  }
  _ttsDrain();
}

function ttsFinish() {
  tts.done = true;
  const rem = tts.buf.trim();
  if (rem.length > 4 && state.voiceEnabled) { tts.q.push(cleanForTTS(rem)); tts.buf = ''; }
  if (!state.voiceEnabled) {
    logToSidebar(tts.full);
    if (state.continuousOn) scheduleRestart(500);
    return;
  }
  if (!tts.active && !tts.q.length) {
    if (tts.full) logToSidebar(tts.full);
    if (state.continuousOn) scheduleRestart(500);
  } else {
    _ttsDrain();
  }
}

function _ttsDrain() {
  if (tts.active || !tts.q.length) return;
  if (!state.isSpeaking) pauseListeningForSpeech();
  const sentence = tts.q.shift();
  tts.active = true; state.isSpeaking = true;
  sidebar.classList.add('speaking');
  if (!state.sidebarOpen) openSidebar();
  sbNow.style.display = 'block';
  if (sbCursor) sbCursor.classList.remove('done');
  typeWriter(sbNowText, sentence, 14, false); // suppress auto-hide mid-stream
  const utt = new SpeechSynthesisUtterance(sentence);
  if (state.selectedVoice) utt.voice = state.selectedVoice;
  utt.rate = 0.92; utt.pitch = 0.9; utt.volume = 1.0;
  utt.onend = utt.onerror = () => {
    tts.active = false;
    if (tts.q.length) { _ttsDrain(); return; }
    if (tts.done) {
      state.isSpeaking = false;
      sidebar.classList.remove('speaking');
      sbNow.style.display = 'none';
      if (sbCursor) sbCursor.classList.add('done');
      const t = new Date().toLocaleTimeString('en-US',{hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false});
      const disp = tts.full.replace(/[#*_`]/g,'').replace(/\n+/g,' ').trim();
      state.speakLog.unshift({ text: disp, time: t });
      renderSpeakHistory();
      resumeListeningAfterSpeech();
    }
    // else: more chunks incoming via ttsFeed, wait
  };
  speechSynthesis.speak(utt);
}

// ═══════════════════════════════════════════════════════════
//  CHAT
// ═══════════════════════════════════════════════════════════

function looksLikeAnalysis(msg) {
  return /\b(analy|valuation|long.?term|should i (buy|sell)|buy or sell|buy,? sell|accumulate|invest|stock|share price|target price|dcf|report on|view on|worth buying|fair value|intrinsic|price target)\b/i.test(msg);
}

function autoDownload(url) {
  const a = document.createElement('a');
  a.href = url; a.download = '';
  document.body.appendChild(a); a.click(); a.remove();
}

// Chat-triggered analysis → numbers in chat + auto-download Excel/PDF + speak 2 lines
async function runChatAnalysis(text) {
  showThinking(true);
  // Progress ticker — an institutional report on Opus 4.8 takes ~25-35s
  const t0 = Date.now();
  const think = thinkingBar?.querySelector('.thinking-text');
  const tick = setInterval(() => {
    if (think) think.textContent = `Building institutional report (Opus 4.8)… ${Math.round((Date.now()-t0)/1000)}s`;
  }, 500);
  const stopTick = () => { clearInterval(tick); if (think) think.textContent = 'Processing, Master...'; };
  try {
    const res = await fetch('/api/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text }),
    });
    const data = await res.json();
    stopTick();
    if (!data.is_analysis) { showThinking(false); return false; }   // fall back to chat
    showThinking(false);
    if (data.error) {
      addMessage('jarvis', `I could not retrieve data for that, Master. ${data.error}`);
      return true;
    }
    const body = (data.note ? `_${data.note}_\n\n` : '') + (data.analysis || data.numbers);
    addMessage('jarvis', body);                         // ENTIRE analysis shown in chat
    autoDownload(data.excel_url);                       // auto-download both files
    setTimeout(() => autoDownload(data.pdf_url), 900);
    if (state.voiceEnabled) speak(data.speech || data.summary);  // read first 2 + last 2 lines
    if (state.continuousOn) scheduleRestart(800);
    return true;
  } catch (e) {
    stopTick();
    showThinking(false);
    addMessage('jarvis', 'The analysis timed out, Master. Please try again.');
    return true;
  }
}

async function sendMessage(text) {
  text = text.trim();
  if (!text) return;

  addMessage('user', text);
  messageInput.value = '';
  showThinking(true);
  ttsReset();

  // ALWAYS try the data pipeline first — any company mention gets the full
  // numbers / DCF / PDF / Excel. Only genuine non-stock chat falls through.
  const handled = await runChatAnalysis(text);
  if (handled) return;

  const actualModel = autoRouteModel(text);
  const t0 = Date.now();
  let ttftShown = false;

  try {
    const jarvisEl = addMessage('jarvis', '', true);
    const bubble   = jarvisEl.querySelector('.msg-bubble');
    let fullText   = '';

    const res = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: text,
        model:   actualModel,
        history: state.history.slice(-30),
        context: { emails: state.emails }
      })
    });

    showThinking(false);

    const reader = res.body.getReader();
    const dec    = new TextDecoder();

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      const chunk = dec.decode(value, { stream: true });
      for (const line of chunk.split('\n')) {
        if (!line.startsWith('data: ')) continue;
        try {
          const d = JSON.parse(line.slice(6));
          if (d.text) {
            fullText += d.text;
            bubble.innerHTML = formatMarkdown(fullText);
            scrollBottom();
            ttsFeed(d.text);
            if (!ttftShown) {
              ttftShown = true;
              const ms = Date.now() - t0;
              const ml = actualModel.includes('opus') ? 'OPUS' : actualModel.includes('haiku') ? 'HAIKU' : 'SONNET';
              setVoiceStatus(`TTFT ${ms}ms · ${ml}`);
              setTimeout(() => setVoiceStatus(state.isListening ? 'LISTENING' : 'STANDBY'), 4000);
            }
          }
          if (d.error) throw new Error(d.error);
        } catch (_) {}
      }
    }

    state.history.push({ role: 'user', content: text }, { role: 'assistant', content: fullText });
    ttsFinish();

  } catch (err) {
    showThinking(false);
    tts.done = true;
    const errMsg = `I apologise, Master. A system fault occurred: ${err.message}. Please verify the server is running and your API key is configured in jarvis/.env`;
    addMessage('jarvis', errMsg);
    if (state.continuousOn) scheduleRestart(800);
  }
}

function addMessage(role, content, empty = false) {
  const wrap   = document.createElement('div');
  wrap.className = `msg ${role}`;
  const header = document.createElement('div');
  header.className = 'msg-header';
  header.textContent = role === 'jarvis' ? 'J.A.R.V.I.S.' : '— MASTER —';
  wrap.appendChild(header);
  const bubble = document.createElement('div');
  bubble.className = 'msg-bubble';
  if (!empty) bubble.innerHTML = formatMarkdown(content);
  wrap.appendChild(bubble);
  chatMessages.appendChild(wrap);
  scrollBottom();
  return wrap;
}

function formatMarkdown(text) {
  return text
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/```([\s\S]*?)```/g, '<pre><code>$1</code></pre>')
    .replace(/`([^`]+)`/g,'<code>$1</code>')
    .replace(/^### (.+)$/gm,'<h3>$1</h3>')
    .replace(/^## (.+)$/gm,'<h2>$1</h2>')
    .replace(/^# (.+)$/gm,'<h2>$1</h2>')
    .replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>')
    .replace(/\*(.+?)\*/g,'<em>$1</em>')
    .replace(/^[-•] (.+)$/gm,'<li>$1</li>')
    .replace(/((?:<li>.*<\/li>\n?)+)/g,'<ul>$1</ul>')
    .replace(/\n\n/g,'</p><p>')
    .replace(/\n/g,'<br>')
    .replace(/^(.+)$/,'<p>$1</p>');
}

function scrollBottom() { chatMessages.scrollTop = chatMessages.scrollHeight; }
function showThinking(show) { thinkingBar.style.display = show ? 'flex' : 'none'; sendBtn.disabled = show; }

// ═══════════════════════════════════════════════════════════
//  GMAIL
// ═══════════════════════════════════════════════════════════

async function checkGmailStatus() {
  try {
    const r = await fetch('/api/gmail/status');
    const d = await r.json();
    if (d.connected) { state.gmailConnected = true; gmailConnectBtn.textContent = 'REFRESH'; refreshEmailsBtn.disabled = false; getDailyBriefBtn.disabled = false; gmailPill.textContent = '● GMAIL ON'; gmailPill.className = 'status-pill gmail-on'; await fetchEmails(); }
  } catch (_) {}
}

async function connectGmail() {
  if (state.gmailConnected) { await fetchEmails(); return; }
  try {
    const r = await fetch('/api/gmail/auth');
    const { authUrl, error } = await r.json();
    if (error) throw new Error(error);
    window.open(authUrl, '_blank', 'width=500,height=600');
    addMessage('jarvis', 'Opening Google authorisation in a new window, Master. Once you approve access, click Refresh to load your emails.');
  } catch (err) {
    addMessage('jarvis', `⚠️ Gmail connection failed: ${err.message}`);
  }
}

async function fetchEmails() {
  emailList.innerHTML = '<div class="loading">SYNCING COMMS...</div>';
  try {
    const r = await fetch('/api/gmail/emails');
    if (r.status === 401) { const d = await r.json(); if (d.needsAuth) { state.gmailConnected = false; gmailConnectBtn.textContent = 'CONNECT'; } emailList.innerHTML = buildEmptyState('✉','Session Expired','Please reconnect Gmail, Master.'); return; }
    const { emails, total } = await r.json();
    state.emails = emails || [];
    renderEmails(emails, total);
    state.gmailConnected = true;
    refreshEmailsBtn.disabled = false; getDailyBriefBtn.disabled = false;
    gmailConnectBtn.textContent = 'REFRESH';
    gmailPill.textContent = '● GMAIL ON'; gmailPill.className = 'status-pill gmail-on';
    emailStats.style.display = 'flex';
    unreadCount.textContent  = total || emails.length;
    priorityCount.textContent = emails.filter(e => e.isImportant).length;
  } catch (err) { emailList.innerHTML = buildEmptyState('⚠️','Fetch Error',err.message); }
}

function renderEmails(emails, total) {
  if (!emails?.length) { emailList.innerHTML = buildEmptyState('✅','All Clear','Inbox is empty, Master.'); return; }
  emailList.innerHTML = emails.map(e => `
    <div class="email-card ${e.isImportant?'priority':''}" onclick="emailClick('${e.id}')">
      <div class="email-from">${escHtml(trimEmail(e.from))}</div>
      <div class="email-subject">${escHtml(e.subject)}</div>
      <div class="email-snippet">${escHtml(e.snippet||'')}</div>
      <div class="email-meta">
        <span class="email-date">${formatEmailDate(e.date)}</span>
        ${e.isImportant?'<span class="priority-badge">★ PRIORITY</span>':''}
      </div>
    </div>`).join('');
}

function emailClick(id) {
  const e = state.emails.find(x => x.id === id);
  if (!e) return;
  sendMessage(`I've selected an email:\nFrom: ${e.from}\nSubject: ${e.subject}\nPreview: ${e.snippet}\n\nWhat can you tell me about this, and what should I do?`);
}

function trimEmail(from) { const m = from.match(/^([^<]+)</); return m ? m[1].trim() : from.split('@')[0]; }
function escHtml(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
function formatEmailDate(d) { try { const dt=new Date(d),now=new Date(),diff=now-dt; if(diff<3600000)return`${Math.floor(diff/60000)}m ago`; if(diff<86400000)return`${Math.floor(diff/3600000)}h ago`; return dt.toLocaleDateString('en-US',{month:'short',day:'numeric'}); } catch(_){return '';} }
function buildEmptyState(icon,title,sub) { return `<div class="empty-state"><div class="empty-icon">${icon}</div><div class="empty-title">${title}</div><div class="empty-sub">${sub}</div></div>`; }

// ─── Daily Briefing ───────────────────────────────────────
async function getDailyBriefing() {
  getDailyBriefBtn.disabled = true; getDailyBriefBtn.textContent = 'BRIEFING...';
  showThinking(true);
  try {
    const r = await fetch('/api/briefing', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ emails: state.emails, model: state.model }) });
    const { briefing } = await r.json();
    showThinking(false);
    addMessage('jarvis', briefing);
    if (state.voiceEnabled) speak(briefing);
  } catch (err) {
    showThinking(false);
    addMessage('jarvis', `Unable to prepare briefing, Master: ${err.message}`);
  } finally {
    getDailyBriefBtn.disabled = false; getDailyBriefBtn.textContent = '★ BRIEF ME';
  }
}

// ═══════════════════════════════════════════════════════════
//  FINANCIAL ANALYSIS
// ═══════════════════════════════════════════════════════════

async function runAnalysis() {
  const data  = $('financialInput').value.trim();
  const type  = $('analysisType').value;
  const model = $('finAnalysisModel').value;
  if (!data) { addMessage('jarvis','Master, please provide financial data to analyse.'); return; }
  analyzeBtn.disabled = true; analyzeBtn.textContent = '⚡ ANALYSING...';
  switchFinTab('results');
  $('analysisResults').innerHTML = '<div class="loading">RUNNING PRIMARY AGENT + VALIDATION...</div>';
  $('validationBlock').style.display = 'none';
  try {
    const r = await fetch('/api/financial/analyze', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({data,type,model}) });
    const { analysis, validation } = await r.json();
    $('analysisResults').innerHTML = formatMarkdown(analysis);
    addMessage('jarvis', `Financial analysis complete, Master. Full ${type} results in the Financial Core panel.\n\n${analysis.substring(0,400)}…`);
    if (state.voiceEnabled) speak(`Analysis complete, Master. ${analysis.split('\n').slice(0,3).join(' ')}`);
    if (validation) renderValidation(validation);
    $('finModelBadge').textContent = model.includes('opus') ? 'OPUS' : 'SONNET';
  } catch (err) {
    $('analysisResults').innerHTML = `<div style="color:#ff4422;padding:10px">Analysis failed: ${err.message}</div>`;
  } finally { analyzeBtn.disabled=false; analyzeBtn.textContent='⚡ ANALYZE'; }
}

async function runFinancialModel() {
  const inputs = $('modelInput').value.trim();
  const type   = $('modelType').value;
  const model  = $('finBuildModel').value;
  if (!inputs) { addMessage('jarvis','Master, please provide model parameters first.'); return; }
  buildModelBtn.disabled=true; buildModelBtn.textContent='⚡ BUILDING...';
  switchFinTab('results');
  $('analysisResults').innerHTML='<div class="loading">BUILDING MODEL...</div>';
  $('validationBlock').style.display='none';
  try {
    const r = await fetch('/api/financial/model', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({type,inputs,model}) });
    const { result } = await r.json();
    $('analysisResults').innerHTML = formatMarkdown(result);
    addMessage('jarvis', `${type.toUpperCase()} model complete, Master. Review the full output in the Financial Core panel.`);
    if (state.voiceEnabled) speak(`${type.toUpperCase()} model is ready, Master.`);
  } catch (err) {
    $('analysisResults').innerHTML=`<div style="color:#ff4422;padding:10px">Model failed: ${err.message}</div>`;
  } finally { buildModelBtn.disabled=false; buildModelBtn.textContent='⚡ BUILD MODEL'; }
}

function renderValidation(v) {
  const block=$('validationBlock'), score=$('valScore'), grid=$('valGrid'), verdict=$('valVerdict');
  block.style.display='block';
  const s=v.overallScore||0;
  score.textContent=`${s}% ${v.grade||''}`;
  score.className='val-score '+(s>=75?'':s>=50?'warn':'fail');
  const checks=[
    {label:'DATA FRESHNESS',...v.dataFreshness},
    {label:'COMPLETENESS',...v.dataCompleteness},
    {label:'CALCULATIONS',...v.calculationAccuracy},
    {label:'CONFIDENCE',status:v.confidence==='HIGH'?'PASS':v.confidence==='MEDIUM'?'WARN':'FAIL',message:v.confidence||'—'},
  ];
  grid.innerHTML=checks.map(c=>`<div class="val-item ${(c.status||'warn').toLowerCase()}" title="${escHtml(c.message||'')}"><div>${c.label}</div><div>${c.status||'?'}</div></div>`).join('');
  const rec=(v.recommendation||'').toLowerCase();
  verdict.textContent=`VERDICT: ${v.recommendation||'UNKNOWN'}`;
  verdict.className='val-verdict '+(rec.includes('proceed')?'proceed':rec.includes('caution')?'caution':'review');
}

// ─── Tabs / Model ─────────────────────────────────────────
function switchFinTab(name) {
  document.querySelectorAll('.fin-tab').forEach(t=>t.classList.toggle('active',t.dataset.tab===name));
  document.querySelectorAll('.fin-content').forEach(c=>c.classList.toggle('active',c.id===`tab-${name}`));
}

function switchModel(val) {
  state.model = val;
  const labels = {
    'auto': 'AUTO-ROUTING ACTIVE',
    'claude-opus-4-7': 'OPUS 4.7 ACTIVE',
    'claude-sonnet-4-6': 'SONNET 4.6 ACTIVE',
    'claude-haiku-4-5-20251001': 'HAIKU 4.5 ACTIVE'
  };
  modelIndicator.textContent = labels[val] || val.toUpperCase();
  const names = {
    'auto': 'Auto-routing',
    'claude-opus-4-7': 'Opus 4.7',
    'claude-sonnet-4-6': 'Sonnet 4.6',
    'claude-haiku-4-5-20251001': 'Haiku 4.5'
  };
  const msg = val === 'auto'
    ? 'Auto-routing engaged, Master. I will select the optimal model automatically — Haiku for quick queries, Opus for financial analysis, Sonnet for everything else.'
    : `Switching to ${names[val]||val}, Master. ${val.includes('opus')?'Maximum analytical power engaged.':val.includes('haiku')?'Rapid-response mode active.':'Balanced performance mode active.'}`;
  addMessage('jarvis', msg);
}

function autoRouteModel(text) {
  if (state.model !== 'auto') return state.model;
  const q = text.toLowerCase().trim();
  // Financial/analytical → Opus first (even for short queries)
  if (/\b(dcf|lbo|model|valuat|analys|portfolio|ebitda|wacc|irr|moic|cash flow|financial|investment|equity|debt|revenue|earnings|balance sheet|income statement)\b/.test(q))
    return 'claude-opus-4-7';
  // Short/simple greetings → Haiku
  if (q.length < 55 || /^(hi|hey|hello|thanks|ok|good|what time|date)\b/.test(q))
    return 'claude-haiku-4-5-20251001';
  return 'claude-sonnet-4-6';
}

// ─── URL flags ────────────────────────────────────────────
function checkUrlFlags() {
  const p = new URLSearchParams(window.location.search);
  if (p.get('connected')==='gmail') { state.gmailConnected=true; history.replaceState({},'','/'); addMessage('jarvis','Gmail authorisation successful, Master. Syncing your communications now.'); fetchEmails(); }
  if (p.get('error')==='gmail')     { history.replaceState({},'','/'); addMessage('jarvis','⚠️ Gmail authorisation failed. Please verify your Google OAuth credentials in .env and ensure the redirect URI http://localhost:3000/api/gmail/callback is registered.'); }
}

// ═══════════════════════════════════════════════════════════
//  BACKGROUND CANVAS
// ═══════════════════════════════════════════════════════════

function initBgCanvas() {
  const ctx = bgCanvas.getContext('2d');
  let W, H, particles = [];

  function resize() {
    W = bgCanvas.width  = window.innerWidth;
    H = bgCanvas.height = window.innerHeight;
    particles = Array.from({length:60}, () => ({
      x: Math.random()*W, y: Math.random()*H,
      r: Math.random()*1.5+0.5,
      vx: (Math.random()-0.5)*0.35, vy: (Math.random()-0.5)*0.35,
      op: Math.random()*0.4+0.1,
    }));
  }

  function drawHex(x,y,size) {
    ctx.beginPath();
    for (let i=0;i<6;i++) { const a=(Math.PI/3)*i-Math.PI/6; i===0?ctx.moveTo(x+size*Math.cos(a),y+size*Math.sin(a)):ctx.lineTo(x+size*Math.cos(a),y+size*Math.sin(a)); }
    ctx.closePath();
  }

  function draw() {
    ctx.clearRect(0,0,W,H);
    ctx.strokeStyle='rgba(0,212,255,0.03)'; ctx.lineWidth=0.5;
    const hs=42, hh=hs*Math.sqrt(3)/2;
    for (let row=-1;row<H/hh+2;row++) for (let col=-1;col<W/(hs*1.5)+2;col++) { drawHex(col*hs*1.5,row*hh*2+(col%2===0?0:hh),hs*0.95); ctx.stroke(); }
    particles.forEach(p => {
      p.x=(p.x+p.vx+W)%W; p.y=(p.y+p.vy+H)%H;
      ctx.beginPath(); ctx.arc(p.x,p.y,p.r,0,Math.PI*2);
      ctx.fillStyle=`rgba(0,212,255,${p.op})`; ctx.fill();
    });
    for (let i=0;i<particles.length;i++) for (let j=i+1;j<particles.length;j++) {
      const dx=particles[i].x-particles[j].x, dy=particles[i].y-particles[j].y, d=Math.hypot(dx,dy);
      if (d<130) { ctx.beginPath(); ctx.moveTo(particles[i].x,particles[i].y); ctx.lineTo(particles[j].x,particles[j].y); ctx.strokeStyle=`rgba(0,212,255,${0.12*(1-d/130)})`; ctx.lineWidth=0.5; ctx.stroke(); }
    }
    requestAnimationFrame(draw);
  }

  window.addEventListener('resize', resize);
  resize(); draw();
}

// ─── Viz Canvas (voice waveform) ──────────────────────────
function initVizCanvas() {
  const ctx = vizCanvas.getContext('2d');
  const W = vizCanvas.width, H = vizCanvas.height;
  let t = 0;

  function draw() {
    ctx.clearRect(0,0,W,H);
    const listening = state.isListening && !state.isSpeaking;
    const hearing   = state.isHearing;
    const speaking  = state.isSpeaking;

    const color     = hearing ? '#00ff88' : speaking ? '#ffc107' : '#00d4ff';
    const amplitude = hearing ? 0.7 : speaking ? 0.5 : 0.25;
    const speed     = hearing ? 0.15 : speaking ? 0.1 : 0.04;

    t += speed;

    ctx.beginPath();
    const bars = 32;
    for (let i=0;i<=bars;i++) {
      const x=(i/bars)*W;
      const amp=(Math.sin(t*4+i*0.6)*0.5+0.5)*H*amplitude+3;
      i===0?ctx.moveTo(x,H/2):ctx.lineTo(x,H/2-amp/2+amp*Math.sin(t*2+i)*0.3);
    }
    ctx.strokeStyle = color;
    ctx.lineWidth   = 1.8;
    ctx.shadowBlur  = 6;
    ctx.shadowColor = color;
    ctx.stroke();
    ctx.shadowBlur  = 0;

    requestAnimationFrame(draw);
  }
  draw();
}

// ═══════════════════════════════════════════════════════════
//  EVENT LISTENERS
// ═══════════════════════════════════════════════════════════

// ═══ Equity Report — real market data → Excel + PDF (no LLM) ═══
async function generateReport() {
  const sym = (reportSymbol.value || '').trim();
  if (!sym) { reportSymbol.focus(); return; }
  reportResult.style.display = 'none';
  reportStatus.style.display = 'block';
  reportStatus.textContent = `Fetching live data & building report for ${sym.toUpperCase()}…`;
  genReportBtn.disabled = true;
  try {
    const res = await fetch('/api/stock/report', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol: sym }),
    });
    const data = await res.json();
    if (!res.ok || data.error) {
      reportStatus.textContent = '⚠ ' + (data.error || 'Report failed');
      return;
    }
    reportStatus.style.display = 'none';
    reportVerdict.textContent = `${data.verdict} — ${data.name}`;
    reportVerdict.className = 'report-verdict v-' + (data.verdict || '').toLowerCase();
    dlExcel.href = data.excel_url;
    dlPdf.href = data.pdf_url;
    reportResult.style.display = 'block';
    let extra = `\n\nAuthored by: ${data.authored_by || 'engine'}`;
    if (data.data_asof) extra += `\nData as-of: ${data.data_asof} (${data.data_status || ''})`;
    if (data.fair_value) extra += `\nDCF fair value: ₹${Number(data.fair_value).toLocaleString('en-IN',{maximumFractionDigits:0})}`;
    if (data.price_target) extra += `\n12m target: ₹${Number(data.price_target).toLocaleString('en-IN',{maximumFractionDigits:0})}`;
    if (data.validated === true)  extra += `\n✅ Model calcs validated (formulas verified)`;
    if (data.validated === false) extra += `\n⚠ Validation flagged issues (see checks)`;
    reportSummary.textContent = data.summary + extra;
    // Chat shows summary + download note; JARVIS SPEAKS only the 2-line summary
    addMessage('jarvis', data.summary + `\n\n📊 Excel model & institutional PDF ready — download from the REPORT panel, Master.`);
    if (state.voiceEnabled) speak(data.summary);
  } catch (e) {
    reportStatus.textContent = '⚠ Network error — is the server running?';
  } finally {
    genReportBtn.disabled = false;
  }
}

function setupEventListeners() {
  // Send
  sendBtn.addEventListener('click', () => sendMessage(messageInput.value));
  messageInput.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(messageInput.value); }
  });

  // Both mic buttons toggle always-on continuous listening
  micBtn.addEventListener('click', () => {
    state.continuousOn ? stopContinuousListening() : startContinuousListening();
  });
  whisperBtn.addEventListener('click', () => {
    state.continuousOn ? stopContinuousListening() : startContinuousListening();
  });

  // Voice output toggle
  voiceToggleBtn.addEventListener('click', () => {
    state.voiceEnabled = !state.voiceEnabled;
    voiceToggleBtn.textContent = state.voiceEnabled ? '🔊' : '🔇';
    voiceToggleBtn.classList.toggle('active', !state.voiceEnabled);
    if (!state.voiceEnabled) { speechSynthesis.cancel(); state.isSpeaking=false; sidebar.classList.remove('speaking'); resumeListeningAfterSpeech(); }
  });

  // Audio log sidebar toggle
  audioLogBtn.addEventListener('click', toggleSidebar);
  sidebarClose.addEventListener('click', closeSidebar);

  // Clear chat
  clearBtn.addEventListener('click', () => {
    chatMessages.innerHTML=''; state.history=[];
    addMessage('jarvis','Memory cleared, Master. Ready for new directives.');
  });

  // Briefing
  briefingBtn.addEventListener('click', getDailyBriefing);
  getDailyBriefBtn.addEventListener('click', getDailyBriefing);

  // Gmail
  gmailConnectBtn.addEventListener('click', connectGmail);
  refreshEmailsBtn.addEventListener('click', fetchEmails);

  // Financial
  analyzeBtn.addEventListener('click', runAnalysis);
  buildModelBtn.addEventListener('click', runFinancialModel);

  // Equity Report (real data, no LLM)
  genReportBtn.addEventListener('click', generateReport);
  reportSymbol.addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); generateReport(); }
  });

  // Model (God Mode)
  modelSelector.addEventListener('change', e => switchModel(e.target.value));

  // Fin tabs
  document.querySelectorAll('.fin-tab').forEach(t => t.addEventListener('click', () => switchFinTab(t.dataset.tab)));

  // Close sidebar on outside click
  document.addEventListener('click', e => {
    if (state.sidebarOpen && !sidebar.contains(e.target) && e.target !== audioLogBtn)
      closeSidebar();
  });
}
