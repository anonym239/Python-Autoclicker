/* Simuliert das Python-Programm im Browser – nur fuer die Vorschau-Datei.
   Gleiche API wie der echte Server (state / post / qrUrl / bye). */
window.AC_MOCK = (() => {
  "use strict";
  const CONFIG = __CONFIG__;
  const QR = "__QR__";
  const REMOTE_URL = "http://192.168.178.24:8765/?t=Vorschau-Code";

  const cfg = JSON.parse(JSON.stringify(CONFIG));
  let rev = 1;
  let recording = null, recordUntil = 0;
  let notice = null, noticeId = 0;
  let remoteClient = false;
  const now = () => performance.now() / 1000;

  // Beispiel-Werte, damit Graph und Level nicht leer sind
  const eng = {
    armed: false, countdownEnd: null, lastTick: 0, runStart: null, runClicks: 0,
    session: 0, lifetimeBase: 18234, best: 0, stopReason: "",
    keyHeld: false, mouse: new Set(), holding: false, nextT: null,
    state: "idle", reason: "", samples: [], cps: 0,
    history: Array.from({ length: 120 }, (_, i) => (i > 18 && i < 74 ? 11 + Math.sin(i * 1.7) * 1.6 + Math.cos(i * 0.6) : 0)),
  };

  const active = () => cfg.profiles.find((p) => p.name === cfg.active) || cfg.profiles[0];
  const notify = (text) => { noticeId++; notice = { id: noticeId, text, at: Date.now() }; };
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

  function arm() { eng.armed = true; eng.countdownEnd = null; eng.runStart = now(); eng.runClicks = 0; eng.nextT = null; }
  function start(source) {
    const p = active();
    if (eng.armed || eng.countdownEnd !== null || p.mode === "hold_key") return;
    let delay = p.start_delay;
    if (source !== "hotkey") delay = Math.max(delay, 3);
    eng.stopReason = "";
    if (delay > 0) eng.countdownEnd = now() + delay; else arm();
  }
  function stop(reason) {
    const on = eng.armed || eng.countdownEnd !== null;
    eng.armed = false; eng.countdownEnd = null; eng.runStart = null;
    if (on) { eng.stopReason = reason || "manual"; if (reason === "limit") notify("Auto-Stopp erreicht"); }
  }
  function toggle(source) { if (eng.armed || eng.countdownEnd !== null) stop("manual"); else start(source); }

  function evaluate() {
    const p = active();
    if (eng.countdownEnd !== null) return ["countdown", ""];
    if (p.mode === "hold_key") { if (!eng.keyHeld) return ["ready", "key"]; }
    else if (!eng.armed) return ["idle", ""];
    else if (p.mode === "hold_mouse" && !eng.mouse.has(p.button)) return ["ready", "mouse"];
    return ["clicking", ""];
  }

  function step() {
    const t = now(), p = active();
    if (eng.countdownEnd !== null && t >= eng.countdownEnd) arm();
    if (eng.armed && ((p.limit_clicks > 0 && eng.runClicks >= p.limit_clicks) ||
        (p.limit_seconds > 0 && t - eng.runStart >= p.limit_seconds))) stop("limit");
    [eng.state, eng.reason] = evaluate();
    eng.holding = eng.state === "clicking" && p.action === "hold" && p.mode === "toggle";
    if (eng.state !== "clicking" || eng.holding) { eng.nextT = null; return; }
    if (eng.nextT === null) eng.nextT = t + (p.mode === "hold_mouse" ? 1 / p.cps_max : 0);
    let guard = 0;
    while (eng.nextT <= t && guard++ < 400) {
      eng.session++; eng.runClicks++;
      const lo = Math.min(p.cps_min, p.cps_max), hi = Math.max(p.cps_min, p.cps_max);
      eng.nextT += 1 / (lo + Math.random() * (hi - lo));
      if (p.limit_clicks > 0 && eng.runClicks >= p.limit_clicks) break;
    }
    if (eng.nextT < t - 0.05) eng.nextT = t;
  }
  setInterval(step, 16);
  setInterval(() => {
    const t = now();
    eng.samples.push([t, eng.session]);
    if (eng.samples.length > 5) eng.samples.shift();
    const [t0, c0] = eng.samples[0], [t1, c1] = eng.samples[eng.samples.length - 1];
    eng.cps = t1 > t0 && c1 >= c0 ? (c1 - c0) / (t1 - t0) : 0;
    eng.history.push(eng.cps); eng.history.shift();
    eng.best = Math.max(eng.best, eng.cps);
    if (recording && t > recordUntil) recording = null;
  }, 250);

  function state(since) {
    const t = now(), p = active();
    let progress = null;
    const runTime = eng.runStart !== null ? t - eng.runStart : 0;
    if (eng.armed && p.limit_clicks > 0) progress = Math.min(1, eng.runClicks / p.limit_clicks);
    if (eng.armed && p.limit_seconds > 0) progress = Math.max(progress || 0, Math.min(1, runTime / p.limit_seconds));
    const out = {
      rev,
      engine: {
        state: eng.state, reason: eng.reason, stop_reason: eng.stopReason, armed: eng.armed,
        countdown: eng.countdownEnd !== null ? Math.max(0, eng.countdownEnd - t) : null,
        run_time: runTime, run_clicks: eng.runClicks, session_clicks: eng.session,
        lifetime_clicks: eng.lifetimeBase + eng.session, cps: Math.round(eng.cps * 10) / 10,
        best_cps: Math.round(eng.best * 10) / 10, history: eng.history.map((v) => Math.round(v * 10) / 10),
        limit_progress: progress, holding: eng.holding,
      },
      recording,
      notice: notice && Date.now() - notice.at < 6000 ? notice : null,
    };
    if (String(since) !== String(rev)) {
      out.config = {
        active: cfg.active, profiles: cfg.profiles.map((x) => x.name), profile: { ...p },
        hotkeys: { ...cfg.hotkeys }, smart: { ...cfg.smart },
        app: { sound: cfg.app.sound, always_on_top: cfg.app.always_on_top, theme: cfg.app.theme, remote: cfg.app.remote },
        best_cps_ever: 0,
      };
      out.info = {
        name: "AutoClicker v6", version: "6.0.0", backend: "demo", hooks_ok: false,
        remote_client: remoteClient, remote_url: cfg.app.remote ? REMOTE_URL : null, remote_error: null, port: 8765,
      };
    }
    return out;
  }

  function sanitizeProfile(p, patch) {
    const q = { ...p };
    for (const k of ["button", "mode", "action"]) if (patch[k]) q[k] = patch[k];
    if ("cps_min" in patch) q.cps_min = clamp(+patch.cps_min || 0.1, 0.1, 1000);
    if ("cps_max" in patch) q.cps_max = clamp(+patch.cps_max || 0.1, 0.1, 1000);
    if (q.cps_min > q.cps_max) { if ("cps_max" in patch && !("cps_min" in patch)) q.cps_min = q.cps_max; else q.cps_max = q.cps_min; }
    if ("hold_ms" in patch) q.hold_ms = clamp(+patch.hold_ms || 0, 0, 500);
    if ("limit_seconds" in patch) q.limit_seconds = clamp(+patch.limit_seconds || 0, 0, 86400);
    if ("limit_clicks" in patch) q.limit_clicks = Math.round(clamp(+patch.limit_clicks || 0, 0, 1e9));
    if ("start_delay" in patch) q.start_delay = clamp(+patch.start_delay || 0, 0, 60);
    if (q.mode !== "toggle" && q.action === "hold") q.action = "click";
    return q;
  }
  function uniqueName(name, taken) {
    taken = taken.map((x) => x.toLowerCase());
    if (!taken.includes(name.toLowerCase())) return name;
    let i = 2;
    while (taken.includes(`${name.slice(0, 20)} ${i}`.toLowerCase())) i++;
    return `${name.slice(0, 20)} ${i}`;
  }

  function profileOp(b) {
    const names = cfg.profiles.map((p) => p.name);
    const idx = names.indexOf(cfg.active);
    if (b.op === "select" && names.includes(b.name)) cfg.active = b.name;
    else if (b.op === "next") { cfg.active = names[(idx + 1) % names.length]; notify("Profil: " + cfg.active); }
    else if (b.op === "create" || b.op === "duplicate") {
      if (cfg.profiles.length >= 12) return { error: "Maximal 12 Profile" };
      const base = b.op === "duplicate" ? { ...active() } : { ...CONFIG.profiles[0] };
      base.name = uniqueName((b.new_name || base.name).slice(0, 24), names);
      cfg.profiles.push(base); cfg.active = base.name;
    } else if (b.op === "rename") {
      const clean = String(b.new_name || "").trim().slice(0, 24);
      if (!clean) return { error: "Name fehlt" };
      const nn = uniqueName(clean, names.filter((n) => n !== cfg.active));
      active().name = nn; cfg.active = nn;
    } else if (b.op === "delete") {
      if (cfg.profiles.length <= 1) return { error: "Das letzte Profil bleibt" };
      cfg.profiles.splice(idx, 1);
      cfg.active = cfg.profiles[Math.max(0, idx - 1)].name;
    }
    rev++;
    return null;
  }

  async function post(name, b) {
    await new Promise((r) => setTimeout(r, 30));
    if (name === "action") {
      if (b.do === "toggle") toggle(remoteClient ? "remote" : "ui");
      else if (b.do === "start") start("ui");
      else if (b.do === "stop") stop("manual");
      else if (b.do === "reset_stats") { eng.lifetimeBase += eng.session; eng.session = 0; eng.runClicks = 0; eng.best = 0; eng.history = eng.history.map(() => 0); }
    } else if (name === "settings") {
      if (b.profile) {
        const i = cfg.profiles.findIndex((p) => p.name === cfg.active);
        cfg.profiles[i] = sanitizeProfile(cfg.profiles[i], b.profile);
      }
      if (b.smart) Object.assign(cfg.smart, b.smart);
      if (b.app) Object.assign(cfg.app, b.app);
      rev++;
    } else if (name === "profile") {
      const err = profileOp(b);
      if (err) { const e = new Error(err.error); e.code = 400; throw e; }
    } else if (name === "record") {
      if (b.cancel) recording = null;
      else if (b.key !== undefined) {
        const key = String(b.key);
        if (key) {
          for (const s of Object.keys(cfg.hotkeys)) if (s !== b.slot && cfg.hotkeys[s] === key) cfg.hotkeys[s] = "";
          notify("Hotkey gespeichert: " + key.toUpperCase());
        }
        cfg.hotkeys[b.slot] = key;
        recording = null;
      } else { recording = b.slot; recordUntil = now() + 15; }
      rev++;
    } else if (name === "remote") {
      if (b.new_token) notify("Neuer Handy-Code – das Handy muss den QR-Code neu scannen");
      if ("enabled" in b) cfg.app.remote = !!b.enabled;
      rev++;
    }
    return state(-1);
  }

  // "Globale" Hotkeys + gehaltene Maustaste in der Vorschau nachstellen
  const typing = (el) => el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA");
  const hk = () => cfg.hotkeys.toggle;
  const keyName = (e) => (/^F\d{1,2}$/.test(e.code) ? e.code.toLowerCase() : /^Key[A-Z]$/.test(e.code) ? e.code.slice(3).toLowerCase() : null);
  window.addEventListener("keydown", (e) => {
    if (recording || typing(document.activeElement) || e.repeat) return;
    if (keyName(e) && keyName(e) === hk()) {
      e.preventDefault();
      if (active().mode === "hold_key") eng.keyHeld = true; else toggle("hotkey");
    } else if (keyName(e) && keyName(e) === cfg.hotkeys.stop) stop("manual");
    else if (keyName(e) && keyName(e) === cfg.hotkeys.next_profile) profileOp({ op: "next" });
  });
  window.addEventListener("keyup", (e) => { if (keyName(e) === hk()) eng.keyHeld = false; });
  const interactive = (el) => el && el.closest && el.closest("button, input, label, a, summary, select, .tabs, .profiles, .pv-bar");
  const BTN = { 0: "left", 1: "middle", 2: "right" };
  window.addEventListener("pointerdown", (e) => { if (!interactive(e.target) && BTN[e.button]) eng.mouse.add(BTN[e.button]); });
  const up = (e) => { eng.mouse.delete(BTN[e.button] || "left"); };
  window.addEventListener("pointerup", up);
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
