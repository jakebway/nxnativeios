"""Storage on the phone: the space a build takes, and giving it back.

A big game takes 100 GB of work files if all of them stay until the end, and an iPhone has one disk. The forks of nxnative (the Windows shells) and upstream's scripts each handle a part
of this; this module is where the app does the same:

  preflight(inputs)     before anything is copied: refuse early, in plain words, when the phone cannot hold the build (nxn_pack.check_free_space: "it fails halfway through the extraction,
                        which leaves a partial tree of the same size to clean up, so say it up front"); a warning, not a refusal, when it is tight
  sweep_temp()          the temporary files a stopped run left behind (the shader split's spill file, half-written .partial / .tmp folders): removed at the start of the next run
                        (nxn_pack --clean, upstream's .partial folders and prune_stale_chains)
  after_failure(job)    a failed build keeps its log and the extracted game (the next try starts from it), and gives back everything else: the game file copy, the shader packages,
                        unfinished folders
  friendly(e)           "No space left on device" as what it means and what to do
  free_gb(path)         the app's own view of the free space (logged at each stage, so a log shows where the disk went)
"""
import errno, os, shutil, tempfile, time
from pathlib import Path

NEED = 2.4        # game size -> room for the copy, the extracted game, and the largest work files at once (measured: 2 to 2.3 for the games built so far)
REFUSE = 1.5      # below this the copy and the extraction cannot both fit
EXPAND = {'.nsz': 1.6, '.xcz': 1.6, '.rar': 1.05, '.zip': 1.05}   # a compressed game unpacks to more than its file


def free_bytes(path):
    p = str(path)
    while p and not os.path.exists(p): p = os.path.dirname(p)
    s = os.statvfs(p or '/')
    return s.f_bavail * s.f_frsize


def free_gb(path): return free_bytes(path) / 1e9


def game_bytes(inputs):
    """→ the bytes the game will unpack to, from the picked files (keys and small files count for nothing)"""
    n = 0
    for p in inputs or []:
        try:
            q = Path(p)
            files = [f for f in q.rglob('*') if f.is_file()] if q.is_dir() else [q]
            for f in files:
                s = f.stat().st_size
                if s > (64 << 20): n += int(s * EXPAND.get(f.suffix.lower(), 1.0))
        except OSError: pass
    return n


def preflight(inputs, where, log):
    """Raises RuntimeError when the phone clearly cannot hold the build; logs the numbers either way"""
    size = game_bytes(inputs)
    if not size: return
    free = free_bytes(where)
    need = size * NEED
    log(f'[disk] {free / 1e9:.1f} GB free; the game takes about {size / 1e9:.1f} GB and the build up to about {need / 1e9:.0f} GB at its peak')
    if free < size * REFUSE:
        raise RuntimeError(f'Not enough storage: {free / 1e9:.0f} GB is free and this build needs about {need / 1e9:.0f} GB while it runs (the game is {size / 1e9:.0f} GB). Free some space in Settings > General > iPhone Storage and build again.')
    if free < need: log(f'[RED] storage is tight: {free / 1e9:.0f} GB free, {need / 1e9:.0f} GB is safer. The build goes on and gives space back as it goes; if it stops for space, free some and build again.')


_TEMP_PREFIXES = ('split-spill-', 'nxb-', 'nxnative-')


def sweep_temp(log=None, older_than=1800):
    """the run's temporary folder: what an earlier run left behind (a killed app leaves its spill file). Only names this app makes, only when nothing has touched them for a while"""
    n = 0; now = time.time()
    try: entries = list(os.scandir(tempfile.gettempdir()))
    except OSError: return 0
    for e in entries:
        if not e.name.startswith(_TEMP_PREFIXES): continue
        try:
            if now - e.stat(follow_symlinks=False).st_mtime < older_than: continue
            size = e.stat().st_size if e.is_file() else sum(f.stat().st_size for f in Path(e.path).rglob('*') if f.is_file())
            shutil.rmtree(e.path, ignore_errors=True) if e.is_dir(follow_symlinks=False) else os.unlink(e.path)
            n += size
        except OSError: pass
    if n and log: log(f'[cleanup] freed {n / 1e9:.1f} GB: temporary files of an earlier run')
    return n


def partials(root):
    """unfinished folders and files under a job: each is rebuilt from scratch by the step that made it"""
    root = Path(root)
    if not root.is_dir(): return []
    out = []
    for dp, dirs, files in os.walk(root):
        for n in list(dirs):
            if n.endswith(('.partial', '.tmp')): out.append(Path(dp) / n); dirs.remove(n)
        out += [Path(dp) / n for n in files if n.endswith(('.partial', '.tmp')) and n != 'status.json.tmp']
    return out


def _size(p):
    try: return sum(f.stat().st_size for f in p.rglob('*') if f.is_file()) if p.is_dir() else p.stat().st_size
    except OSError: return 0


def after_failure(job_dir, log):
    """the game's extraction stays (the next try starts from it); the rest of the work goes: the game file copy, unfinished folders, the shader packages, the spill file"""
    job_dir = Path(job_dir); freed = 0
    victims = partials(job_dir) + [job_dir / 'input/game'] + list((job_dir / 'build').glob('*/shader/pkg*')) + list((job_dir / 'build').glob('*/shader/split-spill-*'))
    for p in victims:
        if not p.exists(): continue
        n = _size(p)
        try: shutil.rmtree(p) if p.is_dir() else p.unlink()
        except OSError: continue
        freed += n
    freed += sweep_temp(None, older_than=0)
    if freed: log(f'[cleanup] freed {freed / 1e9:.1f} GB after the failure (the extracted game stays for the next try)')
    return freed


def friendly(e, where):
    """the error text the app shows: storage errors say what to do"""
    msg = str(e)
    if (isinstance(e, OSError) and e.errno == errno.ENOSPC) or 'No space left' in msg or 'disk full' in msg.lower():
        return f'The phone ran out of storage during the build ({free_gb(where):.1f} GB free now). Free some space in Settings > General > iPhone Storage and build again: the app keeps what it already unpacked.'
    return msg
