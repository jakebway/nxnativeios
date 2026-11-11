"""nxnativeios: what the builder app calls (PythonBridge.m nxb_python_build). One job folder per build:

  <job>/job.json      {"inputs": [file paths], "ipas": "<IPAs folder>", "shells": "<bundled shells folder>",
                       "upstream_zip": "<bundled nxnative.zip>", "upstream": "<writable folder for it>", "options": {...}}
  <job>/log.txt       every line of the build, as it comes (the app shows it)
  <job>/status.json   {"state": "running"|"done"|"failed", "stage": ..., "progress": 0..1, "ipa": ..., "error": ...}

Inputs are .zip files and/or single files (no folder picker): keys are the file named prod.keys (else the one *.keys file), the game
is every .nsp/.xci/.nsz/.xcz (base game, update, DLC), or one .nup file (needs no keys).
"""
import io, json, os, re, shutil, subprocess, sys, time, traceback, zipfile
from pathlib import Path

GAME_EXT = ('.nsp', '.xci', '.nsz', '.xcz', '.nup')   # .nup: a Switch 2 game in one NUP container (base, updates, DLC); it needs no keys


class Joined(io.RawIOBase):
    """Several files read as one: the parts of a split zip (game.zip.001, .002, ... or game.z01, game.z02, ..., game.zip)."""
    def __init__(self, paths):
        self.f = [open(p, 'rb') for p in paths]
        self.sizes = [os.path.getsize(p) for p in paths]
        self.starts = [sum(self.sizes[:i]) for i in range(len(paths))]
        self.total = sum(self.sizes); self.pos = 0
    def readable(self): return True
    def seekable(self): return True
    def tell(self): return self.pos
    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else self.pos + off if whence == 1 else self.total + off
        self.pos = max(0, self.pos); return self.pos
    def readinto(self, b):
        n = 0; mv = memoryview(b)
        while n < len(b) and self.pos < self.total:
            i = max(j for j in range(len(self.f)) if self.starts[j] <= self.pos)
            self.f[i].seek(self.pos - self.starts[i])
            got = self.f[i].readinto(mv[n:n + min(len(b) - n, self.starts[i] + self.sizes[i] - self.pos)])
            if not got: break
            n += got; self.pos += got
        return n
    def close(self):
        for f in self.f: f.close()
        super().close()


def split_groups(inputs):
    """([(group name, [part paths in order])], [other inputs]): game.zip.001/.002/..., or game.z01/game.z02/... with game.zip last."""
    parts, rest = {}, []
    for p in map(Path, inputs):
        m = re.fullmatch(r'(.+)\.zip\.(\d{3})', p.name, re.I) or re.fullmatch(r'(.+)\.z(\d{2})', p.name, re.I)
        if m: parts.setdefault((p.parent, m.group(1)), []).append((int(m.group(2)), p))
        else: rest.append(p)
    groups = []
    for (d, name), lst in parts.items():
        lst.sort(key=lambda t: t[0]); paths = [p for _, p in lst]
        last = next((q for q in rest if q.parent == d and q.name.lower() == name.lower() + '.zip'), None)
        if last is not None: rest.remove(last); paths.append(last)   # spanned zip: the .zip is the last part
        nums = [n for n, _ in lst]
        if nums != list(range(nums[0], nums[0] + len(nums))) or nums[0] not in (0, 1):
            raise RuntimeError(f'{name}: some parts of the split zip are missing (have {", ".join(p.name for p in paths)})')
        groups.append((name, paths))
    return groups, rest


def open_split_zip(paths):
    """A ZipFile over the parts. A spanned zip (.z01, .z02, .zip) keeps each entry's offset relative to its own part: made absolute here."""
    j = Joined([str(p) for p in paths]); z = zipfile.ZipFile(j)
    if any(zi.volume for zi in z.infolist()):
        last = j.starts[-1]
        for zi in z.infolist():   # zipfile took the last part's start as the base of every offset
            zi.header_offset += j.starts[min(zi.volume, len(paths) - 1)] - last
    return z


class Job:
    def __init__(self, d):
        self.dir = Path(d); self.cfg = json.loads((self.dir / 'job.json').read_text())
        self.logf = open(self.dir / 'log.txt', 'a', buffering=1, encoding='utf-8')
        self.status = {'state': 'running', 'stage': 'starting', 'progress': 0.0}

    def log(self, line):
        self.logf.write(line.rstrip('\n') + '\n')
        if line.startswith('{"ev"'): self._event(line)

    def _event(self, line):   # the NSP script's --progress json events
        try: ev = json.loads(line)
        except ValueError: return
        k, n = ev.get('k'), ev.get('n') or self.status.get('n')
        if ev.get('ev') == 'stage': self.set(stage=ev.get('name') or self.status['stage'], k=k, n=n, progress=((k or 1) - 1) / n if n else 0.0)
        elif ev.get('ev') == 'progress' and ev.get('total') and self.status.get('n'):
            self.set(progress=min(1.0, ((self.status.get('k') or 1) - 1 + ev['done'] / ev['total']) / self.status['n']))

    def set(self, **kw):
        self.status.update(kw)
        tmp = self.dir / 'status.json.tmp'; tmp.write_text(json.dumps(self.status)); os.replace(tmp, self.dir / 'status.json')


def ensure_upstream(zip_path, dest, log):
    """nxnative's scripts and profiles, unpacked once into a writable folder (the script writes into the profiles; the app bundle is read-only)."""
    dest = Path(dest); stamp = dest / '.nxb_stamp'
    want = f'{os.path.getsize(zip_path)}:{int(os.path.getmtime(zip_path))}'
    if stamp.is_file() and stamp.read_text() == want: return dest
    log('unpacking nxnative (first launch after an install or update)')
    tmp = dest.with_name(dest.name + '.tmp'); shutil.rmtree(tmp, ignore_errors=True)
    with zipfile.ZipFile(zip_path) as z: z.extractall(tmp)
    shutil.rmtree(dest, ignore_errors=True); os.replace(tmp, dest); stamp.write_text(want)
    return dest


def gather(job, inputs):
    """Keys and game files from the picked .zip files and single files, into <job>/input/{keys,game}."""
    keys_dir, game_dir = job.dir / 'input/keys', job.dir / 'input/game'
    for d in (keys_dir, game_dir): d.mkdir(parents=True, exist_ok=True)
    def take(name, opener):
        base = os.path.basename(name)
        if base.startswith('._') or base.startswith('.'): return
        low = base.lower()
        dst = keys_dir / base if low.endswith('.keys') else game_dir / base if low.endswith(GAME_EXT) else None
        if dst is None: return
        with opener() as src, open(dst, 'wb') as out: shutil.copyfileobj(src, out, 8 << 20)
        job.log(f'input: {base} ({dst.stat().st_size / 1e6:.0f} MB)')
    from . import rar
    rars, inputs = rar.first_volumes(inputs)
    for arc in rars:
        job.log(f'rar: {arc.name}')
        def want(name):
            base = os.path.basename(name); low = base.lower()
            if base.startswith('.'): return None
            if low.endswith('.keys'): return str(keys_dir / base)
            if low.endswith(GAME_EXT): return str(game_dir / base)
            return None
        for name, dst in rar.extract(arc, want): job.log(f'input: {os.path.basename(dst)} ({os.path.getsize(dst) / 1e6:.0f} MB)')
    groups, inputs = split_groups(inputs)
    for name, paths in groups:
        job.log(f'split zip: {name} ({len(paths)} parts)')
        with open_split_zip(paths) as z:
            for zi in z.infolist():
                if not zi.is_dir(): take(zi.filename, lambda zi=zi: z.open(zi))
    for p in inputs:
        p = Path(p)
        if p.suffix.lower() == '.zip':
            with zipfile.ZipFile(p) as z:
                for zi in z.infolist():
                    if not zi.is_dir(): take(zi.filename, lambda zi=zi: z.open(zi))
        else: take(str(p), lambda p=p: open(p, 'rb'))
    keys = sorted(keys_dir.glob('*.keys'), key=lambda k: (k.name.lower() != 'prod.keys', k.name))
    if not keys and any(f.suffix.lower() == '.nup' for f in game_dir.iterdir()):
        if not any(game_dir.iterdir()): raise RuntimeError('no game file among the files')
        return None, game_dir   # a NUP carries no encryption: no keys
    if not keys: raise RuntimeError('no prod.keys among the files (a .keys file, alone or inside a .zip)')
    if not any(game_dir.iterdir()): raise RuntimeError('no game file among the files (.nsp, .xci, .nsz or .xcz, alone or inside a .zip)')
    if len(keys) > 1:   # prod.keys + title.keys (same "name = hex" lines): one combined file, prod.keys first
        merged = keys_dir / 'combined.keys'
        with open(merged, 'wb') as out:
            for k in keys:
                out.write(k.read_bytes().rstrip() + b'\n')
        job.log(f'keys: {" + ".join(k.name for k in keys)}')
        return merged, game_dir
    return keys[0], game_dir


def base_title(keys, game_dir, log):
    """The base game's title ID, by nx_extract --contents (the NSP script reads the same lines)"""
    from . import shim
    nups = [f for f in sorted(game_dir.iterdir()) if f.suffix.lower() == '.nup']
    if nups:   # a Switch 2 game: the NUP names its own title ID
        sys.path.insert(0, os.path.join(os.environ['NXB_UPSTREAM'], 'scripts'))
        import pack_nup
        app, *_ = pack_nup.scan(pack_nup.Nup(nups[0]))
        return f'{app:016X}'
    files = [str(f) for f in sorted(game_dir.iterdir()) if f.suffix.lower() in ('.nsp', '.xci')]
    if not files: return None   # NSZ / XCZ: the script converts them first; the shell is checked when the IPA is assembled
    r = subprocess.run(['/nxnativeios/nx_extract', str(keys), '--contents', *files], capture_output=True, text=True)
    tids = [l.split()[2] for l in r.stdout.splitlines() if l.startswith('content Application ')]
    for l in r.stdout.splitlines():
        if l.startswith('[RED]'): log(l)
    return tids[0].upper() if tids else None


def run(job_dir):
    job = Job(job_dir)
    so, se = sys.stdout, sys.stderr
    class W:   # the script's prints and progress events go to the log
        def write(self, s):
            for l in s.splitlines():
                if l.strip(): job.log(l)
            return len(s)
        def flush(self): pass
    sys.stdout = sys.stderr = W()
    try:
        c = job.cfg
        os.environ['NXB_UPSTREAM'] = str(ensure_upstream(c['upstream_zip'], c['upstream'], job.log))
        from . import capfix, shim, driver
        capfix.prepare(job.log)
        shim.install(log=job.log)
        job.set(stage='reading your files')
        keys, game_dir = gather(job, c['inputs'])
        tid = base_title(keys, game_dir, job.log)
        shells = Path(c['shells'])
        if tid:
            job.log(f'game: {tid}')
            if not (shells / f'shell-{tid}.zip').is_file():
                raise RuntimeError(f'no player shell for {tid} in this build of the app: add the title ID to the "Player shells" workflow, then rebuild the app')
        os.environ['NXB_SHELLS'] = str(shells)
        o = c.get('options', {})
        extra = []
        if o.get('language'): extra += ['--language', o['language']]
        if 'show_fps' in o: extra += ['--show-fps' if o['show_fps'] else '--no-show-fps']
        job.set(stage='building')
        rc = driver.build(game_dir, keys, None, job.dir, log=job.log, extra=extra)
        ipas = sorted(job.dir.glob('*.ipa'), key=lambda p: p.stat().st_mtime)
        if rc != 0 or not ipas:
            reds = [l for l in (job.dir / 'log.txt').read_text(errors='replace').splitlines() if '[RED]' in l]
            raise RuntimeError(reds[-1].split('[RED]', 1)[1].strip().strip('"}') if reds else f'the build stopped (exit code {rc})')
        out = Path(c['ipas']); out.mkdir(parents=True, exist_ok=True)
        dst = out / ipas[-1].name; os.replace(ipas[-1], dst)
        if not o.get('keep_build'): shutil.rmtree(job.dir / 'build', ignore_errors=True); shutil.rmtree(job.dir / 'input', ignore_errors=True)
        job.set(state='done', stage='done', progress=1.0, ipa=str(dst))
        job.log(f'done: {dst.name}')
        return 0
    except BaseException as e:
        job.log(traceback.format_exc()); job.set(state='failed', error=str(e)); return 1
    finally:
        sys.stdout, sys.stderr = so, se
        shutil.rmtree(job.dir / 'input/keys', ignore_errors=True)   # never keep a copy of the keys
