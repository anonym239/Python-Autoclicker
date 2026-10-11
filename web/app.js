/* AutoClicker v6 – Oberflaeche (PC-Fenster und Handy-Fernbedienung). */
(() => {
  "use strict";

  const $ = (s) => document.querySelector(s);
  const $$ = (s) => Array.from(document.querySelectorAll(s));
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* egal */ } },
  };

  // ─── Verbindung ─────────────────────────────────────────
  const params = new URLSearchParams(location.search);
  let token = params.get("t") || store.get("ac_token") || "";
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
    if (res.status === 403) { const e = new Error("token"); e.code = 403; throw e; }
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

  // ─── Zustand ────────────────────────────────────────────
  let rev = -1;
  let C = null;      // Konfiguration
  let INFO = null;   // Programm-Infos
  let E = null;      // Engine-Live-Status
  let recording = null;
  let lastNotice = 0;
  let fails = 0;
  let lastArmed = null;
  const editing = new Map();

  const fmt = new Intl.NumberFormat("de-DE");
  const fmt1 = new Intl.NumberFormat("de-DE", { maximumFractionDigits: 1 });
  const num = (v, d = 1) => new Intl.NumberFormat("de-DE", { maximumFractionDigits: d }).format(v);

  const KEY_LABELS = {
    ctrl: "Strg", shift: "Shift", alt: "Alt", win: "Win", space: "Leertaste", enter: "Enter",
    esc: "Esc", backspace: "⌫", tab: "Tab", capslock: "Caps", pageup: "Bild↑", pagedown: "Bild↓",
    home: "Pos1", end: "Ende", insert: "Einfg", delete: "Entf", up: "↑", down: "↓", left: "←",
    right: "→", printscreen: "Druck", pause: "Pause", scrolllock: "Rollen", numlock: "Num",
    menu: "Menü", mouse3: "Maus 3", mouse4: "Maus 4", mouse5: "Maus 5", num_add: "Num +",
    num_sub: "Num −", num_mul: "Num ×", num_div: "Num ÷", num_dec: "Num ,", semicolon: "Ü",
    plus: "+", comma: ",", minus: "-", period: ".", slash: "#", backtick: "Ö", bracketleft: "ß",
    backslash: "^", bracketright: "´", quote: "Ä", oem102: "<",
  };
  function keyLabel(hk) {
    if (!hk) return "—";
    return hk.split("+").map((p) => KEY_LABELS[p] || (/^num\d$/.test(p) ? "Num " + p.slice(3) : p.toUpperCase())).join(" + ");
  }

  const BUTTON_NAMES = { left: "Links", right: "Rechts", middle: "Mitte" };
  const BUTTON_NAMES_LONG = { left: "linke", right: "rechte", middle: "mittlere" };
  const MODE_NAMES = { toggle: "Umschalten", hold_mouse: "Maus halten", hold_key: "Taste halten" };

  // ─── Hilfen ─────────────────────────────────────────────
  function markEdit(el) { editing.set(el.id, Date.now()); }
  function canSet(el) {
    return document.activeElement !== el && Date.now() - (editing.get(el.id) || 0) > 1500;
  }
  function setVal(el, v) { if (canSet(el) && String(el.value) !== String(v)) el.value = v; }
  function setChecked(el, v) { if (canSet(el)) el.checked = !!v; }
  function pressed(container, val) {
    $$(container + " [data-val]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.val === val)));
  }
  function debounce(fn, ms) {
    let t = null;
    return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
  }
  let toastTimer = null;
  function toast(text) {
    const el = $("#toast");
    el.textContent = text;
    el.hidden = false;
    el.style.animation = "none"; void el.offsetWidth; el.style.animation = "";
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.hidden = true; }, 2600);
  }
  function clockTime(s) {
    s = Math.floor(s || 0);
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
    return h ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}` : `${m}:${String(sec).padStart(2, "0")}`;
  }
  function compact(n) {
    if (n >= 1e6) return num(n / 1e6, 1) + " Mio";
    if (n >= 1e5) return num(n / 1e3, 0) + "k";
    return fmt.format(n);
  }

  async function send(name, body) {
    try {
      const st = await api.post(name, body);
      if (st && st.rev !== undefined) apply(st);
      return st;
    } catch (e) {
      toast(e.code === 403 ? "Code ungültig – QR-Code neu scannen" : (e.message || "Fehler"));
      return null;
    }
  }

  // ─── Pixel-Hintergrund (Deepslate) ──────────────────────
  (function texture() {
    try {
      const c = document.createElement("canvas");
      c.width = c.height = 16;
      const g = c.getContext("2d");
      let seed = 7;
      const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
      for (let y = 0; y < 16; y++) {
        for (let x = 0; x < 16; x++) {
          const v = rnd();
          const l = v < 0.08 ? 15 : v < 0.55 ? 21 : v < 0.93 ? 23 : 27;
          g.fillStyle = `rgb(${l - 1},${l + 1},${l + 6})`;
          g.fillRect(x, y, 1, 1);
        }
      }
      document.documentElement.style.setProperty("--tex", `url(${c.toDataURL()})`);
      document.body.style.imageRendering = "pixelated";
    } catch (e) { /* Hintergrund ist optional */ }
  })();

  const savedMat = store.get("ac_material");
  if (savedMat) document.documentElement.dataset.material = savedMat;

  // ─── Rendern: Konfiguration ─────────────────────────────
  function renderConfig() {
    const p = C.profile;
    document.documentElement.dataset.material = C.app.theme;
    store.set("ac_material", C.app.theme);
    document.body.classList.toggle("is-remote", !!INFO.remote_client);

    // Profile
    const box = $("#profiles");
    const names = C.profiles.join("\u0000");
    if (box.dataset.names !== names) {
      box.dataset.names = names;
      box.textContent = "";
      C.profiles.forEach((n) => {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "pchip";
        b.setAttribute("role", "tab");
        b.textContent = n;
        b.addEventListener("click", () => send("profile", { op: "select", name: n }));
        box.appendChild(b);
      });
    }
    $$("#profiles .pchip").forEach((b) => b.setAttribute("aria-selected", String(b.textContent === C.active)));
    const active = $("#profiles .pchip[aria-selected='true']");
    if (active && box.dataset.active !== C.active) {
      box.dataset.active = C.active;  // nur die Chip-Leiste scrollen, nie die Seite
      const left = active.offsetLeft - box.offsetLeft;
      if (left < box.scrollLeft || left + active.offsetWidth > box.scrollLeft + box.clientWidth) {
        box.scrollLeft = Math.max(0, left - 12);
      }
    }

    pressed("#button-seg", p.button);
    pressed("#mode-seg", p.mode);
    pressed("#action-seg", p.action);
    const holdAllowed = p.mode === "toggle";
    $("#act-hold").disabled = !holdAllowed;
    $("#action-note").textContent = holdAllowed
      ? "Dauerdrücken hält die Taste fest – ideal für AFK-Angeln oder Cobblestone abbauen."
      : "Dauerdrücken gibt es nur im Modus „Umschalten“.";
    const holding = p.action === "hold" && holdAllowed;
    $("#speed-group").style.opacity = holding ? ".4" : "";
    $("#speed-group").style.pointerEvents = holding ? "none" : "";

    renderSpeed(p);
    setVal($("#f-limit-s"), p.limit_seconds);
    setVal($("#f-limit-c"), p.limit_clicks);
    setVal($("#f-delay"), p.start_delay);
    setVal($("#f-hold"), p.hold_ms);
    setVal($("#f-pname"), p.name);

    // Hotkeys
    ["toggle", "stop", "next_profile"].forEach((slot) => {
      const el = $("#hk-" + slot);
      el.textContent = keyLabel(C.hotkeys[slot]);
      el.classList.toggle("empty", !C.hotkeys[slot]);
    });
    $("#hk-toggle-desc").textContent = p.mode === "hold_key"
      ? "Gedrückt halten = klicken (Modus „Taste halten“)"
      : "Schaltet den Klicker an und aus";
    $("#hooks-warn").hidden = !(INFO.backend === "windows" && !INFO.hooks_ok);

    // Smart
    setChecked($("#o-lock"), C.smart.window_lock);
    setVal($("#o-match"), C.smart.window_match);
    $("#o-match-wrap").style.opacity = C.smart.window_lock ? "" : ".5";
    setChecked($("#o-menus"), C.smart.pause_in_menus);
    setChecked($("#o-sound"), C.app.sound);
    setChecked($("#o-top"), C.app.always_on_top);
    $$("#materials [data-mat]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.mat === C.app.theme)));

    // Handy
    setChecked($("#o-remote"), C.app.remote);
    $("#remote-box").hidden = !C.app.remote;
    if (C.app.remote) {
      $("#remote-url").textContent = INFO.remote_url || "Keine Netzwerkverbindung gefunden";
      const src = api.qrUrl(rev);
      if ($("#qr").dataset.src !== src) { $("#qr").dataset.src = src; $("#qr").src = src; }
    }
    $("#remote-err").hidden = !INFO.remote_error;
    $("#remote-err").textContent = INFO.remote_error ? "WLAN-Freigabe fehlgeschlagen: " + INFO.remote_error : "";
  }

  function renderSpeed(p) {
    const vary = p.cps_max - p.cps_min > 1e-9;
    setChecked($("#vary"), vary);
    $("#range2").classList.toggle("single", !vary);
    $("#f-min-label").textContent = vary ? "Min CPS" : "CPS";
    $("#f-max-wrap").hidden = !vary;
    $("#f-ms-wrap").hidden = vary;
    setVal($("#f-min"), +p.cps_min.toFixed(2));
    setVal($("#f-max"), +p.cps_max.toFixed(2));
    setVal($("#f-ms"), +(1000 / p.cps_min).toFixed(1));
    const rMin = $("#r-min"), rMax = $("#r-max");
    if (canSet(rMin)) rMin.value = Math.min(30, p.cps_min);
    if (canSet(rMax)) rMax.value = Math.min(30, p.cps_max);
    paintRange();
    $("#speed-note").textContent = vary
      ? `= ${num(1000 / p.cps_max)}–${num(1000 / p.cps_min)} ms pro Klick · zufällig`
      : `= ${num(1000 / p.cps_min)} ms pro Klick`;
    $$("#presets [data-cps]").forEach((b) => b.classList.toggle("on", !vary && Math.abs(+b.dataset.cps - p.cps_min) < 1e-6));
  }

  function paintRange() {
    const lo = +$("#r-min").value, hi = +$("#r-max").value;
    const vary = !$("#range2").classList.contains("single");
    const pct = (v) => ((v - 1) / 29) * 100;
    const fill = $("#range2-fill");
    fill.style.left = (vary ? pct(Math.min(lo, hi)) : 0) + "%";
    fill.style.right = (100 - pct(vary ? Math.max(lo, hi) : hi)) + "%";
  }

  // ─── Rendern: Live ──────────────────────────────────────
  const STATE_TEXT = { idle: "AUS", ready: "BEREIT", clicking: "KLICKT", paused: "PAUSE", countdown: "START" };

  function renderLive() {
    if (!E || !C) return;
    const p = C.profile;
    const hud = $(".hud");
    const st = E.state;
    hud.dataset.s = st;
    const pill = $("#pill");
    pill.dataset.s = st;
    pill.textContent = st === "clicking" && E.holding ? "HÄLT" : STATE_TEXT[st] || st.toUpperCase();
    $("#hud-mode").textContent = `${BUTTON_NAMES[p.button]} · ${MODE_NAMES[p.mode]}${p.action === "hold" && p.mode === "toggle" ? " · Dauerdrücken" : ""}`;

    $("#cps").textContent = fmt1.format(E.cps);
    const vary = p.cps_max - p.cps_min > 1e-9;
    $("#cps-target").textContent = p.action === "hold" && p.mode === "toggle"
      ? "Taste wird gehalten statt geklickt"
      : `Ziel ${vary ? num(p.cps_min) + "–" + num(p.cps_max) : num(p.cps_min)} CPS`;

    const cd = $("#countdown");
    cd.hidden = E.countdown === null || E.countdown === undefined;
    if (!cd.hidden) $("#countdown-num").textContent = Math.max(1, Math.ceil(E.countdown));

    // XP-Leiste: Auto-Stopp-Fortschritt oder Level
    const xp = $("#xp");
    if (E.limit_progress !== null && E.limit_progress !== undefined) {
      xp.classList.add("limit");
      $("#xp-level").textContent = Math.round(E.limit_progress * 100) + "%";
      $("#xp-fill").style.width = (E.limit_progress * 100).toFixed(1) + "%";
      const parts = [];
      if (p.limit_clicks > 0) parts.push(`${fmt.format(E.run_clicks)} / ${fmt.format(p.limit_clicks)} Klicks`);
      if (p.limit_seconds > 0) parts.push(`${clockTime(E.run_time)} / ${clockTime(p.limit_seconds)}`);
      $("#xp-caption").textContent = "Auto-Stopp · " + parts.join(" · ");
    } else {
      xp.classList.remove("limit");
      const life = E.lifetime_clicks;
      const lvl = Math.floor(Math.sqrt(life / 100));
      const a = 100 * lvl * lvl, b = 100 * (lvl + 1) * (lvl + 1);
      $("#xp-level").textContent = lvl;
      $("#xp-fill").style.width = (((life - a) / (b - a)) * 100).toFixed(1) + "%";
      $("#xp-caption").textContent = `Level ${lvl} · ${fmt.format(life)} / ${fmt.format(b)} Klicks`;
    }

    $("#st-session").textContent = compact(E.session_clicks);
    $("#st-best").textContent = fmt1.format(E.best_cps);
    $("#st-time").textContent = clockTime(E.run_time);
    $("#st-life").textContent = compact(E.lifetime_clicks);

    // Grosser Knopf
    const mega = $("#mega");
    const hk = keyLabel(C.hotkeys.toggle);
    mega.classList.remove("stop", "wait");
    mega.disabled = false;
    $("#mega-key").hidden = !C.hotkeys.toggle;
    $("#mega-key").textContent = hk;
    let hint;
    if (p.mode === "hold_key") {
      mega.disabled = true;
      $("#mega-label").textContent = st === "clicking" ? "KLICKT" : "HALTEN";
      hint = C.hotkeys.toggle ? `Halte ${hk} gedrückt, um zu klicken.` : "Lege im Tab Hotkeys eine Taste fest.";
    } else if (st === "countdown") {
      mega.classList.add("wait");
      $("#mega-label").textContent = "ABBRUCH";
      hint = "Jetzt mit der Maus ins Spiel wechseln.";
    } else if (E.armed) {
      mega.classList.add("stop");
      $("#mega-label").textContent = "STOPP";
      hint = {
        ready: p.mode === "hold_mouse" ? `Bereit – halte im Spiel die ${BUTTON_NAMES_LONG[p.button]} Maustaste.` : "Bereit.",
        clicking: E.holding ? "Taste wird gedrückt gehalten." : "Klickt an der aktuellen Mausposition.",
        paused: {
          window: "Pause – Minecraft ist nicht im Vordergrund.",
          menu: "Pause – Inventar, Chat oder Menü ist offen.",
          self: "Pause – klickt nicht ins AutoClicker-Fenster.",
        }[E.reason] || "Pause.",
      }[st] || "";
    } else {
      $("#mega-label").textContent = "START";
      hint = C.hotkeys.toggle
        ? `${hk} drücken – auch während Minecraft im Vordergrund ist.`
        : "Start per Knopf: 3 s Countdown.";
      if (E.stop_reason === "limit") hint = "Auto-Stopp erreicht.";
    }
    $("#hud-hint").textContent = hint;

    drawGraph();

    // Aufnahme-Dialog
    const modal = $("#rec-modal");
    const was = !modal.hidden;
    modal.hidden = !recording;
    if (recording && !was) {
      const f = $("#rec-timer-fill");
      f.style.transition = "none"; f.style.transform = "scaleX(1)"; void f.offsetWidth;
      f.style.transition = "transform 15s linear"; f.style.transform = "scaleX(0)";
    }

    // Handy: Vibration + Bildschirm wach halten
    if (lastArmed !== null && lastArmed !== E.armed && INFO && INFO.remote_client && store.get("ac_vibrate") === "1") {
      try { navigator.vibrate && navigator.vibrate(E.armed ? [40, 60, 40] : 120); } catch (e) { /* egal */ }
    }
    lastArmed = E.armed;
    wakeLock(INFO && INFO.remote_client && (E.armed || st === "countdown"));
  }

  let lock = null;
  async function wakeLock(on) {
    try {
      if (on && !lock && navigator.wakeLock && !document.hidden) {
        lock = await navigator.wakeLock.request("screen");
        lock.addEventListener("release", () => { lock = null; });
      } else if (!on && lock) {
        await lock.release();
        lock = null;
      }
    } catch (e) { lock = null; }
  }

  // ─── CPS-Graph (Treppen-Linie, Pixel-Stil) ──────────────
  function drawGraph() {
    const cv = $("#graph");
    const w = cv.clientWidth, h = cv.clientHeight;
    if (!w || !h) return;
    const dpr = window.devicePixelRatio || 1;
    if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) {
      cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
    }
    const g = cv.getContext("2d");
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, w, h);
    const css = getComputedStyle(document.documentElement);
    const accent = css.getPropertyValue("--accent").trim() || "#7ccf4a";
    const hi = css.getPropertyValue("--hi").trim();
    const dim = css.getPropertyValue("--dim").trim();
    const data = E.history || [];
    const p = C.profile;
    const peak = Math.max(...data, 0);
    const clickMode = !(p.action === "hold" && p.mode === "toggle");
    let top = Math.max(5, clickMode ? p.cps_max * 1.25 : 0, peak * 1.1);
    const step = niceStep(top / 3);
    top = Math.ceil(top / step) * step;
    const padL = 26, padB = 4, padT = 4;
    const iw = w - padL, ih = h - padB - padT;
    const y = (v) => padT + ih - (v / top) * ih;

    g.font = "11px 'Jersey 15', monospace";
    g.textBaseline = "middle";
    g.lineWidth = 1;
    for (let v = 0; v <= top + 1e-9; v += step) {
      const yy = Math.round(y(v)) + 0.5;
      g.strokeStyle = hi; g.globalAlpha = 0.55;
      g.beginPath(); g.moveTo(padL, yy); g.lineTo(w, yy); g.stroke();
      g.globalAlpha = 1; g.fillStyle = dim;
      g.fillText(fmt.format(v), 0, Math.min(h - 6, Math.max(6, yy)));
    }
    if (clickMode) {  // Zielbereich
      g.fillStyle = accent; g.globalAlpha = 0.1;
      const y1 = y(Math.min(top, p.cps_max)), y2 = y(Math.min(top, p.cps_min));
      g.fillRect(padL, y1 - (y2 - y1 < 2 ? 1 : 0), iw, Math.max(2, y2 - y1));
      g.globalAlpha = 1;
    }
    if (!data.length) return;
    const n = data.length, bw = iw / n;
    g.beginPath();
    g.moveTo(padL, y(0));
    data.forEach((v, i) => { g.lineTo(padL + i * bw, y(v)); g.lineTo(padL + (i + 1) * bw, y(v)); });
    g.lineTo(padL + iw, y(0));
    g.closePath();
    g.fillStyle = accent; g.globalAlpha = 0.22; g.fill(); g.globalAlpha = 1;
    g.beginPath();
    data.forEach((v, i) => {
      const x0 = padL + i * bw, yy = Math.round(y(v)) + 0.5;
      if (i === 0) g.moveTo(x0, yy); else g.lineTo(x0, yy);
      g.lineTo(x0 + bw, yy);
    });
    g.strokeStyle = accent; g.lineWidth = 2; g.stroke();
    const last = data[n - 1];
    g.fillStyle = accent;
    g.fillRect(padL + iw - 5, Math.round(y(last)) - 3, 5, 6);
  }
  function niceStep(raw) {
    const p = Math.pow(10, Math.floor(Math.log10(Math.max(raw, 1e-6))));
    const m = raw / p;
    return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 5 ? 5 : 10) * p;
  }

  // ─── Daten anwenden & Abfrage-Schleife ──────────────────
  function apply(st) {
    if (st.config) {
      C = st.config;
      INFO = st.info;
      rev = st.rev;
      renderConfig();
    }
    E = st.engine;
    recording = st.recording;
    if (st.notice && st.notice.id !== lastNotice) {
      lastNotice = st.notice.id;
      toast(st.notice.text);
    }
    renderLive();
  }

  function online(ok, why) {
    const conn = $("#conn");
    conn.classList.toggle("ok", ok);
    conn.classList.toggle("bad", !ok);
    $("#conn-text").textContent = ok
      ? (INFO && INFO.remote_client ? "Mit PC verbunden" : INFO && INFO.backend === "demo" ? "Demo · Klicks simuliert" : "Hotkeys aktiv")
      : "Getrennt";
    if (INFO && INFO.backend === "windows" && !INFO.hooks_ok && ok) $("#conn-text").textContent = "Ohne Hotkeys";
    $("#offline").hidden = ok || fails < 3;
    if (why) $("#offline-text").textContent = why;
  }

  async function poll() {
    try {
      const st = await api.state(rev);
      fails = 0;
      apply(st);
      online(true);
    } catch (e) {
      fails++;
      online(false, e.code === 403
        ? "Der Code ist ungültig. Scanne den QR-Code im Tab „Handy“ am PC neu."
        : "Läuft das Programm auf dem PC noch? Neuer Versuch läuft …");
    }
    const remote = INFO && INFO.remote_client;
    setTimeout(poll, document.hidden ? 1000 : remote ? 350 : 200);
  }

  // ─── Eingaben ───────────────────────────────────────────
  const sendProfile = (() => {
    let patch = {};
    const flush = debounce(() => { const p = patch; patch = {}; send("settings", { profile: p }); }, 220);
    return (part) => {
      Object.assign(patch, part);
      if (C) { Object.assign(C.profile, part); renderConfig(); renderLive(); }
      flush();
    };
  })();

  function bindSeg(sel, key) {
    $$(sel + " [data-val]").forEach((b) => b.addEventListener("click", () => {
      if (b.disabled) return;
      const part = { [key]: b.dataset.val };
      if (key === "mode" && b.dataset.val !== "toggle" && C && C.profile.action === "hold") part.action = "click";
      sendProfile(part);
    }));
  }
  bindSeg("#button-seg", "button");
  bindSeg("#mode-seg", "mode");
  bindSeg("#action-seg", "action");

  function clampCps(v) { return Math.min(1000, Math.max(0.1, Math.round(v * 100) / 100)); }
  function round05(v) { return Math.max(0.5, Math.round(v * 2) / 2); }

  $("#vary").addEventListener("change", (e) => {
    markEdit(e.target);
    const p = C.profile;
    if (e.target.checked) {
      const c = p.cps_min;
      sendProfile({ cps_min: clampCps(round05(c * 0.85)), cps_max: clampCps(round05(c * 1.15) + (c < 4 ? 1 : 0)) });
    } else {
      const mid = clampCps(Math.round(((p.cps_min + p.cps_max) / 2) * 10) / 10);
      sendProfile({ cps_min: mid, cps_max: mid });
    }
  });

  ["#r-min", "#r-max"].forEach((sel) => $(sel).addEventListener("input", (e) => {
    markEdit(e.target);
    let lo = +$("#r-min").value, hi = +$("#r-max").value;
    const single = $("#range2").classList.contains("single");
    if (single) { lo = hi; }
    else if (lo > hi) { if (sel === "#r-min") hi = lo; else lo = hi; }
    $("#r-min").value = lo; $("#r-max").value = hi;
    paintRange();
    sendProfile({ cps_min: lo, cps_max: hi });
  }));

  function numberInput(sel, handler) {
    const el = $(sel);
    const go = () => { const v = parseFloat(String(el.value).replace(",", ".")); if (!isNaN(v)) handler(v); };
    el.addEventListener("input", () => { markEdit(el); debounceMap(sel, go); });
    el.addEventListener("change", () => { markEdit(el); go(); });
  }
  const timers = {};
  function debounceMap(key, fn) { clearTimeout(timers[key]); timers[key] = setTimeout(fn, 500); }

  numberInput("#f-min", (v) => {
    v = clampCps(v);
    const vary = $("#vary").checked;
    if (!vary) sendProfile({ cps_min: v, cps_max: v });
    else sendProfile({ cps_min: v, cps_max: Math.max(v, C.profile.cps_max) });
  });
  numberInput("#f-max", (v) => { v = clampCps(v); sendProfile({ cps_max: v, cps_min: Math.min(v, C.profile.cps_min) }); });
  numberInput("#f-ms", (v) => { if (v > 0) { const c = clampCps(1000 / v); sendProfile({ cps_min: c, cps_max: c }); } });
  numberInput("#f-limit-s", (v) => sendProfile({ limit_seconds: Math.max(0, v) }));
  numberInput("#f-limit-c", (v) => sendProfile({ limit_clicks: Math.max(0, Math.round(v)) }));
  numberInput("#f-delay", (v) => sendProfile({ start_delay: Math.max(0, Math.min(60, v)) }));
  numberInput("#f-hold", (v) => sendProfile({ hold_ms: Math.max(0, Math.min(500, v)) }));

  $$("#presets [data-cps]").forEach((b) => b.addEventListener("click", () => {
    const c = +b.dataset.cps;
    if ($("#vary").checked && c >= 4) sendProfile({ cps_min: clampCps(round05(c * 0.85)), cps_max: clampCps(round05(c * 1.15)) });
    else sendProfile({ cps_min: c, cps_max: c });
  }));

  // Profile verwalten
  $("#f-pname").addEventListener("change", (e) => {
    markEdit(e.target);
    const v = e.target.value.trim();
    if (v && C && v !== C.profile.name) send("profile", { op: "rename", name: C.active, new_name: v });
  });
  $("#f-pname").addEventListener("keydown", (e) => { if (e.key === "Enter") e.target.blur(); });
  $("#p-dup").addEventListener("click", () => send("profile", { op: "duplicate" }));
  $("#p-new").addEventListener("click", () => send("profile", { op: "create", new_name: "Profil" }));
  let delArmed = 0;
  $("#p-del").addEventListener("click", () => {
    const btn = $("#p-del");
    if (Date.now() - delArmed < 3000) {
      delArmed = 0; btn.classList.remove("armed"); $("#p-del-confirm").hidden = true;
      send("profile", { op: "delete", name: C.active });
    } else {
      delArmed = Date.now(); btn.classList.add("armed"); $("#p-del-confirm").hidden = false;
      setTimeout(() => { if (Date.now() - delArmed >= 2900) { btn.classList.remove("armed"); $("#p-del-confirm").hidden = true; } }, 3050);
    }
  });

  // Smart / App
  const sendSmart = (part) => { if (C) Object.assign(C.smart, part); send("settings", { smart: part }); };
  const sendApp = (part) => { if (C) Object.assign(C.app, part); send("settings", { app: part }); };
  $("#o-lock").addEventListener("change", (e) => { markEdit(e.target); sendSmart({ window_lock: e.target.checked }); });
  $("#o-match").addEventListener("change", (e) => { markEdit(e.target); sendSmart({ window_match: e.target.value }); });
  $("#o-menus").addEventListener("change", (e) => { markEdit(e.target); sendSmart({ pause_in_menus: e.target.checked }); });
  $("#o-sound").addEventListener("change", (e) => { markEdit(e.target); sendApp({ sound: e.target.checked }); });
  $("#o-top").addEventListener("change", (e) => { markEdit(e.target); sendApp({ always_on_top: e.target.checked }); });
  $$("#materials [data-mat]").forEach((b) => b.addEventListener("click", () => {
    document.documentElement.dataset.material = b.dataset.mat;
    store.set("ac_material", b.dataset.mat);
    sendApp({ theme: b.dataset.mat });
  }));

  // Handy
  $("#o-remote").addEventListener("change", (e) => { markEdit(e.target); send("remote", { enabled: e.target.checked }); });
  $("#new-token").addEventListener("click", () => send("remote", { new_token: true }));
  $("#copy-url").addEventListener("click", async () => {
    const text = $("#remote-url").textContent;
    try { await navigator.clipboard.writeText(text); toast("Adresse kopiert"); }
    catch (e) {
      const r = document.createRange(); r.selectNodeContents($("#remote-url"));
      const s = getSelection(); s.removeAllRanges(); s.addRange(r);
      toast("Markiert – jetzt Strg+C");
    }
  });
  $("#o-vibrate").checked = store.get("ac_vibrate") === "1";
  $("#o-vibrate").addEventListener("change", (e) => store.set("ac_vibrate", e.target.checked ? "1" : "0"));

  // Start / Stopp / Statistik
  $("#mega").addEventListener("click", () => send("action", { do: "toggle" }));
  $("#reset-stats").addEventListener("click", async () => {
    await send("action", { do: "reset_stats" });
    toast("Statistik zurückgesetzt");
  });

  // Tabs
  function showTab(name) {
    $$(".tab").forEach((t) => t.setAttribute("aria-selected", String(t.dataset.tab === name)));
    $$(".tab-body").forEach((b) => { b.hidden = b.dataset.body !== name; });
    store.set("ac_tab", name);
    if (name === "click") requestAnimationFrame(paintRange);
  }
  $$(".tab").forEach((t) => t.addEventListener("click", () => showTab(t.dataset.tab)));
  showTab(store.get("ac_tab") || "click");

  // ─── Hotkey-Aufnahme ────────────────────────────────────
  $$("[data-rec]").forEach((b) => b.addEventListener("click", () => send("record", { slot: b.dataset.rec })));
  $$("[data-clear]").forEach((b) => b.addEventListener("click", () => send("record", { slot: b.dataset.clear, key: "" })));
  $("#rec-cancel").addEventListener("click", () => send("record", { cancel: true }));

  const CODE_NAMES = {
    Space: "space", Enter: "enter", NumpadEnter: "enter", Tab: "tab", Backspace: "backspace",
    Home: "home", End: "end", PageUp: "pageup", PageDown: "pagedown", Insert: "insert",
    Delete: "delete", ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right",
    CapsLock: "capslock", Pause: "pause", ScrollLock: "scrolllock", NumLock: "numlock",
    PrintScreen: "printscreen", ContextMenu: "menu", NumpadAdd: "num_add", NumpadSubtract: "num_sub",
    NumpadMultiply: "num_mul", NumpadDivide: "num_div", NumpadDecimal: "num_dec",
    ShiftLeft: "shift", ShiftRight: "shift", ControlLeft: "ctrl", ControlRight: "ctrl",
    AltLeft: "alt", AltRight: "alt", MetaLeft: "win", MetaRight: "win", Semicolon: "semicolon",
    Equal: "plus", Comma: "comma", Minus: "minus", Period: "period", Slash: "slash",
    Backquote: "backtick", BracketLeft: "bracketleft", Backslash: "backslash",
    BracketRight: "bracketright", Quote: "quote", IntlBackslash: "oem102",
  };
  function codeName(code) {
    if (/^F\d{1,2}$/.test(code)) return code.toLowerCase();
    if (/^Key[A-Z]$/.test(code)) return code.slice(3).toLowerCase();
    if (/^Digit\d$/.test(code)) return code.slice(5);
    if (/^Numpad\d$/.test(code)) return "num" + code.slice(6);
    return CODE_NAMES[code] || null;
  }
  const MODS = ["ctrl", "shift", "alt", "win"];
  function modsOf(e, except) {
    const m = [];
    if (e.ctrlKey) m.push("ctrl");
    if (e.shiftKey) m.push("shift");
    if (e.altKey) m.push("alt");
    if (e.metaKey) m.push("win");
    return m.filter((x) => x !== except);
  }
  // Ohne globale Hooks (Demo) nimmt der Browser die Taste auf; unter Windows macht das der Hook.
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
    if (browserRecords()) send("record", { slot: recording, key: [...modsOf(e), name].join("+") });
  }, true);
  window.addEventListener("keyup", (e) => {
    if (!recording) return;
    e.preventDefault();
    const name = codeName(e.code);
    if (name && name === pendingMod && browserRecords()) {
      send("record", { slot: recording, key: [...modsOf(e, name), name].join("+") });
    }
    pendingMod = null;
  }, true);
  window.addEventListener("mousedown", (e) => {
    if (!recording || e.button === 0 || e.button === 2) return;
    e.preventDefault();
    const name = { 1: "mouse3", 3: "mouse4", 4: "mouse5" }[e.button];
    if (name && browserRecords()) send("record", { slot: recording, key: [...modsOf(e), name].join("+") });
  }, true);
  window.addEventListener("contextmenu", (e) => { if (recording) e.preventDefault(); });
  window.addEventListener("resize", () => { if (E && C) { drawGraph(); paintRange(); } });

  // Fenster geschlossen -> Programm beenden (nur das PC-Fenster)
  window.addEventListener("pagehide", () => api.bye());

  if (!token && !window.AC_MOCK) {
    $("#offline").hidden = false;
    $("#offline-text").textContent = "Code fehlt. Öffne die Seite über den QR-Code im Tab „Handy“ am PC.";
  }
  poll();
})();
