/* AutoClicker 6 – Oberflaeche (PC-Fenster und Handy). */
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
  const token = params.get("t") || store.get("ac_token") || "";
  if (params.get("t")) store.set("ac_token", token);
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
    qrUrl: (rev) => `/api/qr.svg?t=${encodeURIComponent(token)}&v=${rev}`,
    bye() {
      if (client === "desktop" && navigator.sendBeacon) {
        navigator.sendBeacon(`/api/bye?t=${encodeURIComponent(token)}&client=desktop`, "{}");
      }
    },
  };

  // ─── Texte ──────────────────────────────────────────────
  const DESC = {
    standard: "Drück den Hotkey: Es wird automatisch geklickt, bis du ihn nochmal drückst.",
    pvp: "Hotkey drücken, dann im Spiel die Maustaste gedrückt halten. Solange du hältst, wird schnell geklickt.",
    boost: "Hotkey drücken, dann ganz normal klicken. Zu jedem Klick kommen Extra-Klicks dazu, so steigen deine CPS.",
    afk: "Klickt langsam weiter (1,6 CPS = Schwert-Cooldown ab 1.9). Ideal für Mob-Farmen.",
  };
  const STATUS = { idle: "Aus", ready: "Bereit", clicking: "Klickt", paused: "Pause", countdown: "Start" };
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
  let rev = -1, C = null, INFO = null, E = null, recording = false;
  let lastNotice = 0, fails = 0, lastArmed = null, tourShown = false;
  const edited = new Map();
  const markEdit = (el) => edited.set(el.id, Date.now());
  const canSet = (el) => document.activeElement !== el && Date.now() - (edited.get(el.id) || 0) > 1500;
  const setVal = (el, v) => { if (canSet(el) && String(el.value) !== String(v)) el.value = v; };
  const setChecked = (el, v) => { if (canSet(el)) el.checked = !!v; };
  const pressed = (sel, val) => $$(sel + " [data-val]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.val === String(val))));

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
      toast(e.code === 403 ? "Code ungültig – QR-Code neu scannen" : e.message || "Fehler");
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
    document.body.classList.toggle("is-remote", !!INFO.remote_client);
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
    $("#hotkey").textContent = recording ? "Taste drücken …" : keyLabel(C.hotkey);
    $("#start-key").textContent = keyLabel(C.hotkey);
    $("#start-key").hidden = !C.hotkey;

    setVal($("#o-stop"), g.auto_stop);
    setVal($("#o-delay"), g.start_delay);
    setChecked($("#o-vary"), g.vary);
    setChecked($("#o-lock"), g.window_lock);
    setVal($("#o-match"), g.window_match);
    $("#o-match-row").hidden = !g.window_lock;
    setChecked($("#o-top"), g.always_on_top);
    setChecked($("#o-sound"), g.sound);
    pressed("#theme-seg", g.theme);
    setChecked($("#o-remote"), g.remote);
    $("#remote-box").hidden = !g.remote;
    if (g.remote) {
      $("#remote-url").textContent = INFO.remote_url || "Keine WLAN-Verbindung gefunden";
      const src = api.qrUrl(rev);
      if ($("#qr").dataset.src !== src) { $("#qr").dataset.src = src; $("#qr").src = src; }
    }
    $("#remote-err").hidden = !INFO.remote_error;
    $("#remote-err").textContent = INFO.remote_error ? "Freigabe fehlgeschlagen: " + INFO.remote_error : "";
    $("#version").textContent = `Version ${INFO.version}${INFO.backend === "demo" ? " · Demo" : ""}`;

    if (!tourShown && !g.tutorial_done && !INFO.remote_client) { tourShown = true; openTour(); }
  }

  // ─── Anzeigen: Live ─────────────────────────────────────
  function renderLive() {
    if (!E || !C) return;
    const st = E.state, mode = C.mode, hk = keyLabel(C.hotkey), btn = C.current.button === "right" ? "rechte" : "linke";
    const status = $("#status");
    status.dataset.s = st;
    status.textContent = st === "countdown" ? `Start in ${Math.max(1, Math.ceil(E.countdown || 0))}` : STATUS[st] || st;
    $(".live").dataset.s = st;
    $("#cps").textContent = nf(E.cps);
    $("#st-clicks").textContent = new Intl.NumberFormat("de-DE").format(E.session_clicks);
    $("#st-time").textContent = clock(E.run_time);
    $("#st-best").textContent = nf(E.best_cps);

    const start = $("#start");
    start.classList.remove("stop", "wait");
    start.disabled = false;
    let label = "Start", hint;
    if (st === "countdown") {
      start.classList.add("wait"); label = "Abbrechen";
      hint = "Jetzt ins Spiel wechseln …";
    } else if (E.armed) {
      start.classList.add("stop"); label = "Stopp";
      if (st === "paused") hint = E.reason === "self" ? "Pause – in dieses Fenster wird nicht geklickt." : "Pause – Minecraft ist nicht im Vordergrund.";
      else if (mode === "hold_mouse") hint = st === "clicking" ? "Klickt, solange du hältst." : `Bereit – halte die ${btn} Maustaste gedrückt.`;
      else if (mode === "boost") hint = st === "clicking" ? "Boost!" : "Bereit – klick einfach ganz normal.";
      else hint = "Klickt dort, wo die Maus gerade ist.";
    } else {
      hint = C.hotkey ? `Drück ${hk} – auch mitten im Spiel.` : "Klick auf das Hotkey-Feld und wähle eine Taste.";
      if (E.stop_reason === "limit") hint = "Auto-Stopp erreicht.";
    }
    $("#start-label").textContent = label;
    $("#hint").textContent = recording ? "Drück jetzt die neue Taste (Esc = abbrechen)." : hint;
    $("#hotkey").classList.toggle("rec", recording);
    $("#hotkey").textContent = recording ? "Taste drücken …" : hk;

    if (lastArmed !== null && lastArmed !== E.armed && INFO && INFO.remote_client) {
      try { navigator.vibrate && navigator.vibrate(E.armed ? 40 : 90); } catch (e) { /* egal */ }
    }
    lastArmed = E.armed;
  }

  function apply(st) {
    if (st.config) { C = st.config; INFO = st.info; rev = st.rev; }
    E = st.engine;
    recording = !!st.recording;
    if (st.config) renderConfig();
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
      if (fails >= 3) {
        $("#offline").hidden = false;
        $("#offline-text").textContent = e.code === 403
          ? "Der Code ist ungültig. Scanne den QR-Code am PC neu (Einstellungen → Handy)."
          : "Läuft der AutoClicker auf dem PC noch? Neuer Versuch läuft …";
      }
    }
    setTimeout(poll, document.hidden ? 1000 : INFO && INFO.remote_client ? 350 : 200);
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

  $("#o-remote").addEventListener("change", (e) => { markEdit(e.target); send("remote", { enabled: e.target.checked }); });
  $("#copy-url").addEventListener("click", async () => {
    try { await navigator.clipboard.writeText($("#remote-url").textContent); toast("Adresse kopiert"); }
    catch (e) {
      const r = document.createRange(); r.selectNodeContents($("#remote-url"));
      const s = getSelection(); s.removeAllRanges(); s.addRange(r);
      toast("Markiert – jetzt Strg+C");
    }
  });

  $("#start").addEventListener("click", () => send("action", { do: "toggle" }));
  $("#reset-stats").addEventListener("click", async () => { await send("action", { do: "reset_stats" }); toast("Statistik zurückgesetzt"); });

  // Einstellungen
  const openSettings = () => { $("#settings").hidden = false; };
  const closeOverlays = () => { $("#settings").hidden = true; };
  $("#settings-btn").addEventListener("click", openSettings);
  $("#settings").addEventListener("click", (e) => { if (e.target.id === "settings" || e.target.closest("[data-close]")) closeOverlays(); });

  // ─── Anleitung (3 Schritte) ─────────────────────────────
  const TOUR = [
    { t: "Modus wählen", p: "Links wählst du, wie geklickt wird: Standard, Minecraft PvP (Maustaste halten), CPS-Boost (jeder Klick zählt doppelt) oder AFK-Farm.",
      i: '<svg viewBox="0 0 24 24"><path d="M3 5h18v2H3zm0 6h18v2H3zm0 6h12v2H3z"/></svg>' },
    { t: "Tempo einstellen", p: "Mit dem Regler stellst du ein, wie viele Klicks pro Sekunde (CPS) es sein sollen. Beim Boost wählst du ×2 oder ×3.",
      i: '<svg viewBox="0 0 24 24"><path d="M3 11h11v2H3zm15 0h3v2h-3zM14 8h2v8h-2z"/></svg>' },
    { t: "Starten", p: "Drück F6 – das geht auch mitten im Spiel. Nochmal F6 stoppt. Den Hotkey änderst du, indem du auf das Tasten-Feld klickst.",
      i: '<svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>' },
  ];
  let tourStep = 0;
  function renderTour() {
    const s = TOUR[tourStep];
    $("#tour-art").innerHTML = s.i;
    $("#tour-title").textContent = s.t;
    $("#tour-text").textContent = tourStep === 2 && C ? s.p.replace(/F6/g, keyLabel(C.hotkey)) : s.p;
    $$("#tour-dots i").forEach((d, i) => d.classList.toggle("on", i === tourStep));
    $("#tour-next").textContent = tourStep === TOUR.length - 1 ? "Los geht's" : "Weiter";
  }
  function openTour() { tourStep = 0; renderTour(); $("#tutorial").hidden = false; }
  function closeTour() {
    $("#tutorial").hidden = true;
    if (C && !C.general.tutorial_done && !(INFO && INFO.remote_client)) sendGeneral({ tutorial_done: true });
  }
  $("#help-btn").addEventListener("click", openTour);
  $("#tour-skip").addEventListener("click", closeTour);
  $("#tour-next").addEventListener("click", () => { if (tourStep < TOUR.length - 1) { tourStep++; renderTour(); } else closeTour(); });
  window.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !recording) { closeOverlays(); if (!$("#tutorial").hidden) closeTour(); }
  });

  // ─── Hotkey ändern ──────────────────────────────────────
  $("#hotkey").addEventListener("click", () => send("record", recording ? { cancel: true } : {}));
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
    if (!recording) return;
    e.preventDefault();
    if (e.repeat) return;
    if (e.code === "Escape") { send("record", { cancel: true }); return; }
    const name = codeName(e.code);
    if (!name) return;
    if (MODS.includes(name)) { pendingMod = name; return; }
    pendingMod = null;
    if (browserRecords()) send("record", { key: [...modsOf(e), name].join("+") });
  }, true);
  window.addEventListener("keyup", (e) => {
    if (!recording) return;
    e.preventDefault();
    const name = codeName(e.code);
    if (name && name === pendingMod && browserRecords()) send("record", { key: [...modsOf(e, name), name].join("+") });
    pendingMod = null;
  }, true);
  window.addEventListener("mousedown", (e) => {
    if (!recording || e.button === 0 || e.button === 2) return;
    e.preventDefault();
    const name = { 1: "mouse3", 3: "mouse4", 4: "mouse5" }[e.button];
    if (name && browserRecords()) send("record", { key: [...modsOf(e), name].join("+") });
  }, true);

  window.addEventListener("pagehide", () => api.bye());
  if (!token && !window.AC_MOCK) {
    $("#offline").hidden = false;
    $("#offline-text").textContent = "Code fehlt. Öffne die Seite über den QR-Code am PC (Einstellungen → Handy).";
  }
  poll();
})();
