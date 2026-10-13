/* AutoClicker 6 – Oberflaeche. */
(() => {
  "use strict";

  const $ = (s) => document.querySelector(s);
  const $$ = (s) => Array.from(document.querySelectorAll(s));
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* egal */ } },
  };

  // ─── Verbindung zum Programm ────────────────────────────
  const params = new URLSearchParams(location.search);
  const token = params.get("t") || "";
  const client = params.get("client") || "";

  async function request(path, body) {
    const opts = { headers: { "X-Token": token }, cache: "no-store" };
    if (body !== undefined) {
      opts.method = "POST";
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    const sep = path.includes("?") ? "&" : "?";
    const res = await fetch(path + sep + "client=" + encodeURIComponent(client), opts);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) { const e = new Error(data.error || "Fehler"); e.code = res.status; throw e; }
    return data;
  }

  const api = window.AC_MOCK || {
    state: (since) => request(`/api/state?since=${since}`),
    post: (name, body) => request(`/api/${name}`, body || {}),
    bye() {
      if (client === "desktop" && navigator.sendBeacon) {
        navigator.sendBeacon(`/api/bye?t=${encodeURIComponent(token)}&client=desktop`, "{}");
      }
    },
  };

  // ─── Texte ──────────────────────────────────────────────
  const DESC = {
    standard: "Hotkey drücken: Es wird sofort automatisch geklickt, bis du ihn nochmal drückst.",
    pvp: "Hotkey drücken, dann im Spiel die Maustaste gedrückt halten. Solange du hältst, wird schnell geklickt.",
    boost: "Hotkey drücken, dann ganz normal klicken. Zu jedem Klick kommen Extra-Klicks dazu, so steigen deine CPS.",
    afk: "Klickt langsam weiter (1,6 CPS = Schwert-Cooldown ab 1.9). Ideal für Mob-Farmen.",
  };
  const STATUS = { idle: "Aus", ready: "Bereit", clicking: "Klickt", paused: "Pause", countdown: "Start" };
  const ACTIONS = { toggle: "An / Aus", on: "Nur an", off: "Nur aus" };
  const KEY_LABELS = {
    ctrl: "Strg", shift: "Shift", alt: "Alt", win: "Win", space: "Leertaste", enter: "Enter", esc: "Esc",
    backspace: "⌫", tab: "Tab", capslock: "Caps", pageup: "Bild↑", pagedown: "Bild↓", home: "Pos1",
    end: "Ende", insert: "Einfg", delete: "Entf", up: "↑", down: "↓", left: "←", right: "→",
    printscreen: "Druck", pause: "Pause", scrolllock: "Rollen", numlock: "Num", menu: "Menü",
    mouse3: "Maus 3", mouse4: "Maus 4", mouse5: "Maus 5", num_add: "Num +", num_sub: "Num −",
    num_mul: "Num ×", num_div: "Num ÷", num_dec: "Num ,", semicolon: "Ü", plus: "+", comma: ",",
    minus: "-", period: ".", slash: "#", backtick: "Ö", bracketleft: "ß", backslash: "^",
    bracketright: "´", quote: "Ä", oem102: "<",
  };
  const keyLabel = (hk) => !hk ? "—" : hk.split("+").map((p) =>
    KEY_LABELS[p] || (/^num\d$/.test(p) ? "Num " + p.slice(3) : p.toUpperCase())).join(" + ");
  const nf = (v, d = 1) => new Intl.NumberFormat("de-DE", { maximumFractionDigits: d }).format(v);
  const clock = (s) => {
    s = Math.floor(s || 0);
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
    return h ? `${h}:${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}` : `${m}:${String(r).padStart(2, "0")}`;
  };

  // ─── Zustand ────────────────────────────────────────────
  let rev = -1, C = null, INFO = null, E = null, recording = null;
  let lastNotice = 0, fails = 0, tourShown = false;
  const edited = new Map();
  const markEdit = (el) => edited.set(el.id, Date.now());
  const canSet = (el) => document.activeElement !== el && Date.now() - (edited.get(el.id) || 0) > 1500;
  const setVal = (el, v) => { if (canSet(el) && String(el.value) !== String(v)) el.value = v; };
  const setChecked = (el, v) => { if (canSet(el)) el.checked = !!v; };
  const pressed = (sel, val) => $$(sel + " [data-val]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.val === String(val))));
  // Haupt-Hotkey fuer Knopf und Hinweise: der erste, der einschalten kann
  const mainHotkey = () => C && (C.hotkeys.find((h) => h.action !== "off") || null);

  let toastTimer = null;
  function toast(text) {
    const el = $("#toast");
    el.textContent = text;
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.hidden = true; }, 2500);
  }

  async function send(name, body) {
    try {
      const st = await api.post(name, body);
      if (st && st.rev !== undefined) apply(st);
      return st;
    } catch (e) {
      toast(e.message || "Fehler");
      return null;
    }
  }

  function applyTheme(theme) {
    if (theme === "light" || theme === "dark") document.documentElement.dataset.theme = theme;
    else delete document.documentElement.dataset.theme;
    store.set("ac_theme", theme);
  }
  applyTheme(store.get("ac_theme") || "system");

  // ─── Anzeigen: Einstellungen ────────────────────────────
  function renderConfig() {
    const g = C.general, cur = C.current, mode = C.mode;
    applyTheme(g.theme);
    $$(".preset").forEach((b) => b.setAttribute("aria-current", String(b.dataset.id === C.preset)));
    const preset = C.presets.find((p) => p.id === C.preset);
    $("#title").textContent = preset ? preset.name : "";
    $("#desc").textContent = DESC[C.preset] || "";

    $("#row-speed").hidden = mode === "boost";
    $("#row-boost").hidden = mode !== "boost";
    if (canSet($("#speed"))) $("#speed").value = Math.min(30, cur.cps);
    setVal($("#speed-num"), cur.cps);
    pressed("#boost-seg", cur.boost);
    pressed("#button-seg", cur.button);

    setVal($("#o-stop"), g.auto_stop);
    setVal($("#o-delay"), g.start_delay);
    setChecked($("#o-vary"), g.vary);
    setChecked($("#o-lock"), g.window_lock);
    setVal($("#o-match"), g.window_match);
    $("#o-match-row").hidden = !g.window_lock;
    setChecked($("#o-top"), g.always_on_top);
    setChecked($("#o-sound"), g.sound);
    pressed("#theme-seg", g.theme);
    $("#version").textContent = `Version ${INFO.version}${INFO.backend === "demo" ? " · Demo" : ""}`;

    renderHotkeys();
    if (!tourShown && !g.tutorial_done) { tourShown = true; openTour(); }
  }

  function renderHotkeys() {
    const sum = $("#hk-summary");
    sum.textContent = "";
    if (!C.hotkeys.length) {
      sum.innerHTML = '<span class="muted small">Noch kein Hotkey</span>';
    }
    C.hotkeys.forEach((h) => {
      const chip = document.createElement("span");
      chip.className = "hk-chip";
      const k = document.createElement("kbd");
      k.textContent = keyLabel(h.key);
      chip.append(k, document.createTextNode(ACTIONS[h.action]));
      sum.appendChild(chip);
    });

    const list = $("#hk-list");
    list.textContent = "";
    if (!C.hotkeys.length) {
      const p = document.createElement("p");
      p.className = "hk-empty";
      p.textContent = "Noch kein Hotkey. Leg unten einen an.";
      list.appendChild(p);
    }
    C.hotkeys.forEach((h, i) => {
      const row = document.createElement("div");
      row.className = "hk-row";
      const key = document.createElement("button");
      key.type = "button";
      key.className = "keycap" + (recording === i ? " rec" : "");
      key.textContent = recording === i ? "Taste drücken …" : keyLabel(h.key);
      key.title = "Anklicken und neue Taste drücken";
      key.addEventListener("click", () => send("hotkeys", recording === i ? { op: "cancel" } : { op: "record", index: i }));
      const sel = document.createElement("select");
      sel.setAttribute("aria-label", "Was der Hotkey macht");
      Object.entries(ACTIONS).forEach(([val, label]) => {
        const o = document.createElement("option");
        o.value = val; o.textContent = label; o.selected = val === h.action;
        sel.appendChild(o);
      });
      sel.addEventListener("change", () => send("hotkeys", { op: "action", index: i, action: sel.value }));
      const del = document.createElement("button");
      del.type = "button";
      del.className = "icon-btn";
      del.textContent = "✕";
      del.setAttribute("aria-label", "Hotkey löschen");
      del.addEventListener("click", () => send("hotkeys", { op: "delete", index: i }));
      row.append(key, sel, del);
      list.appendChild(row);
    });
    const add = $("#hk-add");
    add.classList.toggle("rec", recording === "new");
    add.textContent = recording === "new" ? "Jetzt neue Taste drücken … (Esc = abbrechen)" : "+ Hotkey hinzufügen";
  }

  // ─── Anzeigen: Live ─────────────────────────────────────
  function renderLive() {
    if (!E || !C) return;
    const st = E.state, mode = C.mode, main = mainHotkey(), btn = C.current.button === "right" ? "rechte" : "linke";
    const status = $("#status");
    status.dataset.s = st;
    const secs = Math.max(1, Math.ceil(E.countdown || 0));
    status.textContent = st === "countdown" ? `Start in ${secs}` : STATUS[st] || st;
    $(".live").dataset.s = st;
    $("#cps").textContent = nf(E.cps);
    $("#st-clicks").textContent = new Intl.NumberFormat("de-DE").format(E.session_clicks);
    $("#st-time").textContent = clock(E.run_time);
    $("#st-best").textContent = nf(E.best_cps);

    const start = $("#start");
    start.classList.toggle("stop", E.armed);
    start.classList.toggle("wait", st === "countdown");
    $("#start-label").textContent = st === "countdown" ? "Abbrechen" : E.armed ? "Stopp" : "Start";
    $("#start-key").hidden = !main;
    $("#start-key").textContent = main ? keyLabel(main.key) : "";
    let hint;
    if (st === "countdown") {
      hint = "Nochmal den Hotkey drücken bricht ab.";
    } else if (E.armed) {
      if (st === "paused") hint = E.reason === "self" ? "Läuft – wechsle ins Spiel. In dieses Fenster wird nicht geklickt." : "Pause – Minecraft ist nicht im Vordergrund.";
      else if (mode === "hold_mouse") hint = st === "clicking" ? "Klickt, solange du hältst." : `Bereit – halte die ${btn} Maustaste gedrückt.`;
      else if (mode === "boost") hint = st === "clicking" ? "Boost!" : "Bereit – klick einfach ganz normal.";
      else hint = "Klickt dort, wo die Maus gerade ist.";
    } else {
      hint = main ? `Drück ${keyLabel(main.key)} – auch mitten im Spiel.` : "Leg unter „Hotkeys bearbeiten“ eine Taste an.";
      if (E.stop_reason === "limit") hint = "Auto-Stopp erreicht.";
    }
    $("#hint").textContent = recording !== null ? "Drück jetzt die neue Taste (Esc = abbrechen)." : hint;
    $("#hint").classList.toggle("attn", recording === null && st === "paused");
  }

  // ─── Update-Hinweis ────────────────────────────────────
  let closing = false;
  function renderUpdate(u) {
    const bar = $("#update");
    bar.hidden = !u;
    if (!u) return;
    const busy = u.status === "downloading" || u.status === "installing";
    bar.classList.toggle("error", u.status === "error");
    $("#update-btns").hidden = busy;
    $("#update-install").textContent = u.status === "error" ? "Nochmal versuchen" : u.can_install ? "Jetzt aktualisieren" : "Zum Download";
    $("#update-text").textContent =
      u.status === "downloading" ? `Update ${u.version} wird geladen … ${Math.round(u.progress * 100)} %`
      : u.status === "installing" ? `Update ${u.version} wird installiert – AutoClicker startet gleich neu.`
      : u.status === "error" ? `Update fehlgeschlagen: ${u.error}`
      : `Neue Version ${u.version} ist da.`;
    if (u.status === "installing" && !closing && client === "desktop") {
      closing = true;
      setTimeout(() => window.close(), 1500);  // die neue Version oeffnet ein neues Fenster
    }
  }
  $("#update-install").addEventListener("click", () => send("update", { op: "install" }));
  $("#update-later").addEventListener("click", () => send("update", { op: "later" }));
  $("#update-skip").addEventListener("click", () => send("update", { op: "skip" }));

  function apply(st) {
    const wasRecording = recording;
    if (st.config) { C = st.config; INFO = st.info; rev = st.rev; }
    E = st.engine;
    recording = st.recording === undefined ? null : st.recording;
    if (st.config) renderConfig();
    else if (wasRecording !== recording && C) renderHotkeys();
    renderUpdate(st.update || null);
    if (st.notice && st.notice.id !== lastNotice) { lastNotice = st.notice.id; toast(st.notice.text); }
    renderLive();
  }

  async function poll() {
    try {
      apply(await api.state(rev));
      fails = 0;
      $("#offline").hidden = true;
    } catch (e) {
      fails++;
      if (fails >= 3) $("#offline").hidden = false;
    }
    setTimeout(poll, document.hidden ? 1000 : 200);
  }

  // ─── Eingaben ───────────────────────────────────────────
  let presetPatch = {}, presetTimer = null;
  function sendPreset(part) {
    Object.assign(presetPatch, part);
    if (C) { Object.assign(C.current, part); renderConfig(); renderLive(); }
    clearTimeout(presetTimer);
    presetTimer = setTimeout(() => { const p = presetPatch; presetPatch = {}; send("settings", { preset: p }); }, 200);
  }
  function sendGeneral(part) {
    if (C) Object.assign(C.general, part);
    send("settings", { general: part });
  }

  $$(".preset").forEach((b) => b.addEventListener("click", () => send("preset", { id: b.dataset.id })));
  $$("#button-seg [data-val]").forEach((b) => b.addEventListener("click", () => sendPreset({ button: b.dataset.val })));
  $$("#boost-seg [data-val]").forEach((b) => b.addEventListener("click", () => sendPreset({ boost: +b.dataset.val })));
  $("#speed").addEventListener("input", (e) => { markEdit(e.target); sendPreset({ cps: +e.target.value }); });

  function numberInput(el, fn) {
    let t = null;
    const go = () => { const v = parseFloat(String(el.value).replace(",", ".")); if (!isNaN(v)) fn(v); };
    el.addEventListener("input", () => { markEdit(el); clearTimeout(t); t = setTimeout(go, 500); });
    el.addEventListener("change", () => { markEdit(el); clearTimeout(t); go(); });
  }
  numberInput($("#speed-num"), (v) => sendPreset({ cps: Math.min(1000, Math.max(0.1, v)) }));
  numberInput($("#o-stop"), (v) => sendGeneral({ auto_stop: Math.max(0, v) }));
  numberInput($("#o-delay"), (v) => sendGeneral({ start_delay: Math.max(0, Math.min(60, v)) }));
  [["#o-vary", "vary"], ["#o-lock", "window_lock"], ["#o-top", "always_on_top"], ["#o-sound", "sound"]].forEach(([sel, key]) =>
    $(sel).addEventListener("change", (e) => { markEdit(e.target); sendGeneral({ [key]: e.target.checked }); }));
  $("#o-match").addEventListener("change", (e) => { markEdit(e.target); sendGeneral({ window_match: e.target.value }); });
  $$("#theme-seg [data-val]").forEach((b) => b.addEventListener("click", () => { applyTheme(b.dataset.val); sendGeneral({ theme: b.dataset.val }); }));

  $("#start").addEventListener("click", () => send("action", { do: "toggle" }));
  $("#reset-stats").addEventListener("click", async () => { await send("action", { do: "reset_stats" }); toast("Statistik zurückgesetzt"); });

  // Dialoge
  function closeDialogs() {
    $("#settings").hidden = true;
    if (!$("#hotkeys").hidden) {
      $("#hotkeys").hidden = true;
      if (recording !== null) send("hotkeys", { op: "cancel" });
    }
  }
  $("#settings-btn").addEventListener("click", () => { $("#settings").hidden = false; });
  $("#hotkeys-btn").addEventListener("click", () => { $("#hotkeys").hidden = false; });
  $$("#settings, #hotkeys").forEach((ov) => ov.addEventListener("click", (e) => {
    if (e.target === ov || e.target.closest("[data-close]")) closeDialogs();
  }));
  $("#hk-add").addEventListener("click", () => send("hotkeys", recording === "new" ? { op: "cancel" } : { op: "record" }));

  // ─── Anleitung (3 Schritte) ─────────────────────────────
  const TOUR = [
    { t: "Modus wählen", p: "Links wählst du, wie geklickt wird: Standard, Minecraft PvP (Maustaste halten), CPS-Boost (jeder Klick zählt doppelt) oder AFK-Farm.",
      i: '<svg viewBox="0 0 24 24"><path d="M3 5h18v2H3zm0 6h18v2H3zm0 6h12v2H3z"/></svg>' },
    { t: "Tempo einstellen", p: "Mit dem Regler stellst du ein, wie viele Klicks pro Sekunde (CPS) es sein sollen. Beim Boost wählst du ×2 oder ×3.",
      i: '<svg viewBox="0 0 24 24"><path d="M3 11h11v2H3zm15 0h3v2h-3zM14 8h2v8h-2z"/></svg>' },
    { t: "Starten", p: "Drück F6 – das geht auch mitten im Spiel, und es wird sofort geklickt. Nochmal F6 stoppt. Unter „Hotkeys bearbeiten“ legst du eigene Tasten an.",
      i: '<svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>' },
  ];
  let tourStep = 0;
  function renderTour() {
    const s = TOUR[tourStep], main = mainHotkey();
    $("#tour-art").innerHTML = s.i;
    $("#tour-title").textContent = s.t;
    $("#tour-text").textContent = tourStep === 2 && main ? s.p.replace(/F6/g, keyLabel(main.key)) : s.p;
    $$("#tour-dots i").forEach((d, i) => d.classList.toggle("on", i === tourStep));
    $("#tour-next").textContent = tourStep === TOUR.length - 1 ? "Los geht's" : "Weiter";
  }
  function openTour() { tourStep = 0; renderTour(); $("#tutorial").hidden = false; }
  function closeTour() {
    $("#tutorial").hidden = true;
    if (C && !C.general.tutorial_done) sendGeneral({ tutorial_done: true });
  }
  $("#help-btn").addEventListener("click", openTour);
  $("#tour-skip").addEventListener("click", closeTour);
  $("#tour-next").addEventListener("click", () => { if (tourStep < TOUR.length - 1) { tourStep++; renderTour(); } else closeTour(); });

  // ─── Tasten-Aufnahme ────────────────────────────────────
  const CODE_NAMES = {
    Space: "space", Enter: "enter", NumpadEnter: "enter", Tab: "tab", Backspace: "backspace", Home: "home",
    End: "end", PageUp: "pageup", PageDown: "pagedown", Insert: "insert", Delete: "delete", ArrowUp: "up",
    ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right", CapsLock: "capslock", Pause: "pause",
    ScrollLock: "scrolllock", NumLock: "numlock", PrintScreen: "printscreen", ContextMenu: "menu",
    NumpadAdd: "num_add", NumpadSubtract: "num_sub", NumpadMultiply: "num_mul", NumpadDivide: "num_div",
    NumpadDecimal: "num_dec", ShiftLeft: "shift", ShiftRight: "shift", ControlLeft: "ctrl", ControlRight: "ctrl",
    AltLeft: "alt", AltRight: "alt", MetaLeft: "win", MetaRight: "win",
  };
  const codeName = (c) => /^F\d{1,2}$/.test(c) ? c.toLowerCase() : /^Key[A-Z]$/.test(c) ? c.slice(3).toLowerCase()
    : /^Digit\d$/.test(c) ? c.slice(5) : /^Numpad\d$/.test(c) ? "num" + c.slice(6) : CODE_NAMES[c] || null;
  const MODS = ["ctrl", "shift", "alt", "win"];
  const modsOf = (e, except) => [e.ctrlKey && "ctrl", e.shiftKey && "shift", e.altKey && "alt", e.metaKey && "win"].filter((m) => m && m !== except);
  // Unter Windows nimmt der globale Hook die Taste auf; ohne Hook (Demo) macht es der Browser.
  const browserRecords = () => !INFO || INFO.backend !== "windows";
  let pendingMod = null;
  window.addEventListener("keydown", (e) => {
    if (recording === null) {
      if (e.key === "Escape") { closeDialogs(); if (!$("#tutorial").hidden) closeTour(); }
      return;
    }
    e.preventDefault();
    if (e.repeat) return;
    if (e.code === "Escape") { send("hotkeys", { op: "cancel" }); return; }
    const name = codeName(e.code);
    if (!name) return;
    if (MODS.includes(name)) { pendingMod = name; return; }
    pendingMod = null;
    if (browserRecords()) send("hotkeys", { op: "key", key: [...modsOf(e), name].join("+") });
  }, true);
  window.addEventListener("keyup", (e) => {
    if (recording === null) return;
    e.preventDefault();
    const name = codeName(e.code);
    if (name && name === pendingMod && browserRecords()) send("hotkeys", { op: "key", key: [...modsOf(e, name), name].join("+") });
    pendingMod = null;
  }, true);
  window.addEventListener("mousedown", (e) => {
    if (recording === null || e.button === 0 || e.button === 2) return;
    e.preventDefault();
    const name = { 1: "mouse3", 3: "mouse4", 4: "mouse5" }[e.button];
    if (name && browserRecords()) send("hotkeys", { op: "key", key: [...modsOf(e), name].join("+") });
  }, true);

  window.addEventListener("pagehide", () => api.bye());
  if (!token && !window.AC_MOCK) $("#offline").hidden = false;
  poll();
})();
