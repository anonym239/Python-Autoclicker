"""Baut eine einzelne HTML-Datei als Live-Vorschau der Oberflaeche.

Die Vorschau nutzt exakt dieselben Dateien wie das Programm (web/index.html,
style.css, app.js) – nur das Python-Programm dahinter wird im Browser
simuliert (tools/preview_mock.js). Ideal zum Anschauen auf dem Handy.

    python tools/build_preview.py [ziel.html]
"""

import base64
import json
import os
import re
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from clicker.app import qr_svg  # noqa: E402
from clicker.config import Config  # noqa: E402

WEB = os.path.join(ROOT, "web")
FONTS = ("https://fonts.googleapis.com/css2?family=Chakra+Petch:wght@400;500;600;700"
         "&family=Jersey+15&display=swap")

PREVIEW_CSS = """
/* ─── Vorschau-Rahmen ─── */
.pv { padding-inline: 16px; padding-block: 14px 28px; }
.pv-bar { max-width: 964px; margin: 0 auto 14px; display: flex; flex-wrap: wrap; align-items: center; gap: 10px 16px; }
.pv-seg { display: inline-grid; grid-template-columns: 1fr 1fr; gap: 4px; padding: 4px; border-radius: 6px; background: var(--slot);
  box-shadow: inset 2px 2px 0 var(--lo), inset -2px -2px 0 var(--hi); }
.pv-seg button { border: 0; border-radius: 4px; padding: 8px 14px; background: none; color: var(--muted); font-weight: 600; }
.pv-seg button[aria-pressed="true"] { background: var(--accent); color: var(--accent-ink); box-shadow: inset 0 2px 0 rgba(255,255,255,.3), inset 0 -3px 0 rgba(0,0,0,.25); }
.pv-hint { margin: 0; color: var(--muted); font-size: 13px; flex: 1 1 260px; }
.pv-hint kbd { font-size: 15px; padding: 1px 6px; border-radius: 3px; background: var(--bg-3); color: var(--fg); }
.pv-stage { max-width: 964px; margin: 0 auto; }
.pv-scale { margin: 0 auto; }
.pv-window { width: 964px; transform-origin: top left; border-radius: 8px; overflow: hidden; background: var(--bg);
  box-shadow: 0 0 0 1px #2c313b, 0 24px 60px rgba(0,0,0,.55); }
.pv-title { height: 32px; display: flex; align-items: center; gap: 10px; padding: 0 0 0 12px; background: #202227; color: #d6d8dc; font: 12px/1 "Segoe UI", system-ui, sans-serif; }
.pv-title img { width: 16px; height: 16px; image-rendering: pixelated; }
.pv-title span { flex: 1; }
.pv-title i { width: 46px; height: 32px; display: grid; place-items: center; font-style: normal; color: #b9bcc2; font-size: 13px; }
.pv-viewport { height: 681px; container: app / inline-size; background-color: var(--bg); background-image: var(--tex); background-size: 64px 64px; }
.pv-pc .app { height: 100%; display: flex; flex-direction: column; }
.pv-pc .layout { flex: 1; min-height: 0; }
.pv-pc .hud, .pv-pc .panel { max-height: 100%; overflow-y: auto; scrollbar-width: thin; scrollbar-color: var(--hi) transparent; }
.pv-pc .panel { padding-top: 0; }
.pv-phone .pv-window { width: min(400px, 100%); margin: 0 auto; border-radius: 30px; border: 8px solid #0a0b0d; transform: none !important; }
.pv-phone .pv-title { display: none; }
.pv-phone .pv-viewport { height: auto; padding-top: 10px; }
.pv-phone .pv-scale { width: auto !important; height: auto !important; }
"""

PREVIEW_JS = """
(() => {
  const pv = document.querySelector(".pv");
  const stage = document.querySelector(".pv-stage");
  const scaler = document.querySelector(".pv-scale");
  const win = document.querySelector(".pv-window");
  let view = "pc";
  function layout() {
    if (view === "pc") {
      const s = Math.min(1, stage.clientWidth / 964);
      win.style.transform = s < 1 ? `scale(${s})` : "";
      scaler.style.width = 964 * s + "px";
      scaler.style.height = win.offsetHeight * s + "px";
    }
  }
  function setView(v) {
    view = v;
    pv.classList.toggle("pv-pc", v === "pc");
    pv.classList.toggle("pv-phone", v === "phone");
    document.querySelectorAll(".pv-seg button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.view === v)));
    window.AC_MOCK.setRemoteClient(v === "phone");
    layout();
    window.dispatchEvent(new Event("resize"));
  }
  document.querySelectorAll(".pv-seg button").forEach((b) => b.addEventListener("click", () => setView(b.dataset.view)));
  window.addEventListener("resize", layout);
  if (window.ResizeObserver) new ResizeObserver(layout).observe(stage);
  setView("pc");
})();
"""


def _data_uri(text: str, mime: str) -> str:
    return f"data:{mime};base64," + base64.b64encode(text.encode("utf-8")).decode("ascii")


def _drop_block(css: str, head: str) -> str:
    start = css.index(head)
    i = css.index("{", start)
    depth = 0
    for j in range(i, len(css)):
        if css[j] == "{":
            depth += 1
        elif css[j] == "}":
            depth -= 1
            if depth == 0:
                return css[:start] + css[j + 1:]
    raise ValueError("Block nicht geschlossen: " + head)


def read(*parts) -> str:
    with open(os.path.join(*parts), encoding="utf-8") as f:
        return f.read()


def build() -> str:
    html = read(WEB, "index.html")
    body = html.split("<!--APP-->")[1].split("<!--/APP-->")[0]
    app_part, rest = body.split("<!-- Hotkey-Aufnahme -->")
    icon = _data_uri(read(WEB, "icon.svg"), "image/svg+xml")
    app_part = app_part.replace('src="icon.svg"', f'src="{icon}"')

    css = read(WEB, "style.css")
    css = re.sub(r"@font-face \{[^}]*\}\n", "", css)
    css = _drop_block(css, "@media (min-width: 821px) and (min-height: 560px)")
    css = css.replace("@media (max-width: 820px)", "@container app (max-width: 820px)")
    css = css.replace("@media (max-width: 480px)", "@container app (max-width: 480px)")

    with tempfile.TemporaryDirectory() as tmp:
        cfg = Config(tmp)
        cfg.load()
    data = cfg.data
    data["app"]["token"] = "Vorschau-Code"
    mock = read(ROOT, "tools", "preview_mock.js")
    mock = mock.replace("__CONFIG__", json.dumps(data, ensure_ascii=False))
    mock = mock.replace("__QR__", _data_uri(qr_svg("http://192.168.178.24:8765/?t=Vorschau-Code"), "image/svg+xml"))
    app_js = read(WEB, "app.js")

    return f"""<title>AutoClicker v6</title>
<link rel="stylesheet" href="{FONTS}">
<style>
{css}
{PREVIEW_CSS}
</style>
<div class="pv pv-pc">
  <div class="pv-bar">
    <div class="pv-seg" role="group" aria-label="Ansicht">
      <button type="button" data-view="pc" aria-pressed="true">PC-Fenster</button>
      <button type="button" data-view="phone" aria-pressed="false">Handy</button>
    </div>
    <p class="pv-hint">Live-Vorschau, Klicks werden simuliert. Start mit <kbd>F6</kbd> oder dem großen Knopf. „Maus halten“: freie Fläche gedrückt halten.</p>
  </div>
  <div class="pv-stage">
    <div class="pv-scale">
      <div class="pv-window">
        <div class="pv-title"><img src="{icon}" alt=""><span>AutoClicker v6</span><i>&#8212;</i><i>&#9744;</i><i>&#10005;</i></div>
        <div class="pv-viewport">
{app_part}
        </div>
      </div>
    </div>
  </div>
</div>
{rest}
<script>
{mock}
</script>
<script>
{app_js}
</script>
<script>
{PREVIEW_JS}
</script>
"""


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "vorschau.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(build())
    print("Vorschau geschrieben:", out)


if __name__ == "__main__":
    main()
