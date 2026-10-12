# PyInstaller-Bauplan fuer AutoClicker.exe
# Bauen am besten mit:  python tools/build_windows.py

a = Analysis(
    ["AutoClicker.pyw"],
    datas=[("web", "web")],
    excludes=["tkinter", "_tkinter", "unittest", "pydoc_data", "test", "lib2to3"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AutoClicker",
    icon="assets/icon.ico",
    version="build/version_info.txt",
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, upx=False, name="AutoClicker")
