"""Player shells: one per nxnative game profile, built on a Mac by the "Player shells" workflow (shells-data branch, <nxnative commit>/shell-<title ID>.zip).
The app carries none; the one a build needs is downloaded once (17 MB) and kept in Application Support/Shells/<commit>."""
import ctypes, json, os
from pathlib import Path

REPO = 'jakebway/nxnativeios'


def commit():
    return (Path(os.environ['NXB_UPSTREAM']) / '.nxb_commit').read_text().strip() if (Path(os.environ['NXB_UPSTREAM']) / '.nxb_commit').is_file() else ''


def supported(tid):
    """nxnative has a game profile for this title ID (a game without one cannot be built: nxnative needs per-game work on a Mac first)"""
    g = Path(os.environ['NXB_UPSTREAM']) / 'dm/games'
    lst = g / 'supported.txt'
    return (g / tid.upper()).is_dir() or (lst.is_file() and tid.upper() in lst.read_text().split())


def get(tid, cache, bundled, log, progress=None):
    """The shell zip for tid (the app's own copy if it has one, else the cached download, else downloaded now), with the game's profile put in place. Returns the shell's path."""
    tid = tid.upper(); name = f'shell-{tid}.zip'
    c = commit(); d = Path(cache) / (c or 'any'); d.mkdir(parents=True, exist_ok=True)
    prof = Path(os.environ['NXB_UPSTREAM']) / 'dm/games' / tid
    if not prof.is_dir():
        pz = d / f'profile-{tid}.zip'
        if not pz.is_file(): _fetch(c, pz.name, pz, tid, log, 'the game profile')
        import zipfile
        with zipfile.ZipFile(pz) as zf: zf.extractall(prof.parent)
        if not prof.is_dir(): raise RuntimeError(f'{pz.name} holds no profile for {tid}')
    if bundled and (Path(bundled) / name).is_file(): return Path(bundled) / name
    z = d / name
    if z.is_file() and z.stat().st_size > 1_000_000: return z
    log(f'shell: downloading the player for {tid} (about 17 MB, once)')
    _fetch(c, name, z, tid, log, 'the player', progress)
    return z


def _fetch(c, name, z, tid, log, what, progress=None):
    for old in z.parent.parent.iterdir():   # shells of an older nxnative are of no use once the app moved on
        if old != z.parent and old.is_dir():
            import shutil; shutil.rmtree(old, ignore_errors=True)
    url = f'https://raw.githubusercontent.com/{REPO}/shells-data/{c + "/" if c else ""}{name}'
    f = ctypes.CDLL(None).nxb_download
    CB = ctypes.CFUNCTYPE(None, ctypes.c_longlong, ctypes.c_longlong)
    f.argtypes = [ctypes.c_char_p, ctypes.c_char_p, CB, ctypes.c_char_p, ctypes.c_int]
    last = [-1]
    def cb(done, total):
        if progress and total > 0:
            p = int(done * 100 / total)
            if p != last[0]: last[0] = p; progress(done / total)
    cbp = CB(cb); err = ctypes.create_string_buffer(512); part = z.with_suffix('.part')
    rc = f(url.encode(), str(part).encode(), cbp, err, 512)
    if rc == 404: raise RuntimeError(f'{what} for {tid} is not built yet (the "Player shells" workflow builds one for every game nxnative supports). Try again once it has run')
    if rc != 0: raise RuntimeError(f'could not download {what} for {tid} ({err.value.decode(errors="replace") or f"HTTP {rc}"}). Check the internet connection and try again')
    os.replace(part, z)
