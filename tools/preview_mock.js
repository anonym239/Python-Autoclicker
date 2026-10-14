/* Simuliert das Python-Programm im Browser – nur fuer die Vorschau-Datei.
   Gleiche API wie der echte Server (state / post / bye). */
window.AC_MOCK = (() => {
  "use strict";
  const CONFIG = __CONFIG__;
  const PRESETS = __PRESETS__;

  const cfg = JSON.parse(JSON.stringify(CONFIG));
  let update = { version: "6.20", status: "available", progress: 0, error: "", can_install: true };
  let rev = 1, recording = null, recordUntil = 0, notice = null, noticeId = 0;
  let learning = false, slot = 1, learnPress = null;
  cfg.kits = cfg.kits || [{ name: "Kit 1", tools: [] }];
  cfg.kit = cfg.kit || 0;
  // Werkzeuge des gewaehlten Kits
  const T = () => cfg.kits[cfg.kit].tools;
  const setT = (list) => { cfg.kits[cfg.kit].tools = list; };
  // Vorschau: auf Platz 3 liegt eine Spitzhacke, sonst ein Schwert (Tasten 1–9 wechseln)
  const toolIndex = () => (slot === 3 ? T().findIndex((x) => x.demo) : -1);
  const isTool = () => (mode() === "hold_mouse" || mode() === "boost") && toolIndex() >= 0;
  // Vorschau: kleine Pixel-Spitzhacke als "abfotografiertes" Item
  function demoIcon() {
    const c = document.createElement("canvas"); c.width = c.height = 16;
    const g = c.getContext("2d");
    g.fillStyle = "#6b4a2b"; for (let i = 3; i < 14; i++) g.fillRect(i, 15 - i, 2, 2);
    g.fillStyle = "#4fd1c5"; [[3,2],[4,1],[5,1],[6,1],[7,1],[8,1],[9,2],[10,3],[11,4],[12,5],[13,6],[14,7],[14,8],[13,9]].forEach(([x, y]) => g.fillRect(x, y, 1, 2));
    return c.toDataURL("image/png");
  }
  const now = () => performance.now() / 1000;
  const eng = {
    armed: false, runStart: null, session: 0, lifetime: 0, best: 0, stopReason: "",
    mouse: new Set(), owed: 0, due: null, nextT: null, state: "idle", reason: "", samples: [], cps: 0,
  };
  const mode = () => PRESETS[cfg.preset].mode;
  const cur = () => cfg.presets[cfg.preset];
  const notify = (key) => { noticeId++; notice = { id: noticeId, key, at: Date.now() }; };
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

  function arm() { eng.armed = true; eng.countdownEnd = null; eng.runStart = now(); eng.owed = 0; eng.nextT = null; }
  function start() {
    if (eng.armed || eng.countdownEnd) return;
    eng.stopReason = "";
    if (cfg.general.start_delay > 0) eng.countdownEnd = now() + cfg.general.start_delay; else arm();
  }
  function stop(reason) {
    if (eng.armed || eng.countdownEnd) eng.stopReason = reason;
    eng.countdownEnd = null;
    eng.armed = false; eng.runStart = null; eng.owed = 0;
    if (reason === "limit") notify("n_limit");
  }
  const toggle = () => (eng.armed || eng.countdownEnd ? stop("manual") : start());

  function evaluate() {
    const m = mode(), held = eng.mouse.has(cur().button);
    if (eng.countdownEnd) return ["countdown", ""];
    if (!eng.armed) return ["idle", ""];
    if (isTool()) return ["ready", "tool"];
    if (m === "hold_mouse" && !held) return ["ready", "mouse"];
    if (m === "boost" && (!eng.owed || held)) return ["ready", "boost"];
    return ["clicking", ""];
  }
  const rate = () => (cfg.general.vary ? cur().cps * (0.88 + Math.random() * 0.24) : cur().cps);
  function step() {
    const t = now();
    if (eng.countdownEnd && t >= eng.countdownEnd) arm();
    if (eng.armed && cfg.general.auto_stop > 0 && t - eng.runStart >= cfg.general.auto_stop) stop("limit");
    [eng.state, eng.reason] = evaluate();
    if (eng.state !== "clicking") { eng.nextT = null; return; }
    if (mode() === "toggle" && cur().action === "hold") return;  // haelt nur gedrueckt
    if (mode() === "boost") {
      if (t >= eng.due) { eng.owed--; eng.session++; eng.due = t + 0.028 + Math.random() * 0.017; }
      return;
    }
    if (eng.nextT === null) eng.nextT = t + (mode() === "hold_mouse" ? 1 / rate() : 0);
    let guard = 0;
    while (eng.nextT <= t && guard++ < 400) { eng.session++; eng.nextT += 1 / rate(); }
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
    if (recording !== null && t > recordUntil) recording = null;
  }, 250);

  function state(since) {
    const out = {
      rev,
      engine: {
        state: eng.state, reason: eng.reason, stop_reason: eng.stopReason, armed: eng.armed,
        countdown: eng.countdownEnd ? Math.max(0, eng.countdownEnd - now()) : null,
        holding: eng.state === "clicking" && mode() === "toggle" && cur().action === "hold",
        run_time: eng.runStart !== null ? now() - eng.runStart : 0, session_clicks: eng.session,
        lifetime_clicks: eng.lifetime + eng.session, cps: Math.round(eng.cps * 10) / 10,
        best_cps: Math.round(eng.best * 10) / 10,
      },
      recording,
      learning,
      tool_index: (mode() === "hold_mouse" || mode() === "boost") ? toolIndex() : -1,
      hotbar: true,
      update,
      notice: notice && Date.now() - notice.at < 6000 ? notice : null,
    };
    if (String(since) !== String(rev)) {
      const general = { ...cfg.general };
      delete general.token; delete general.port;
      out.config = {
        preset: cfg.preset,
        presets: Object.keys(PRESETS).map((id) => ({ id, name: PRESETS[id].name, mode: PRESETS[id].mode })),
        mode: mode(), current: { ...cur() }, hotkeys: cfg.hotkeys.map((h) => ({ ...h })),
        tools: T().map((x) => ({ ...x })), general,
        kits: cfg.kits.map((k) => ({ name: k.name, count: k.tools.length })), kit: cfg.kit,
        pins: (cfg.pins || []).map((x) => ({ ...x })), games: ["minecraft", "roblox", "terraria", "cookie", "other"],
      };
      out.info = { name: "AutoClicker", version: "__VERSION__", backend: "demo", hooks_ok: false };
    }
    return out;
  }

  function fail(msg) { const e = new Error(msg); e.code = 400; throw e; }

  function hotkeys(b) {
    if (b.op === "record") { recording = b.index === undefined || b.index === null ? (b.target === "learn" ? "learn" : "new") : b.index; recordUntil = now() + 15; }
    else if (b.op === "cancel") recording = null;
    else if (b.op === "key") {
      const key = String(b.key || ""), target = recording;
      recording = null;
      if (!key || target === null) return;
      if (target === "learn") {
        if (cfg.hotkeys.some((h) => h.key === key)) { notify("e_key_taken"); return; }
        cfg.general.learn_hotkey = key; cfg.general.learn_hotkey_on = true; notify("n_hotkey_saved"); return;
      }
      if (cfg.hotkeys.some((h, i) => h.key === key && i !== target)) { notify("e_key_taken"); return; }
      if (target === "new") {
        if (cfg.hotkeys.length >= 8) { notify("e_max_hotkeys"); return; }
        cfg.hotkeys.push({ key, action: "toggle" });
      } else cfg.hotkeys[target].key = key;
      notify("n_hotkey_saved");
    } else if (b.op === "action") {
      if (!cfg.hotkeys[b.index]) fail("Hotkey nicht gefunden");
      cfg.hotkeys[b.index].action = b.action;
    } else if (b.op === "delete") {
      if (!cfg.hotkeys[b.index]) fail("Hotkey nicht gefunden");
      cfg.hotkeys.splice(b.index, 1);
    }
  }

  async function post(name, b) {
    await new Promise((r) => setTimeout(r, 25));
    if (name === "action") {
      if (b.do === "toggle") toggle();
      else if (b.do === "stop") stop("manual");
      else if (b.do === "reset_stats") { eng.lifetime += eng.session; eng.session = 0; eng.best = 0; }
      return state(rev);
    }
    if (name === "settings") {
      if (b.preset) {
        const p = cur();
        if (b.preset.button) p.button = b.preset.button;
        if ("cps" in b.preset) p.cps = clamp(+b.preset.cps || 0.1, 0.1, 1000);
        if ("boost" in b.preset) p.boost = clamp(Math.round(+b.preset.boost), 2, 3);
        if (b.preset.action === "click" || b.preset.action === "hold") p.action = b.preset.action;
      }
      if (b.general) Object.assign(cfg.general, b.general);
    } else if (name === "preset") {
      if (!PRESETS[b.id]) fail("Unbekannter Modus");
      if (b.id !== cfg.preset && (eng.armed || eng.countdownEnd)) stop("manual");
      cfg.preset = b.id; eng.owed = 0;
    } else if (name === "hotkeys") {
      hotkeys(b);
    } else if (name === "tools") {
      if (b.op === "learn") learning = true;  // Klicker bleibt an (pausiert nur)
      else if (b.op === "cancel") learning = false;
      else if (b.op === "delete") setT(T().filter((x, i) => i !== b.index));
      else if (b.op === "kit_select") { if (cfg.kits[b.index]) cfg.kit = b.index; }
      else if (b.op === "kit_new") {
        if (cfg.kits.length >= 10) fail("e_max_kits");
        cfg.kits.push({ name: String(b.name || "").trim().slice(0, 30) || `Kit ${cfg.kits.length + 1}`, tools: [] });
        cfg.kit = cfg.kits.length - 1;
      } else if (b.op === "kit_rename") { const n = String(b.name || "").trim().slice(0, 30); if (n && cfg.kits[b.index]) cfg.kits[b.index].name = n; }
      else if (b.op === "kit_delete") {
        if (cfg.kits.length === 1) cfg.kits = [{ name: "Kit 1", tools: [] }];
        else { cfg.kits.splice(b.index, 1); if (cfg.kit >= cfg.kits.length || cfg.kit > b.index) cfg.kit = Math.max(0, cfg.kit - 1); }
      }
      else if (b.op === "export") {
        if (!T().length) fail("e_no_tools");
        const kit = cfg.kits[cfg.kit];
        const blob = new Blob([JSON.stringify({ app: "AutoClicker", type: "kit", name: kit.name, tools: T() }, null, 1)], { type: "application/json" });
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob); a.download = `AutoClicker-${kit.name.replace(/[^\w-]+/g, "-")}.json`; a.click();
        noticeId++; notice = { id: noticeId, key: "n_tools_exported", vars: { path: "Downloads" }, at: Date.now() };
      } else if (b.op === "import") {
        const items = Array.isArray(b.data) ? b.data : b.data && b.data.tools;
        if (!Array.isArray(items)) fail("e_import");
        if (T().length) {
          if (cfg.kits.length >= 10) fail("e_max_kits");
          cfg.kits.push({ name: "", tools: [] }); cfg.kit = cfg.kits.length - 1;
        }
        const kit = cfg.kits[cfg.kit];
        if (b.data && typeof b.data.name === "string" && b.data.name.trim()) kit.name = b.data.name.trim().slice(0, 30);
        if (!kit.name) kit.name = `Kit ${cfg.kit + 1}`;
        let n = 0;
        items.forEach((x) => { if (x && x.icon && T().length < 30) { T().push(x); n++; } });
        noticeId++; notice = { id: noticeId, key: "n_tools_imported", vars: { n }, at: Date.now() };
      }
    } else if (name === "home") {
      // Vorschau: Seiten in einem neuen Tab, Programme gehen hier nicht
      if (b.op === "signin") { window.open("https://accounts.google.com/", "_blank", "noopener"); return { ok: true }; }
      if (b.op === "open") {
        const p = Number.isInteger(b.index) ? cfg.pins[b.index] : null;
        const text = String(b.text || "").trim();
        const url = p ? p.url : /^\S+\.\S+$/.test(text) ? (/^https?:/i.test(text) ? text : "https://" + text)
          : "https://www.google.com/search?q=" + encodeURIComponent(text);
        if (!url) fail("e_open");
        window.open(url, "_blank", "noopener");
        return { ok: true };
      } else if (b.op === "pin_add") {
        const target = String(b.target || "").trim();
        const isApp = /^[a-z]:\\.+\.(exe|lnk|url)$/i.test(target) || /^[a-z][a-z0-9+.-]+:(\/\/)?$/i.test(target);
        if (!isApp && !/^\S+\.[a-z]{2,}(\/\S*)?$/i.test(target.replace(/^https?:\/\//i, ""))) fail("e_pin_target");
        if (cfg.pins.length >= 12) fail("e_max_pins");
        const url = isApp ? "" : (/^https?:/i.test(target) ? target : "https://" + target);
        const name = String(b.name || "").trim() || (url ? new URL(url).hostname.replace(/^www\./, "").split(".")[0] : target.split(/[\\:]/).filter(Boolean).pop());
        cfg.pins.push(isApp ? { name: name.charAt(0).toUpperCase() + name.slice(1), app: target } : { name: name.charAt(0).toUpperCase() + name.slice(1), url });
      } else if (b.op === "pin_remove") cfg.pins.splice(b.index, 1);
    } else if (name === "update") {
      if (b.op === "later") { update = null; notify("Erinnerung in 5 Tagen"); }
      else if (b.op === "skip") update = null;
      else if (b.op === "install") {
        update = { ...update, status: "downloading" };
        const t = setInterval(() => {
          update.progress = Math.min(1, update.progress + 0.1);
          if (update.progress >= 1) { clearInterval(t); update = { ...update, status: "installing" }; setTimeout(() => { update = null; notify("Vorschau: hier würde die neue Version starten"); }, 2500); }
        }, 200);
      }
    }
    rev++;
    return state(-1);
  }

  // Hotkeys und echte Mausklicks in der Vorschau nachstellen (nur solange die Seite den Fokus hat)
  const typing = (el) => el && (el.tagName === "INPUT" || el.tagName === "SELECT");
  const keyName = (e) => (/^F\d{1,2}$/.test(e.code) ? e.code.toLowerCase() : /^Key[A-Z]$/.test(e.code) ? e.code.slice(3).toLowerCase() : null);
  window.addEventListener("keydown", (e) => {
    if (recording !== null || typing(document.activeElement) || e.repeat) return;
    if (/^Digit[1-9]$/.test(e.code)) { slot = +e.code.slice(5); return; }
    const hk = cfg.hotkeys.find((h) => h.key === keyName(e));
    if (!hk) return;
    e.preventDefault();
    if (hk.action === "on") start(); else if (hk.action === "off") stop("manual"); else toggle();
  });
  const interactive = (el) => el && el.closest && el.closest("button, input, select, label, a, .side, .overlay, .pv-bar, .card.rows");
  const BTN = { 0: "left", 2: "right" };
  window.addEventListener("pointerdown", (e) => {
    const b = BTN[e.button];
    if (!b || interactive(e.target)) return;
    if (learning && b === "left") learnPress = now();
    if (eng.armed && b === cur().button && mode() !== "toggle") eng.session++;
    eng.mouse.add(b);
  });
  window.addEventListener("pointerup", (e) => {
    const b = BTN[e.button] || "left";
    const was = eng.mouse.delete(b);
    if (learning && learnPress !== null) {
      if (slot !== 3) notify("e_tool_empty");  // Vorschau: nur Platz 3 hat ein Werkzeug
      else {
        setT(T().filter((x) => !x.demo).concat([{ mask: "", icon: demoIcon(), demo: true }]));
        learning = false; rev++; notify("n_tool_saved");
      }
    }
    learnPress = null;
    if (was && eng.armed && mode() === "boost" && b === cur().button) {
      eng.owed = Math.min(6, eng.owed + cur().boost - 1);
      eng.due = now() + 0.012 + Math.random() * 0.012;
    }
  });
  window.addEventListener("pointercancel", () => eng.mouse.clear());
  window.addEventListener("contextmenu", (e) => { if (!interactive(e.target)) e.preventDefault(); });

  return { state: async (since) => state(since), post, bye() {} };
})();
