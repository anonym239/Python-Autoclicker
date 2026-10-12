/* Simuliert das Python-Programm im Browser – nur fuer die Vorschau-Datei.
   Gleiche API wie der echte Server (state / post / qrUrl / bye). */
window.AC_MOCK = (() => {
  "use strict";
  const CONFIG = __CONFIG__;
  const PRESETS = __PRESETS__;
  const QR = "__QR__";
  const REMOTE_URL = "http://192.168.178.24:8765/?t=Vorschau-Code";

  const cfg = JSON.parse(JSON.stringify(CONFIG));
  let rev = 1, recording = false, recordUntil = 0, notice = null, noticeId = 0, remoteClient = false;
  const now = () => performance.now() / 1000;
  const eng = {
    armed: false, countdownEnd: null, runStart: null, runClicks: 0, session: 0, lifetime: 0, best: 0,
    stopReason: "", mouse: new Set(), boostDue: [], nextT: null, state: "idle", reason: "", samples: [], cps: 0,
  };
  const mode = () => PRESETS[cfg.preset].mode;
  const cur = () => cfg.presets[cfg.preset];
  const notify = (text) => { noticeId++; notice = { id: noticeId, text, at: Date.now() }; };
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
  const count = () => { eng.session++; eng.runClicks++; };

  function start(source) {
    if (eng.armed || eng.countdownEnd !== null) return;
    let delay = cfg.general.start_delay;
    if (source !== "hotkey") delay = Math.max(delay, 3);
    eng.stopReason = "";
    if (delay > 0) eng.countdownEnd = now() + delay; else arm();
  }
  function arm() { eng.armed = true; eng.countdownEnd = null; eng.runStart = now(); eng.runClicks = 0; eng.nextT = null; }
  function stop(reason) {
    const on = eng.armed || eng.countdownEnd !== null;
    eng.armed = false; eng.countdownEnd = null; eng.runStart = null; eng.boostDue = [];
    if (on) { eng.stopReason = reason; if (reason === "limit") notify("Auto-Stopp erreicht"); }
  }
  const toggle = (source) => (eng.armed || eng.countdownEnd !== null ? stop("manual") : start(source));

  function evaluate() {
    const m = mode();
    if (eng.countdownEnd !== null) return ["countdown", ""];
    if (!eng.armed) return ["idle", ""];
    if (m === "hold_mouse" && !eng.mouse.has(cur().button)) return ["ready", "mouse"];
    if (m === "boost" && !eng.boostDue.length) return ["ready", "boost"];
    return ["clicking", ""];
  }
  function rate() {
    const c = cur().cps;
    return cfg.general.vary ? c * (0.88 + Math.random() * 0.24) : c;
  }
  function step() {
    const t = now();
    if (eng.countdownEnd !== null && t >= eng.countdownEnd) arm();
    if (eng.armed && cfg.general.auto_stop > 0 && t - eng.runStart >= cfg.general.auto_stop) stop("limit");
    [eng.state, eng.reason] = evaluate();
    if (eng.state !== "clicking") { eng.nextT = null; return; }
    if (mode() === "boost") {
      while (eng.boostDue.length && eng.boostDue[0] <= t) { eng.boostDue.shift(); if (!eng.mouse.has(cur().button)) count(); }
      return;
    }
    if (eng.nextT === null) eng.nextT = t + (mode() === "hold_mouse" ? 1 / rate() : 0);
    let guard = 0;
    while (eng.nextT <= t && guard++ < 400) { count(); eng.nextT += 1 / rate(); }
    if (eng.nextT < t - 0.05) eng.nextT = t;
  }
  setInterval(step, 10);
  setInterval(() => {
    const t = now();
    eng.samples.push([t, eng.session]);
    if (eng.samples.length > 5) eng.samples.shift();
    const [t0, c0] = eng.samples[0], [t1, c1] = eng.samples[eng.samples.length - 1];
    eng.cps = t1 > t0 && c1 >= c0 ? (c1 - c0) / (t1 - t0) : 0;
    eng.best = Math.max(eng.best, eng.cps);
    if (recording && t > recordUntil) recording = false;
  }, 250);

  function state(since) {
    const t = now();
    const out = {
      rev,
      engine: {
        state: eng.state, reason: eng.reason, stop_reason: eng.stopReason, armed: eng.armed,
        countdown: eng.countdownEnd !== null ? Math.max(0, eng.countdownEnd - t) : null,
        run_time: eng.runStart !== null ? t - eng.runStart : 0, run_clicks: eng.runClicks,
        session_clicks: eng.session, lifetime_clicks: eng.lifetime + eng.session,
        cps: Math.round(eng.cps * 10) / 10, best_cps: Math.round(eng.best * 10) / 10,
        history: [], limit_progress: null, holding: false,
      },
      recording,
      notice: notice && Date.now() - notice.at < 6000 ? notice : null,
    };
    if (String(since) !== String(rev)) {
      const general = { ...cfg.general };
      delete general.token; delete general.port;
      out.config = {
        preset: cfg.preset,
        presets: Object.keys(PRESETS).map((id) => ({ id, name: PRESETS[id].name, mode: PRESETS[id].mode })),
        mode: mode(), current: { ...cur() }, hotkey: cfg.hotkey, general, best_cps_ever: 0,
      };
      out.info = {
        name: "AutoClicker", version: "__VERSION__", backend: "demo", hooks_ok: false,
        remote_client: remoteClient, remote_url: cfg.general.remote ? REMOTE_URL : null, remote_error: null,
      };
    }
    return out;
  }

  async function post(name, b) {
    await new Promise((r) => setTimeout(r, 25));
    if (name === "action") {
      if (b.do === "toggle") toggle(remoteClient ? "remote" : "ui");
      else if (b.do === "stop") stop("manual");
      else if (b.do === "reset_stats") { eng.lifetime += eng.session; eng.session = 0; eng.runClicks = 0; eng.best = 0; }
    } else if (name === "settings") {
      if (b.preset) {
        const p = cur();
        if (b.preset.button) p.button = b.preset.button;
        if ("cps" in b.preset) p.cps = clamp(+b.preset.cps || 0.1, 0.1, 1000);
        if ("boost" in b.preset) p.boost = clamp(Math.round(+b.preset.boost), 2, 3);
      }
      if (b.general) Object.assign(cfg.general, b.general);
      rev++;
    } else if (name === "preset") {
      if (PRESETS[b.id]) { cfg.preset = b.id; eng.boostDue = []; rev++; }
    } else if (name === "record") {
      if (b.cancel) recording = false;
      else if (b.key !== undefined) { cfg.hotkey = String(b.key); recording = false; notify("Hotkey gespeichert: " + cfg.hotkey.toUpperCase()); }
      else { recording = true; recordUntil = now() + 15; }
      rev++;
    } else if (name === "remote") {
      if ("enabled" in b) cfg.general.remote = !!b.enabled;
      rev++;
    }
    return state(-1);
  }

  // Hotkey und echte Mausklicks in der Vorschau nachstellen
  const typing = (el) => el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA");
  const keyName = (e) => (/^F\d{1,2}$/.test(e.code) ? e.code.toLowerCase() : /^Key[A-Z]$/.test(e.code) ? e.code.slice(3).toLowerCase() : null);
  window.addEventListener("keydown", (e) => {
    if (recording || typing(document.activeElement) || e.repeat) return;
    if (keyName(e) && keyName(e) === cfg.hotkey) { e.preventDefault(); toggle("hotkey"); }
  });
  const interactive = (el) => el && el.closest && el.closest("button, input, label, a, .side, .overlay, .pv-bar, .card.rows");
  const BTN = { 0: "left", 2: "right" };
  window.addEventListener("pointerdown", (e) => {
    const b = BTN[e.button];
    if (!b || interactive(e.target)) return;
    if (eng.armed && b === cur().button && (mode() === "hold_mouse" || mode() === "boost")) { count(); eng.boostDue = []; }
    eng.mouse.add(b);
  });
  window.addEventListener("pointerup", (e) => {
    const b = BTN[e.button] || "left";
    const was = eng.mouse.delete(b);
    if (was && eng.armed && mode() === "boost" && b === cur().button) {
      let t = now();
      for (let i = 0; i < cur().boost - 1; i++) { t += i === 0 ? 0.012 + Math.random() * 0.012 : 0.028 + Math.random() * 0.017; eng.boostDue.push(t); }
    }
  });
  window.addEventListener("pointercancel", () => eng.mouse.clear());
  window.addEventListener("contextmenu", (e) => { if (!interactive(e.target)) e.preventDefault(); });

  return {
    state: async (since) => state(since),
    post,
    qrUrl: () => QR,
    bye() {},
    setRemoteClient(on) { remoteClient = on; rev++; },
  };
})();
