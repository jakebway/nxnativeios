"""RAR archives (single, game.part1.rar + part2 ..., or game.rar + game.r00 + r01 ...) through libunrar (Unrar.framework, ctypes).
Volumes are found by name in the same folder, so pick them all."""
import ctypes, os, re
from pathlib import Path

RAR_OM_EXTRACT, RAR_SKIP, RAR_EXTRACT = 1, 0, 2
RHDF_DIRECTORY = 0x20
ERR = {11: 'out of memory', 12: 'the archive is damaged (bad data)', 13: 'this is not a RAR archive', 14: 'an unknown RAR format', 15: 'could not open it (is a part of the archive missing?)',
       16: 'could not create the file', 18: 'could not read', 19: 'could not write the file (disk full?)', 22: 'a password is needed (not supported)', 24: 'wrong password',
       23: 'a bad file reference in the archive', 25: 'the archive needs more memory than this phone gives'}
# RARHeaderDataEx: char ArcName[1024]; wchar_t ArcNameW[1024]; char FileName[1024]; wchar_t FileNameW[1024]; unsigned Flags ...
HDR_SIZE, OFF_FILENAME_W, OFF_FLAGS = 40960, 1024 + 4096 + 1024, 1024 + 4096 + 1024 + 4096


class OpenData(ctypes.Structure):   # RAROpenArchiveDataEx
    _fields_ = [('ArcName', ctypes.c_char_p), ('ArcNameW', ctypes.c_wchar_p), ('OpenMode', ctypes.c_uint), ('OpenResult', ctypes.c_uint),
                ('CmtBuf', ctypes.c_char_p), ('CmtBufSize', ctypes.c_uint), ('CmtSize', ctypes.c_uint), ('CmtState', ctypes.c_uint),
                ('Flags', ctypes.c_uint), ('Callback', ctypes.c_void_p), ('UserData', ctypes.c_ssize_t), ('OpFlags', ctypes.c_uint),
                ('CmtBufW', ctypes.c_wchar_p), ('MarkOfTheWeb', ctypes.c_uint), ('Reserved', ctypes.c_uint * 23)]


def _lib():
    from . import shim
    return shim._lib('Unrar')


def version():
    lib = _lib(); lib.RARGetDllVersion.restype = ctypes.c_int
    return lib.RARGetDllVersion()


def first_volumes(paths):
    """(archives to open, the rest): of a set of picked files, the first volume of each RAR (volumes after it are used through it)."""
    paths = [Path(p) for p in paths]; firsts, used = [], set()
    names = {p.name.lower(): p for p in paths}
    for p in paths:
        n = p.name.lower()
        m = re.fullmatch(r'(.+)\.part0*(\d+)\.rar', n)
        if m:
            used.add(p)
            if int(m.group(2)) == 1:
                nums = sorted(int(x.group(1)) for q in paths if (x := re.fullmatch(re.escape(m.group(1)) + r'\.part0*(\d+)\.rar', q.name.lower())))
                if nums != list(range(1, nums[-1] + 1)): raise RuntimeError(f'{p.name}: parts of the RAR are missing (have part {", ".join(map(str, nums))})')
                firsts.append(p)
        elif re.fullmatch(r'.+\.r\d\d', n): used.add(p)   # game.r00, game.r01 ... follow game.rar
        elif n.endswith('.rar'): used.add(p); firsts.append(p)
    return firsts, [p for p in paths if p not in used]


def extract(archive, want):
    """Unpack the archive. want(name) -> destination path (str) for an entry to keep, or None to skip it. Yields the kept (name, destination)."""
    lib = _lib()
    lib.RAROpenArchiveEx.restype = ctypes.c_void_p; lib.RAROpenArchiveEx.argtypes = [ctypes.POINTER(OpenData)]
    lib.RARReadHeaderEx.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    lib.RARProcessFile.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_char_p]
    lib.RARCloseArchive.argtypes = [ctypes.c_void_p]
    od = OpenData(); od.ArcName = os.fsencode(str(archive)); od.OpenMode = RAR_OM_EXTRACT
    h = lib.RAROpenArchiveEx(ctypes.byref(od))
    if not h: raise RuntimeError(f'{Path(archive).name}: ' + ERR.get(od.OpenResult, f'RAR error {od.OpenResult}'))
    try:
        buf = ctypes.create_string_buffer(HDR_SIZE)
        while True:
            r = lib.RARReadHeaderEx(h, buf)
            if r != 0:
                if r == 10: return   # ERAR_END_ARCHIVE
                raise RuntimeError(f'{Path(archive).name}: ' + ERR.get(r, f'RAR error {r}'))
            raw = buf.raw
            name = ctypes.wstring_at(ctypes.addressof(buf) + OFF_FILENAME_W) if ctypes.sizeof(ctypes.c_wchar) == 4 else raw[OFF_FILENAME_W:OFF_FILENAME_W + 2048].decode('utf-16-le').split('\0')[0]
            flags = int.from_bytes(raw[OFF_FLAGS:OFF_FLAGS + 4], 'little')
            dst = None if flags & RHDF_DIRECTORY else want(name.replace('\\', '/'))
            if dst is None: r = lib.RARProcessFile(h, RAR_SKIP, None, None)
            else:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                r = lib.RARProcessFile(h, RAR_EXTRACT, None, os.fsencode(dst))
            if r != 0: raise RuntimeError(f'{name}: ' + ERR.get(r, f'RAR error {r}'))
            if dst is not None: yield name, dst
    finally:
        lib.RARCloseArchive(h)
