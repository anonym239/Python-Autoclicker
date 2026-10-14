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
    if (!res.ok) { const e = new Error(data.error || "e_generic"); e.code = res.status; throw e; }
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

  // ─── Sprache ────────────────────────────────────────────
  const LANGS = window.AC_LANGS || [["de", "Deutsch"]];
  const TEXTS = window.AC_I18N || {};
  let lang = "de", locale = "de-DE";
  function pickLang(setting) {
    if (TEXTS[setting]) return setting;
    const ALIAS = { no: "nb", nn: "nb" };
    const sys = (navigator.languages || [navigator.language || ""]).map((l) => String(l).slice(0, 2).toLowerCase()).map((l) => ALIAS[l] || l);
    return sys.find((l) => TEXTS[l]) || "en";
  }
  // t("hint_idle", { key: "F6" }) – fehlt ein Text, gilt Englisch, dann Deutsch, dann der Schluessel selbst
  // Nicht-Minecraft-Spiel gewaehlt: neutrale Texte ("PvP" statt "Minecraft PvP") – Schluessel + "_g"
  let neutral = false;
  const pick = (k) => (TEXTS[lang] || {})[k] ?? (TEXTS.en || {})[k] ?? (TEXTS.de || {})[k];
  function t(key, vars) {
    const raw = (neutral && pick(key + "_g")) || (pick(key) ?? key);
    return vars ? raw.replace(/\{(\w+)\}/g, (m, k) => (vars[k] ?? m)) : raw;
  }
  function applyTexts() {
    $$("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
    $$("[data-i18n-aria]").forEach((el) => el.setAttribute("aria-label", t(el.dataset.i18nAria)));
    $$("[data-i18n-title]").forEach((el) => { el.title = t(el.dataset.i18nTitle); });
    $$("[data-i18n-ph]").forEach((el) => { el.placeholder = t(el.dataset.i18nPh); });
  }
  let langReady = false;
  function setLang(setting) {
    const next = pickLang(setting);
    store.set("ac_lang", setting);
    if (langReady && next === lang) return false;
    langReady = true;
    lang = next;
    locale = { de: "de-DE", en: "en-US", pt: "pt-BR", zh: "zh-CN" }[lang] || lang;
    document.documentElement.lang = lang;
    applyTexts();
    const sel = $("#o-lang");
    sel.textContent = "";
    [["auto", t("lang_auto")], ...LANGS].forEach(([val, label]) => {
      const o = document.createElement("option");
      o.value = val; o.textContent = label;
      sel.appendChild(o);
    });
    sel.value = setting;
    return true;
  }

  // ─── Texte ──────────────────────────────────────────────
  const STATUS = { idle: "st_idle", ready: "st_ready", clicking: "st_clicking", paused: "st_paused" };
  const ACTIONS = { toggle: "a_toggle", on: "a_on", off: "a_off" };
  const KEY_LABELS = {
    shift: "Shift", alt: "Alt", win: "Win", enter: "Enter", esc: "Esc",
    backspace: "⌫", tab: "Tab", capslock: "Caps", up: "↑", down: "↓", left: "←", right: "→",
    pause: "Pause", numlock: "Num", num_add: "Num +", num_sub: "Num −",
    num_mul: "Num ×", num_div: "Num ÷", num_dec: "Num ,", semicolon: "Ü", plus: "+", comma: ",",
    minus: "-", period: ".", slash: "#", backtick: "Ö", bracketleft: "ß", backslash: "^",
    bracketright: "´", quote: "Ä", oem102: "<",
  };
  // Tasten, deren Namen uebersetzt werden (k_… in i18n.js)
  const KEY_TEXTS = { ctrl: "k_ctrl", space: "k_space", home: "k_home", end: "k_end", insert: "k_insert",
    delete: "k_delete", pageup: "k_pageup", pagedown: "k_pagedown", printscreen: "k_print",
    scrolllock: "k_scroll", menu: "k_menu" };
  const keyPart = (p) => KEY_TEXTS[p] ? t(KEY_TEXTS[p])
    : lang !== "de" && US_KEYS[p] ? US_KEYS[p]
    : /^mouse\d$/.test(p) ? `${t("k_mouse")} ${p.slice(5)}`
    : KEY_LABELS[p] || (/^num\d$/.test(p) ? "Num " + p.slice(3) : p.toUpperCase());
  // Satzzeichen-Tasten: deutsches Layout bei deutscher Oberflaeche, sonst US-Layout
  const US_KEYS = { semicolon: ";", slash: "/", backtick: "`", bracketleft: "[", backslash: "\\", bracketright: "]", quote: "'", oem102: "\\" };
  const keyLabel = (hk) => !hk ? "—" : hk.split("+").map(keyPart).join(" + ");
  const nf = (v, d = 1) => new Intl.NumberFormat(locale, { maximumFractionDigits: d }).format(v);
  const clock = (s) => {
    s = Math.floor(s || 0);
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
    return h ? `${h}:${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}` : `${m}:${String(r).padStart(2, "0")}`;
  };

  const delayText = (v) => v > 0 ? t("seconds_short", { n: v }) : t("off");

  // ─── Zustand ────────────────────────────────────────────
  let rev = -1, C = null, INFO = null, E = null, recording = null, learning = false, toolIndex = -1, learnError = "", stopKey = "";
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
      toast(t(e.message || "e_generic"));
      return null;
    }
  }

  function applyTheme(theme) {
    if (theme === "light" || theme === "dark") document.documentElement.dataset.theme = theme;
    else delete document.documentElement.dataset.theme;
    store.set("ac_theme", theme);
  }
  applyTheme(store.get("ac_theme") || "system");
  setLang(store.get("ac_lang") || "auto");

  // ─── Anzeigen: Einstellungen ────────────────────────────
  function renderConfig() {
    const g = C.general, cur = C.current, mode = C.mode;
    applyTheme(g.theme);
    const wasNeutral = neutral;
    neutral = !!g.game && g.game !== "minecraft";
    if (setLang(g.language || "auto")) renderTour();
    else if (neutral !== wasNeutral) { applyTexts(); renderTour(); }
    $("#mode-label").textContent = t("mode") + (g.game ? " · " + gameName(g.game) : "");
    if (canSet($("#o-lang"))) $("#o-lang").value = g.language || "auto";
    $$(".preset").forEach((b) => b.setAttribute("aria-current", String(!homeOpen && b.dataset.id === C.preset)));
    $("#title").textContent = t("p_" + C.preset);
    $("#desc").textContent = t("desc_" + C.preset);

    const holdMode = C.preset === "afk" && cur.action === "hold";
    $("#row-action").hidden = C.preset !== "afk";
    pressed("#action-seg", cur.action || "click");
    $("#row-speed").hidden = mode === "boost" || holdMode;
    $("#row-boost").hidden = mode !== "boost";
    if (canSet($("#speed"))) $("#speed").value = Math.min(30, cur.cps);
    setVal($("#speed-num"), cur.cps);
    pressed("#boost-seg", cur.boost);
    pressed("#button-seg", cur.button);

    setVal($("#o-stop"), g.auto_stop);
    setVal($("#o-delay"), Math.round(g.start_delay));
    $("#o-delay-value").textContent = delayText(Math.round(g.start_delay));
    setChecked($("#o-vary"), g.vary);
    setChecked($("#o-lock"), g.window_lock);
    setVal($("#o-match"), g.window_match);
    $("#o-match-row").hidden = !g.window_lock;
    setChecked($("#o-top"), g.always_on_top);
    setChecked($("#o-sound"), g.sound);
    setChecked($("#o-learn"), g.learn_hotkey_on);
    $("#o-learn-row").hidden = !g.learn_hotkey_on || neutral;
    $$(".mc-only").forEach((el) => { el.hidden = neutral; });  // Werkzeuge gibt es nur in Minecraft
    pressed("#theme-seg", g.theme);
    $("#version").textContent = t("version", { v: INFO.version }) + (INFO.backend === "demo" ? " · Demo" : "");

    renderHotkeys();
    renderTools();
    renderHome();
    if (!homeChecked) {  // erster Start oder neue Version -> Home-Menue (Spiel waehlen)
      homeChecked = true;
      if (!g.game || g.home_version !== INFO.version || location.hash === "#home") {  // #home = zurueck von einer Webseite
        openHome();
        sendGeneral({ home_version: INFO.version });
      }
    }
    if (!tourShown && !g.tutorial_done && !homeOpen) { tourShown = true; openTour(); }
  }

  function renderHotkeys() {
    const sum = $("#hk-summary");
    sum.textContent = "";
    if (!C.hotkeys.length) {
      const none = document.createElement("span");
      none.className = "muted small";
      none.textContent = t("hk_none");
      sum.appendChild(none);
    }
    C.hotkeys.forEach((h) => {
      const chip = document.createElement("span");
      chip.className = "hk-chip";
      const k = document.createElement("kbd");
      k.textContent = keyLabel(h.key);
      chip.append(k, document.createTextNode(t(ACTIONS[h.action])));
      sum.appendChild(chip);
    });

    const list = $("#hk-list");
    list.textContent = "";
    if (!C.hotkeys.length) {
      const p = document.createElement("p");
      p.className = "hk-empty";
      p.textContent = t("hk_empty");
      list.appendChild(p);
    }
    C.hotkeys.forEach((h, i) => {
      const row = document.createElement("div");
      row.className = "hk-row";
      const key = document.createElement("button");
      key.type = "button";
      key.className = "keycap" + (recording === i ? " rec" : "");
      key.textContent = recording === i ? t("hk_press") : keyLabel(h.key);
      key.title = t("hk_change");
      key.addEventListener("click", () => send("hotkeys", recording === i ? { op: "cancel" } : { op: "record", index: i }));
      const sel = document.createElement("select");
      sel.setAttribute("aria-label", t("hk_what"));
      Object.entries(ACTIONS).forEach(([val, label]) => {
        const o = document.createElement("option");
        o.value = val; o.textContent = t(label); o.selected = val === h.action;
        sel.appendChild(o);
      });
      sel.addEventListener("change", () => send("hotkeys", { op: "action", index: i, action: sel.value }));
      const del = document.createElement("button");
      del.type = "button";
      del.className = "icon-btn";
      del.textContent = "✕";
      del.setAttribute("aria-label", t("hk_delete"));
      del.addEventListener("click", () => send("hotkeys", { op: "delete", index: i }));
      row.append(key, sel, del);
      list.appendChild(row);
    });
    const lk = $("#o-learn-key");
    lk.classList.toggle("rec", recording === "learn");
    lk.textContent = recording === "learn" ? t("hk_press") : keyLabel(C.general.learn_hotkey);
    const add = $("#hk-add");
    add.classList.toggle("rec", recording === "new");
    add.textContent = recording === "new" ? t("hk_add_rec") : t("hk_add");
  }

  // Werkzeuge (PvP / Boost): angelernte Hotbar-Plaetze mit Item-Bild
  const PICKAXE = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14.8 3.2c2.9-.4 5.3.3 6.6 1.4-2.2-.5-4.6-.3-6.5.4l1.5 1.5-1.4 1.4-1.4-1.4-9.9 9.9 1.4 1.4-1.4 1.4-2.8-2.8 1.4-1.4 1.4 1.4 9.9-9.9L12.2 4c.8-.4 1.7-.7 2.6-.8zM19 7.5c.7 1.9.9 4.3.4 6.5-1.1-1.3-1.8-3.7-1.4-6.6l1 .1z"/></svg>';
  function renderTools() {
    if (!C) return;
    const show = (C.mode === "hold_mouse" || C.mode === "boost") && !neutral;  // Hotbar gibt es nur in Minecraft
    $("#row-tools").hidden = !show;
    $("#row-kit").hidden = !show;
    const kitSel = $("#kit-select");
    kitSel.textContent = "";
    C.kits.forEach((k, i) => {
      const o = document.createElement("option");
      o.value = String(i);
      o.textContent = `${k.name} (${k.count})`;
      o.selected = i === C.kit;
      kitSel.appendChild(o);
    });
    const list = $("#tools-list");
    list.textContent = "";
    if (!C.tools.length) {
      const none = document.createElement("span");
      none.className = "muted small";
      none.textContent = t("tools_empty");
      list.appendChild(none);
    }
    C.tools.forEach((tool, i) => {
      const chip = document.createElement("span");
      chip.className = "tool-chip" + (i === toolIndex ? " on" : "");
      const icon = document.createElement("span");
      icon.className = "tool-icon" + (tool.photo ? " photo" : "");
      if (tool.photo || tool.icon) {
        const img = document.createElement("img");
        img.src = tool.photo || tool.icon; img.alt = "";
        icon.appendChild(img);
      } else {
        icon.innerHTML = PICKAXE;
      }
      const del = document.createElement("button");
      del.type = "button";
      del.className = "icon-btn";
      del.textContent = "✕";
      del.setAttribute("aria-label", t("tool_delete"));
      del.addEventListener("click", () => send("tools", { op: "delete", index: i }));
      chip.append(icon, del);
      list.appendChild(chip);
    });
    const btn = $("#tools-learn");
    btn.classList.toggle("rec", learning);
    btn.textContent = learning ? t("cancel") : t("tool_learn");
  }
  $("#tools-learn").addEventListener("click", () => send("tools", { op: learning ? "cancel" : "learn" }));
  $("#tools-list").addEventListener("wheel", (e) => {
    const el = e.currentTarget;
    if (el.scrollWidth > el.clientWidth && Math.abs(e.deltaY) > Math.abs(e.deltaX)) { el.scrollLeft += e.deltaY; e.preventDefault(); }
  }, { passive: false });
  // Kits: mehrere Werkzeug-Saetze (z. B. einer pro Server), jederzeit umschaltbar
  $("#kit-select").addEventListener("change", (e) => send("tools", { op: "kit_select", index: +e.target.value }));
  let kitMode = "";
  function openKitDialog(mode) {
    const kit = C.kits[C.kit];
    kitMode = mode;
    $("#kit-title").textContent = t(mode === "new" ? "kit_new" : mode === "rename" ? "kit_rename" : "kit_delete");
    const name = $("#kit-name");
    name.hidden = mode === "delete";
    name.value = mode === "rename" ? kit.name : "";
    name.placeholder = mode === "new" ? `Kit ${C.kits.length + 1}` : "";
    $("#kit-text").hidden = mode !== "delete";
    $("#kit-text").textContent = mode === "delete" ? t("kit_delete_q", { name: kit.name, n: kit.count }) : "";
    $("#kit-ok").textContent = t(mode === "delete" ? "kit_delete" : "kit_save");
    $("#kit-dialog").hidden = false;
    if (!name.hidden) setTimeout(() => name.focus(), 0);
  }
  $("#kit-new").addEventListener("click", () => openKitDialog("new"));
  $("#kit-rename").addEventListener("click", () => openKitDialog("rename"));
  $("#kit-delete").addEventListener("click", () => openKitDialog("delete"));
  $("#kit-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const name = $("#kit-name").value.trim();
    if (kitMode === "new") send("tools", { op: "kit_new", name });
    else if (kitMode === "rename") send("tools", { op: "kit_rename", index: C.kit, name });
    else if (kitMode === "delete") send("tools", { op: "kit_delete", index: C.kit });
    $("#kit-dialog").hidden = true;
  });
  // Werkzeuge als JSON-Datei sichern / aus einer Datei laden (auch eine ganze Einstellungsdatei geht)
  $("#tools-export").addEventListener("click", () => send("tools", { op: "export" }));
  $("#tools-import").addEventListener("click", () => $("#tools-file").click());
  $("#tools-file").addEventListener("change", (e) => {
    const file = e.target.files && e.target.files[0];
    e.target.value = "";
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      let data;
      try { data = JSON.parse(reader.result); } catch (err) { toast(t("e_import")); return; }
      send("tools", { op: "import", data });
    };
    reader.onerror = () => toast(t("e_import"));
    reader.readAsText(file);
  });

  // ─── Home-Menue ─────────────────────────────────────────
  // Spiele: Name, Bild, Farbe. Nur Minecraft hat Werkzeug-Erkennung und eigene Modus-Namen.
  // site = offizielle Seite -> deren echtes Icon (ohne Internet: das Emoji)
  const GAMES = {
    minecraft: { name: "Minecraft", icon: "⛏️", site: "minecraft.net", color: "#5d9c3a", sub: "game_sub_mc" },
    roblox: { name: "Roblox", icon: "🎮", site: "roblox.com", color: "#e2231a", sub: "game_sub" },
    terraria: { name: "Terraria", icon: "🌳", site: "terraria.org", color: "#3a7bd5", sub: "game_sub" },
    cookie: { name: "Cookie Clicker", icon: "🍪", site: "orteil.dashnet.org", color: "#b5763b", sub: "game_sub_cookie" },
    other: { name: "", icon: "🖱️", color: "#6b6b6b", sub: "game_sub" },
  };
  // Seiten-Icon in guter Aufloesung; klappt das nicht, das kleine Icon, sonst fallback()
  function siteIcon(host, fallback) {
    const img = document.createElement("img");
    img.alt = "";
    const urls = [`https://www.google.com/s2/favicons?domain=${encodeURIComponent(host)}&sz=64`,
      `https://icons.duckduckgo.com/ip3/${encodeURIComponent(host)}.ico`];
    img.onerror = () => { if (urls.length) img.src = urls.shift(); else { img.remove(); fallback(); } };
    img.src = urls.shift();
    return img;
  }
  const gameName = (id) => (id === "other" ? t("game_other") : (GAMES[id] || {}).name || id);
  let homeOpen = false, homeChecked = false;
  function openHome() {
    homeOpen = true;
    $("#app").classList.add("home-open");
    $("#home").hidden = false;
    $("#home-btn").setAttribute("aria-current", "true");
    $$(".preset").forEach((b) => b.setAttribute("aria-current", "false"));
  }
  function closeHome() {
    if (!homeOpen) return;
    homeOpen = false;
    $("#app").classList.remove("home-open");
    $("#home").hidden = true;
    $("#home-btn").setAttribute("aria-current", "false");
    if (!C) return;
    $$(".preset").forEach((b) => b.setAttribute("aria-current", String(b.dataset.id === C.preset)));
    if (!tourShown && !C.general.tutorial_done) { tourShown = true; openTour(); }
  }
  const hostOf = (url) => { try { return new URL(url).hostname.replace(/^www\./, ""); } catch (e) { return ""; } };
  const hue = (text) => [...text].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 7);
  function renderHome() {
    if (!C) return;
    const pins = $("#pins");
    pins.textContent = "";
    (C.pins || []).forEach((p, i) => {
      const b = document.createElement("button");
      b.type = "button"; b.className = "pin"; b.title = p.url || p.app;
      const icon = document.createElement("span");
      icon.className = "pin-icon";
      const letter = () => { icon.textContent = p.name.slice(0, 1).toUpperCase(); icon.style.background = `hsl(${hue(p.name)} 55% 45%)`; };
      const host = p.url ? hostOf(p.url) : "";
      if (host) icon.appendChild(siteIcon(host, letter));  // ohne Internet: Anfangsbuchstabe
      else letter();
      const name = document.createElement("span");
      name.className = "pin-name"; name.textContent = p.name;
      const del = document.createElement("span");
      del.className = "icon-btn"; del.textContent = "✕"; del.setAttribute("role", "button");
      del.title = t("pin_remove"); del.setAttribute("aria-label", t("pin_remove"));
      del.addEventListener("click", (e) => { e.stopPropagation(); send("home", { op: "pin_remove", index: i }); });
      b.append(icon, name, del);
      b.addEventListener("click", () => send("home", { op: "open", index: i }));
      pins.appendChild(b);
    });
    if ((C.pins || []).length < 12) {
      const add = document.createElement("button");
      add.type = "button"; add.className = "pin add";
      add.innerHTML = '<span class="pin-icon">+</span><span class="pin-name"></span>';
      add.lastChild.textContent = t("pin_add");
      add.addEventListener("click", openPinDialog);
      pins.appendChild(add);
    }
    // Angemeldet: Profilbild statt "Anmelden"
    const si = $("#signin"), pic = C.general.profile_pic || "";
    let av = si.querySelector("img.av");
    if (pic && !av) {
      av = document.createElement("img");
      av.className = "av"; av.alt = ""; av.referrerPolicy = "no-referrer";
      av.onerror = () => { av.remove(); si.classList.remove("avatar"); };
      si.prepend(av);
    }
    if (pic && av.getAttribute("src") !== pic) av.src = pic;
    if (!pic && av) av.remove();
    si.classList.toggle("avatar", !!pic);
    const games = $("#games");
    games.textContent = "";
    (C.games || Object.keys(GAMES)).forEach((id) => {
      const meta = GAMES[id] || GAMES.other;
      const b = document.createElement("button");
      b.type = "button"; b.className = "game";
      b.setAttribute("aria-pressed", String(C.general.game === id));
      b.innerHTML = '<span class="game-icon"></span><span><b></b><small></small></span>';
      const gi = b.querySelector(".game-icon");
      gi.style.background = meta.color + "33";
      const emoji = () => { gi.textContent = meta.icon; };
      if (meta.site) gi.appendChild(siteIcon(meta.site, emoji)); else emoji();
      b.querySelector("b").textContent = gameName(id);
      b.querySelector("small").textContent = t(meta.sub);
      b.addEventListener("click", () => {
        if (C.general.game !== id) sendGeneral({ game: id });
        closeHome();
      });
      games.appendChild(b);
    });
  }
  $("#home-btn").addEventListener("click", () => (homeOpen ? closeHome() : openHome()));
  $("#signin").addEventListener("click", () => send("home", { op: "signin" }));
  $("#search-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const text = $("#search").value.trim();
    if (text) send("home", { op: "open", text });
  });
  function openPinDialog() {
    $("#pin-target").value = ""; $("#pin-name").value = "";
    $("#pin-dialog").hidden = false;
    setTimeout(() => $("#pin-target").focus(), 0);
  }
  $("#pin-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const st = await send("home", { op: "pin_add", target: $("#pin-target").value.trim(), name: $("#pin-name").value.trim() });
    if (st) $("#pin-dialog").hidden = true;
  });


  // ─── Anzeigen: Live ─────────────────────────────────────
  function renderLive() {
    if (!E || !C) return;
    const st = E.state, mode = C.mode, main = mainHotkey(), side = C.current.button === "right" ? "right" : "left";
    const status = $("#status");
    status.dataset.s = st;
    const secs = Math.max(1, Math.ceil(E.countdown || 0));
    status.textContent = st === "countdown" ? t("st_countdown", { n: secs }) : st === "clicking" && E.holding ? t("st_holding") : STATUS[st] ? t(STATUS[st]) : st;
    $(".live").dataset.s = st;
    $("#cps").textContent = nf(E.cps);
    $("#st-clicks").textContent = new Intl.NumberFormat(locale).format(E.session_clicks);
    $("#st-time").textContent = clock(E.run_time);
    $("#st-best").textContent = nf(E.best_cps);

    const start = $("#start");
    start.classList.toggle("stop", E.armed);
    start.classList.toggle("wait", st === "countdown");
    $("#start-label").textContent = t(st === "countdown" ? "cancel" : E.armed ? "stop" : "start");
    $("#start-key").hidden = !main;
    $("#start-key").textContent = main ? keyLabel(main.key) : "";
    let hint;
    if (st === "countdown") {
      hint = t("hint_countdown");
    } else if (E.armed) {
      if (st === "paused") hint = t(E.reason === "self" ? "hint_self" : "hint_window");
      else if (E.reason === "tool") hint = t("hint_tool");
      else if (mode === "hold_mouse") hint = t(st === "clicking" ? "hint_pvp_clicking" : "hint_pvp_" + side);
      else if (mode === "boost") hint = t(st === "clicking" ? "hint_boost" : "hint_boost_ready");
      else if (E.holding || (C.preset === "afk" && C.current.action === "hold")) hint = t("hint_hold_" + side);
      else hint = t("hint_clicking");
    } else {
      hint = main ? t("hint_idle", { key: keyLabel(main.key) }) : t("hint_nokey");
      if (E.stop_reason === "limit") hint = t("hint_limit");
      else if (E.stop_reason === "hotkey" && stopKey) hint = t("hint_off_hotkey", { key: keyLabel(stopKey) });
    }
    $("#hint").textContent = recording !== null ? t("hint_record") : learning ? t(learnError || "hint_learn") : hint;
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
    $("#update-install").textContent = t(u.status === "error" ? "upd_retry" : u.can_install ? "upd_install" : "upd_download");
    $("#update-text").textContent =
      u.status === "downloading" ? t("upd_loading", { v: u.version, p: Math.round(u.progress * 100) })
      : u.status === "installing" ? t("upd_installing", { v: u.version })
      : u.status === "error" ? t("upd_failed", { e: u.error })
      : t("upd_new", { v: u.version });
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
    const ti = st.tool_index === undefined ? -1 : st.tool_index;
    const toolsChanged = !!st.learning !== learning || ti !== toolIndex;
    learning = !!st.learning; toolIndex = ti; learnError = st.learn_error || ""; stopKey = st.stop_key || "";
    if (st.config) renderConfig();
    else if (wasRecording !== recording && C) renderHotkeys();
    if (!st.config && toolsChanged) renderTools();
    renderUpdate(st.update || null);
    if (st.notice && st.notice.id !== lastNotice) { lastNotice = st.notice.id; toast(t(st.notice.key || st.notice.text || "", st.notice.vars)); }
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

  $$(".preset").forEach((b) => b.addEventListener("click", () => { closeHome(); send("preset", { id: b.dataset.id }); }));
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
  $("#o-delay").addEventListener("input", (e) => {
    markEdit(e.target);
    const v = +e.target.value;
    $("#o-delay-value").textContent = delayText(v);
    clearTimeout(e.target._t);
    e.target._t = setTimeout(() => sendGeneral({ start_delay: v }), 150);
  });
  $$("#action-seg [data-val]").forEach((b) => b.addEventListener("click", () => sendPreset({ action: b.dataset.val })));
  [["#o-vary", "vary"], ["#o-lock", "window_lock"], ["#o-top", "always_on_top"], ["#o-sound", "sound"], ["#o-learn", "learn_hotkey_on"]].forEach(([sel, key]) =>
    $(sel).addEventListener("change", (e) => { markEdit(e.target); sendGeneral({ [key]: e.target.checked }); }));
  $("#o-match").addEventListener("change", (e) => { markEdit(e.target); sendGeneral({ window_match: e.target.value }); });
  $("#o-lang").addEventListener("change", (e) => {
    markEdit(e.target);
    if (C) C.general.language = e.target.value;
    if (setLang(e.target.value) && C) { renderConfig(); renderLive(); renderTour(); }
    sendGeneral({ language: e.target.value });
  });
  $$("#theme-seg [data-val]").forEach((b) => b.addEventListener("click", () => { applyTheme(b.dataset.val); sendGeneral({ theme: b.dataset.val }); }));

  $("#start").addEventListener("click", () => send("action", { do: "toggle" }));
  $("#reset-stats").addEventListener("click", async () => { await send("action", { do: "reset_stats" }); toast(t("n_reset")); });

  // Dialoge
  function closeDialogs() {
    $("#settings").hidden = true;
    $("#kit-dialog").hidden = true;
    $("#pin-dialog").hidden = true;
    if (recording === "learn") send("hotkeys", { op: "cancel" });
    if (!$("#hotkeys").hidden) {
      $("#hotkeys").hidden = true;
      if (recording !== null) send("hotkeys", { op: "cancel" });
    }
  }
  $("#settings-btn").addEventListener("click", () => { $("#settings").hidden = false; });
  $("#hotkeys-btn").addEventListener("click", () => { $("#hotkeys").hidden = false; });
  $$("#settings, #hotkeys, #kit-dialog, #pin-dialog").forEach((ov) => ov.addEventListener("click", (e) => {
    if (e.target === ov || e.target.closest("[data-close]")) closeDialogs();
  }));
  $("#o-learn-key").addEventListener("click", () => send("hotkeys", recording === "learn" ? { op: "cancel" } : { op: "record", target: "learn" }));
  $("#hk-add").addEventListener("click", () => send("hotkeys", recording === "new" ? { op: "cancel" } : { op: "record" }));

  // ─── Anleitung (3 Schritte) ─────────────────────────────
  const TOUR = [
    { i: '<svg viewBox="0 0 24 24"><path d="M3 5h18v2H3zm0 6h18v2H3zm0 6h12v2H3z"/></svg>' },
    { i: '<svg viewBox="0 0 24 24"><path d="M3 11h11v2H3zm15 0h3v2h-3zM14 8h2v8h-2z"/></svg>' },
    { i: '<svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>' },
  ];
  let tourStep = 0;
  function renderTour() {
    const s = TOUR[tourStep], main = mainHotkey();
    $("#tour-art").innerHTML = s.i;
    $("#tour-title").textContent = t(`tour${tourStep + 1}_t`);
    $("#tour-text").textContent = t(`tour${tourStep + 1}_p`, { key: main ? keyLabel(main.key) : "F6" });
    $$("#tour-dots i").forEach((d, i) => d.classList.toggle("on", i === tourStep));
    $("#tour-next").textContent = t(tourStep === TOUR.length - 1 ? "tour_go" : "tour_next");
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
