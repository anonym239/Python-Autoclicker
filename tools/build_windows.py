"""Baut AutoClicker.exe und den Installer. Nur unter Windows.

    python -m pip install pyinstaller
    python tools/build_windows.py

Braucht Inno Setup 6 (https://jrsoftware.org/isdl.php) fuer den Installer.
Ergebnis in dist/:
  AutoClicker-Setup-<version>.exe    Installer (Startmenue, Desktop-Verknuepfung, Deinstallation)
  AutoClicker-<version>-portable.zip ohne Installation, einfach entpacken
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from clicker import VERSION  # noqa: E402

VERSION_INFO = """VSVersionInfo(
  ffi=FixedFileInfo(filevers={nums}, prodvers={nums}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040704B0', [
      StringStruct('CompanyName', 'anonym239'),
      StringStruct('FileDescription', 'AutoClicker'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('InternalName', 'AutoClicker'),
      StringStruct('OriginalFilename', 'AutoClicker.exe'),
      StringStruct('ProductName', 'AutoClicker'),
      StringStruct('ProductVersion', '{version}')])]),
    VarFileInfo([VarStruct('Translation', [0x0407, 1200])])
  ]
)
"""


def find_iscc() -> str | None:
    if os.environ.get("ISCC") and os.path.isfile(os.environ["ISCC"]):
        return os.environ["ISCC"]
    for base in (os.environ.get("PROGRAMFILES(X86)"), os.environ.get("PROGRAMFILES"),
                 os.environ.get("LOCALAPPDATA")):
        if base:
            for path in glob.glob(os.path.join(base, "Inno Setup*", "ISCC.exe")) + \
                    glob.glob(os.path.join(base, "Programs", "Inno Setup*", "ISCC.exe")):
                return path
    return shutil.which("iscc")


def main() -> int:
    os.chdir(ROOT)
    nums = tuple(int(x) for x in (VERSION.split(".") + ["0", "0", "0"])[:4])
    os.makedirs("build", exist_ok=True)
    with open(os.path.join("build", "version_info.txt"), "w", encoding="utf-8") as f:
        f.write(VERSION_INFO.format(nums=nums, version=VERSION))

    print(f"== PyInstaller (AutoClicker {VERSION})")
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "AutoClicker.spec"], check=True)
    if not os.path.isfile(os.path.join("dist", "AutoClicker", "AutoClicker.exe")):
        print("AutoClicker.exe wurde nicht erzeugt.")
        return 1

    print("== Portable ZIP")
    base = os.path.join("dist", f"AutoClicker-{VERSION}-portable")
    shutil.make_archive(base, "zip", "dist", "AutoClicker")

    iscc = find_iscc()
    if not iscc:
        print("Inno Setup (ISCC.exe) nicht gefunden – Installer wird übersprungen.")
        return 0
    print("== Inno Setup")
    subprocess.run([iscc, f"/DAppVersion={VERSION}", os.path.join("installer", "AutoClicker.iss")], check=True)
    print("Fertig:", os.path.join("dist", f"AutoClicker-Setup-{VERSION}.exe"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
