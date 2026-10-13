"""Bildschirmaufnahme ueber DXGI Desktop Duplication (Windows 8+), nur ctypes.

Wie OBS/Discord: funktioniert auch bei Spielen im (randlosen) Vollbild, wo die
klassische GDI-Aufnahme (BitBlt) nur ein schwarzes oder altes Bild liefert.
Es wird nur ein kleiner Streifen (unterer Fensterrand) kopiert.
"""

from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes as wt

HRESULT = ctypes.c_long
WAIT_TIMEOUT = 0x887A0027 - (1 << 32)   # DXGI_ERROR_WAIT_TIMEOUT
ACCESS_LOST = 0x887A0026 - (1 << 32)    # DXGI_ERROR_ACCESS_LOST
DXGI_FORMAT_B8G8R8A8_UNORM = 87
D3D11_USAGE_STAGING = 3
D3D11_CPU_ACCESS_READ = 0x20000
D3D11_MAP_READ = 1


class GUID(ctypes.Structure):
    _fields_ = [("a", wt.DWORD), ("b", wt.WORD), ("c", wt.WORD), ("d", ctypes.c_ubyte * 8)]


def _guid(text: str) -> GUID:
    h = text.replace("-", "")
    return GUID(int(h[0:8], 16), int(h[8:12], 16), int(h[12:16], 16),
                (ctypes.c_ubyte * 8)(*bytes.fromhex(h[16:])))


IID_IDXGIDevice = _guid("54ec77fa-1377-44e6-8c32-88fd5f44c84c")
IID_IDXGIOutput1 = _guid("00cddea8-939b-4b83-a340-a685226666cc")
IID_ID3D11Texture2D = _guid("6f15aaf2-d208-4e89-9ab4-489535d34f9c")


class DXGI_OUTPUT_DESC(ctypes.Structure):
    _fields_ = [("DeviceName", wt.WCHAR * 32), ("DesktopCoordinates", wt.RECT),
                ("AttachedToDesktop", wt.BOOL), ("Rotation", ctypes.c_uint), ("Monitor", wt.HANDLE)]


class DXGI_OUTDUPL_FRAME_INFO(ctypes.Structure):
    _fields_ = [("LastPresentTime", ctypes.c_int64), ("LastMouseUpdateTime", ctypes.c_int64),
                ("AccumulatedFrames", ctypes.c_uint), ("RectsCoalesced", wt.BOOL),
                ("ProtectedContentMaskedOut", wt.BOOL),
                ("PointerPosition", ctypes.c_byte * 12), ("TotalMetadataBufferSize", ctypes.c_uint),
                ("PointerShapeBufferSize", ctypes.c_uint)]


class D3D11_TEXTURE2D_DESC(ctypes.Structure):
    _fields_ = [("Width", ctypes.c_uint), ("Height", ctypes.c_uint), ("MipLevels", ctypes.c_uint),
                ("ArraySize", ctypes.c_uint), ("Format", ctypes.c_uint), ("SampleCount", ctypes.c_uint),
                ("SampleQuality", ctypes.c_uint), ("Usage", ctypes.c_uint), ("BindFlags", ctypes.c_uint),
                ("CPUAccessFlags", ctypes.c_uint), ("MiscFlags", ctypes.c_uint)]


class D3D11_BOX(ctypes.Structure):
    _fields_ = [("left", ctypes.c_uint), ("top", ctypes.c_uint), ("front", ctypes.c_uint),
                ("right", ctypes.c_uint), ("bottom", ctypes.c_uint), ("back", ctypes.c_uint)]


class D3D11_MAPPED_SUBRESOURCE(ctypes.Structure):
    _fields_ = [("pData", ctypes.c_void_p), ("RowPitch", ctypes.c_uint), ("DepthPitch", ctypes.c_uint)]


def _method(obj, index: int, *argtypes):
    """COM-Methode Nr. index aus der vtable von obj (c_void_p) als aufrufbare Funktion."""
    vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    proto = ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, *argtypes)
    fn = proto(vtbl[index])
    return lambda *args: fn(obj, *args)


def _release(obj) -> None:
    if obj:
        vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtbl[2])(obj)


def _query(obj, iid: GUID):
    out = ctypes.c_void_p()
    hr = _method(obj, 0, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p))(ctypes.byref(iid), ctypes.byref(out))
    return out if hr >= 0 and out else None


class DesktopDuplication:
    """Haelt Geraet + Duplizierung offen und kopiert bei Bedarf einen Bildausschnitt."""

    def __init__(self):
        self._lock = threading.Lock()
        self._device = self._context = None
        self._outputs: list = []     # [(output1, RECT)]
        self._dups: dict = {}        # index -> duplication
        self._cache: dict = {}       # (index, x, y, w, h) -> bytes (falls kein neues Bild kam)
        self.error = ""

    # ─── Aufbau ─────────────────────────────────────────
    def _init(self) -> bool:
        if self._device:
            return True
        d3d11 = ctypes.WinDLL("d3d11")
        create = d3d11.D3D11CreateDevice
        create.restype = HRESULT
        create.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p,
                           ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p),
                           ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_void_p)]
        device, context, level = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_uint()
        hr = create(None, 1, None, 0, None, 0, 7, ctypes.byref(device), ctypes.byref(level), ctypes.byref(context))
        if hr < 0:
            self.error = f"D3D11CreateDevice {hr & 0xFFFFFFFF:#x}"
            return False
        self._device, self._context = device, context
        dxgi_dev = _query(device, IID_IDXGIDevice)
        adapter = ctypes.c_void_p()
        _method(dxgi_dev, 7, ctypes.POINTER(ctypes.c_void_p))(ctypes.byref(adapter))   # GetAdapter
        _release(dxgi_dev)
        i = 0
        while True:
            out = ctypes.c_void_p()
            if _method(adapter, 7, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p))(i, ctypes.byref(out)) < 0:
                break                                                                  # EnumOutputs
            desc = DXGI_OUTPUT_DESC()
            _method(out, 7, ctypes.POINTER(DXGI_OUTPUT_DESC))(ctypes.byref(desc))     # GetDesc
            out1 = _query(out, IID_IDXGIOutput1)
            _release(out)
            if out1:
                self._outputs.append((out1, desc.DesktopCoordinates))
            i += 1
        _release(adapter)
        if not self._outputs:
            self.error = "keine Ausgabe"
            return False
        return True

    def _dup(self, index: int):
        dup = self._dups.get(index)
        if dup:
            return dup
        dup = ctypes.c_void_p()
        out1 = self._outputs[index][0]
        hr = _method(out1, 22, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))(self._device, ctypes.byref(dup))
        if hr < 0:                                                                     # DuplicateOutput
            self.error = f"DuplicateOutput {hr & 0xFFFFFFFF:#x}"
            return None
        self._dups[index] = dup
        return dup

    def _drop_dup(self, index: int) -> None:
        _release(self._dups.pop(index, None))

    # ─── Aufnahme ───────────────────────────────────────
    def grab(self, x: int, y: int, w: int, h: int):
        """Ausschnitt in Bildschirmkoordinaten (physische Pixel) -> BGRA-Bytes oder None."""
        with self._lock:
            try:
                if not self._init():
                    return None
                for index, (_out, rc) in enumerate(self._outputs):
                    if rc.left <= x and x + w <= rc.right and rc.top <= y and y + h <= rc.bottom:
                        return self._grab_on(index, x - rc.left, y - rc.top, w, h)
                self.error = "Fenster auf keinem Bildschirm"
            except Exception as e:  # nie die App mitreissen
                self.error = f"{type(e).__name__}: {e}"
            return None

    def _grab_on(self, index: int, x: int, y: int, w: int, h: int):
        key = (index, x, y, w, h)
        for _attempt in range(2):
            dup = self._dup(index)
            if not dup:
                return None
            info = DXGI_OUTDUPL_FRAME_INFO()
            res = ctypes.c_void_p()
            hr = _method(dup, 8, ctypes.c_uint, ctypes.POINTER(DXGI_OUTDUPL_FRAME_INFO),
                         ctypes.POINTER(ctypes.c_void_p))(60, ctypes.byref(info), ctypes.byref(res))
            if hr == WAIT_TIMEOUT:            # kein neues Bild – letztes nehmen
                return self._cache.get(key)
            if hr == ACCESS_LOST:              # Aufloesung/Vollbild gewechselt -> neu aufbauen
                self._drop_dup(index)
                continue
            if hr < 0:
                self.error = f"AcquireNextFrame {hr & 0xFFFFFFFF:#x}"
                self._drop_dup(index)
                return None
            try:
                data = self._copy(res, x, y, w, h)
            finally:
                _release(res)
                _method(dup, 14)()                                                     # ReleaseFrame
            if data:
                self._cache = {key: data}
            return data
        return None

    def _copy(self, res, x, y, w, h):
        tex = _query(res, IID_ID3D11Texture2D)
        if not tex:
            return None
        staging = ctypes.c_void_p()
        try:
            desc = D3D11_TEXTURE2D_DESC(w, h, 1, 1, DXGI_FORMAT_B8G8R8A8_UNORM, 1, 0,
                                        D3D11_USAGE_STAGING, 0, D3D11_CPU_ACCESS_READ, 0)
            hr = _method(self._device, 5, ctypes.POINTER(D3D11_TEXTURE2D_DESC), ctypes.c_void_p,
                         ctypes.POINTER(ctypes.c_void_p))(ctypes.byref(desc), None, ctypes.byref(staging))
            if hr < 0:                                                                 # CreateTexture2D
                self.error = f"CreateTexture2D {hr & 0xFFFFFFFF:#x}"
                return None
            box = D3D11_BOX(x, y, 0, x + w, y + h, 1)
            ctx = self._context
            copy = ctypes.WINFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint,
                                      ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint,
                                      ctypes.POINTER(D3D11_BOX))
            vtbl = ctypes.cast(ctx, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
            copy(vtbl[46])(ctx, staging, 0, 0, 0, 0, tex, 0, ctypes.byref(box))       # CopySubresourceRegion
            mapped = D3D11_MAPPED_SUBRESOURCE()
            hr = _method(ctx, 14, ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint,
                         ctypes.POINTER(D3D11_MAPPED_SUBRESOURCE))(staging, 0, D3D11_MAP_READ, 0, ctypes.byref(mapped))
            if hr < 0:                                                                 # Map
                self.error = f"Map {hr & 0xFFFFFFFF:#x}"
                return None
            try:
                row = w * 4
                out = bytearray(row * h)
                for line in range(h):
                    ctypes.memmove(ctypes.addressof((ctypes.c_char * row).from_buffer(out, line * row)),
                                   mapped.pData + line * mapped.RowPitch, row)
                return bytes(out)
            finally:
                unmap = ctypes.WINFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint)
                unmap(vtbl[15])(ctx, staging, 0)                                       # Unmap
        finally:
            _release(staging)
            _release(tex)
