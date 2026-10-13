"""Baut eine einzelne HTML-Datei als Live-Vorschau der Oberflaeche.

Die Vorschau nutzt dieselben Dateien wie das Programm (web/index.html,
style.css, i18n.js, app.js) – nur das Python-Programm dahinter wird im Browser
simuliert (tools/preview_mock.js).

    python tools/build_preview.py [ziel.html]
"""

import base64
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from clicker import VERSION  # noqa: E402
from clicker.config import PRESETS, Config  # noqa: E402

WEB = os.path.join(ROOT, "web")
WIN_W, WIN_H = 844, 641  # Innengroesse des Programmfensters

PREVIEW_CSS = """
/* ─── Vorschau-Rahmen ─── */
body { min-width: 0 !important; }
.pv { padding-inline: 16px; padding-block: 14px 28px; }
.pv-bar { max-width: 856px; margin: 0 auto 14px; display: flex; flex-wrap: wrap; align-items: center; gap: 10px 16px; }
.pv-hint { margin: 0; color: var(--muted); font-size: 13px; flex: 1 1 260px; }
.pv-stage { max-width: 856px; margin: 0 auto; }
.pv-scale { margin: 0 auto; }
.pv-window { width: %(w)dpx; transform-origin: top left; border-radius: 8px; overflow: hidden;
  box-shadow: 0 0 0 1px var(--line), var(--shadow); background: var(--bg); }
.pv-title { height: 32px; display: flex; align-items: center; gap: 10px; padding-left: 12px; background: var(--side);
  color: var(--fg); font: 12px/1 var(--font); border-bottom: 1px solid var(--line); }
.pv-title img { width: 16px; height: 16px; }
.pv-title span { flex: 1; }
.pv-title i { width: 46px; height: 32px; display: grid; place-items: center; font-style: normal; color: var(--muted); }
.pv-viewport { position: relative; height: %(h)dpx; overflow: auto; transform: translateZ(0); background: var(--bg); }
.pv-viewport .app { min-height: 100%%; }
""" % {"w": WIN_W, "h": WIN_H}

PREVIEW_JS = """
(() => {
  const stage = document.querySelector(".pv-stage");
  const scaler = document.querySelector(".pv-scale"), win = document.querySelector(".pv-window");
  function layout() {
    const s = Math.min(1, stage.clientWidth / %(w)d);
    win.style.transform = s < 1 ? `scale(${s})` : "";
    scaler.style.width = %(w)d * s + "px";
    scaler.style.height = win.offsetHeight * s + "px";
  }
  window.addEventListener("resize", layout);
  if (window.ResizeObserver) new ResizeObserver(layout).observe(stage);
  layout();
})();
""" % {"w": WIN_W}


def _data_uri(text: str, mime: str) -> str:
    return f"data:{mime};base64," + base64.b64encode(text.encode("utf-8")).decode("ascii")


def read(*parts) -> str:
    with open(os.path.join(*parts), encoding="utf-8") as f:
        return f.read()


def build() -> str:
    html = read(WEB, "index.html")
    body = html.split("<!--APP-->")[1].split("<!--/APP-->")[0]
    icon = _data_uri(read(WEB, "icon.svg"), "image/svg+xml")
    body = body.replace('src="icon.svg"', f'src="{icon}"')

    css = read(WEB, "style.css")
    css = css.replace(".app { display: grid; grid-template-columns: 224px minmax(0, 1fr); min-height: 100vh; }",
                      ".app { display: grid; grid-template-columns: 224px minmax(0, 1fr); }")

    with tempfile.TemporaryDirectory() as tmp:
        cfg = Config(tmp)
        cfg.load()
    data = cfg.data
    data["general"]["token"] = "Vorschau-Code"
    presets = {pid: {"name": p["name"], "mode": p["mode"]} for pid, p in PRESETS.items()}
    mock = read(ROOT, "tools", "preview_mock.js")
    mock = mock.replace("__CONFIG__", json.dumps(data, ensure_ascii=False))
    mock = mock.replace("__PRESETS__", json.dumps(presets, ensure_ascii=False))
    mock = mock.replace("__VERSION__", VERSION)

    return f"""<title>AutoClicker 6</title>
<style>
{css}
{PREVIEW_CSS}
</style>
<div class="pv">
  <div class="pv-bar">
    <p class="pv-hint">Vorschau des PC-Fensters mit simulierten Klicks. Start mit F6 oder dem Knopf – es wird sofort geklickt. PvP/Boost: auf eine freie Fläche klicken bzw. gedrückt halten.</p>
  </div>
  <div class="pv-stage">
    <div class="pv-scale">
      <div class="pv-window">
        <div class="pv-title"><img src="{icon}" alt=""><span>AutoClicker 6</span><i>&#8212;</i><i>&#9744;</i><i>&#10005;</i></div>
        <div class="pv-viewport">
{body}
        </div>
      </div>
    </div>
  </div>
</div>
<script>
{mock}
</script>
<script>
{read(WEB, "i18n.js")}
</script>
<script>
{read(WEB, "app.js")}
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
