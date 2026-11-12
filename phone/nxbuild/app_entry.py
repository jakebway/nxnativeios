"""nxnativeios: what the builder app calls (PythonBridge.m nxb_python_build). One job folder per build:

  <job>/job.json      {"inputs": [file paths], "ipas": "<IPAs folder>", "shells": "<bundled shells folder>",
                       "upstream_zip": "<bundled nxnative.zip>", "upstream": "<writable folder for it>", "options": {...}}
  <job>/log.txt       every line of the build, as it comes (the app shows it)
  <job>/status.json   {"state": "running"|"done"|"failed", "stage": ..., "progress": 0..1, "ipa": ..., "error": ...}

Inputs are .zip files and/or single files (no folder picker): keys are the file named prod.keys (else the one *.keys file), the game
is every .nsp/.xci/.nsz/.xcz (base game, update, DLC), or one .nup file (needs no keys).
"""
import threading, io, json, os, re, shutil, subprocess, sys, time, traceback, zipfile
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


DEFAULT_WEIGHTS = {'unpack': 150, 'check': 10}   # seconds, until the app has timed a build of its own
GUESS = 90                                         # a stage nothing is known about


def stage_key(name):
    """'unpack v131072' -> 'unpack', 'shader split (3 of 7)' -> 'shader split': the stage without its numbers, to compare builds"""
    return re.sub(r'\s+', ' ', re.sub(r'\(?\bv?\d[\w.]*\b\)?|\bof\b', ' ', name or '')).strip().lower()


class Job:
    def __init__(self, d):
        self.dir = Path(d); self.cfg = json.loads((self.dir / 'job.json').read_text())
        self.logf = open(self.dir / 'log.txt', 'a', buffering=1, encoding='utf-8')
        self.story = open(self.dir / 'story.txt', 'a', buffering=1, encoding='utf-8')   # the lines the app shows: the build's own story, small however long the full log grows
        self.status = {'state': 'running', 'stage': 'starting', 'progress': 0.0}
        self.t0 = time.time()
        self.times_file = Path(self.cfg['upstream']).parent / 'stage_times.json'   # how long each stage took in earlier builds
        try: self.hist = json.loads(self.times_file.read_text())
        except (OSError, ValueError): self.hist = dict(DEFAULT_WEIGHTS)
        self.done_stages = {}       # key -> seconds, this build
        self.stage_t0 = None; self.frac = 0.0
        self._last_set = 0.0
        self._lock = threading.RLock()

    _QUIET = ('[', 'progress: ', 'frame step', 'function patch', 'shaders: ', 'main {', 'subsdk0 {', 'sdk {', '  File ', '    File ')

    def log(self, line):
        self.logf.write(line.rstrip('\n') + '\n')
        if line.startswith('[RED]') or (line.strip() and not line.startswith(self._QUIET) and '"ev": "progress"' not in line): self.story.write(line.rstrip('\n') + '\n')
        if line.startswith('{"ev"'): self._event(line)
        elif line.startswith('progress: '):
            m = re.match(r'progress: (\d+)/(\d+)\s*$', line)
            if m and int(m.group(2)):
                a, b = int(m.group(1)), int(m.group(2)); self.frac = min(1.0, a / b)
                el = time.time() - (self.stage_t0 or time.time())
                self.status.update(detail=f'{a:,} of {b:,}', eta=(el * (1 - self.frac) / self.frac) if self.frac > 0.02 else None)
                self.set(progress=self._overall())

    def _event(self, line):   # the NSP script's --progress json events
        try: ev = json.loads(line)
        except ValueError: return
        try: self._event2(ev)
        except Exception: pass   # a progress event must never stop a build

    def _weight(self, key):
        return float(self.hist.get(key) or GUESS)

    def _overall(self):
        """Fraction of the whole build: stages are weighted by how long they took before (the first build guesses), the running stage by its own progress."""
        st = self.status; n = st.get('n') or 1; key = st.get('key') or ''
        done = sum(self.done_stages.values()) if False else sum(self._weight(k) for k in self.done_stages)
        cur = self._weight(key) if key else 0.0
        left = max(0, n - len(self.done_stages) - (1 if key else 0))
        known = [self._weight(k) for k in self.hist if k] or [GUESS]
        total = done + cur + left * (sum(known) / len(known))
        return min(0.995, (done + cur * min(self.frac, 1.0)) / total) if total else 0.0

    def _event2(self, ev):
        kind = ev.get('ev'); k, n = ev.get('k'), ev.get('n') or self.status.get('n')
        if kind == 'stage' and stage_key(ev.get('name')) == 'rewrite':
            self.free('input/game', 'the game file copy (its contents are unpacked)')
        if kind == 'stage_end' and stage_key(ev.get('name')).startswith('ios shaders'):
            for d in (self.dir / 'build').glob('*/shader/pkg*'): self.free(d, 'the shader package')
        if kind == 'stage':
            key = stage_key(ev.get('name')); self.frac = 0.0; self.stage_t0 = time.time(); self.stage_total = None
            self.status.update(stage=ev.get('name') or self.status['stage'], key=key, k=k, n=n, step='', detail='', eta=None)
            self.set(progress=self._overall())
        elif kind == 'step':
            self.set(step=ev.get('step') or '')
        elif kind == 'stage_end':
            key = stage_key(ev.get('name')); self.done_stages[key] = float(ev.get('elapsed') or 0); self.frac = 1.0
            self.status['key'] = ''
            self.set(progress=self._overall(), detail='', eta=None)
        elif kind == 'progress':
            done, total = ev.get('done'), ev.get('total')
            if total: self.stage_total = (total, ev.get('unit') or '')   # an estimate from the stage's first event, kept for the ones that omit it
            elif done is not None and getattr(self, 'stage_total', None) and done <= self.stage_total[0] * 1.5:
                total = self.stage_total[0]; ev = dict(ev, unit=self.stage_total[1])
            frac = ev.get('frac')
            if frac is None and total and done is not None: frac = min(done / total, 0.99)
            if frac is not None: self.frac = frac
            unit = ev.get('unit') or ''
            detail = (f'{done:,} / {total:,} {unit}' if total and done is not None else f'{done:,} {unit}' if done is not None else '').strip()
            if unit == 'B' and done is not None: detail = f'{done / 1e9:.1f} / {total / 1e9:.1f} GB' if total else f'{done / 1e9:.1f} GB'
            eta = ev.get('eta')
            if eta is None and frac and frac > 0.02 and self.stage_t0: eta = (time.time() - self.stage_t0) * (1 - frac) / frac
            if time.time() - self._last_set >= 1.0:   # the app polls once a second
                self._last_set = time.time()
                self.set(progress=self._overall(), detail=detail, eta=eta, step=ev.get('step') or self.status.get('step', ''))

    def free(self, what, note):
        """Disk space back as soon as nothing needs a file any more: a big game takes 100 GB of work files if they all stay until the end."""
        try:
            p = self.dir / what if isinstance(what, str) else what
            n = sum(f.stat().st_size for f in p.rglob('*') if f.is_file()) if p.is_dir() else (p.stat().st_size if p.exists() else 0)
            shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
            if n: self.log(f'[cleanup] freed {n / 1e9:.1f} GB: {note}')
        except Exception: pass

    def finish_times(self):
        """Remember how long each stage took, for the next build's progress bar."""
        try:
            h = dict(self.hist)
            for k, v in self.done_stages.items():
                if v > 0: h[k] = round(v, 1)
            self.times_file.write_text(json.dumps(h))
        except OSError: pass

    def set(self, **kw):
        """status.json for the app: written under a lock (the heartbeat thread and the build both write), and a failed write never reaches the build."""
        with self._lock:
            self.status.update(kw); self.status['elapsed'] = round(time.time() - self.t0)
            try:
                tmp = self.dir / 'status.json.tmp'; tmp.write_text(json.dumps(self.status)); os.replace(tmp, self.dir / 'status.json')
            except OSError: pass


_KEEP = []

def _trace_exits(job):
    """A build that ends without any error was ended by something calling exit, or by the system. Log who calls exit, and where the build is, so the last lines say."""
    import ctypes, traceback
    me = threading.get_ident()
    def stamp(tag):
        try:
            for tid, fr in sys._current_frames().items():
                job.logf.write(f'[where] {tag}: thread {tid}\n' + ''.join(traceback.format_stack(fr)[-5:])); job.logf.flush()
        except Exception: pass
    real_exit = os._exit
    def _exit(code=0): stamp(f'os._exit({code})'); real_exit(code)
    os._exit = _exit
    try:
        cb = ctypes.CFUNCTYPE(None)(lambda: stamp('C exit() called')); _KEEP.append(cb)
        ctypes.CDLL(None).atexit(cb)
    except Exception: pass
    def loop():   # where the build is, with the time: on every change of position and at least every 10 s, for the whole build, so the last line dates the end
        last, t = None, 0.0
        try: f = ctypes.CDLL(None).os_proc_available_memory; f.restype = ctypes.c_size_t
        except (OSError, AttributeError): f = None
        while True:
            from . import shim as _shim
            time.sleep(0.05 if time.time() < _shim.FAST_UNTIL else 0.5)
            try:
                fr = sys._current_frames().get(me)
                pos = 'build thread gone' if fr is None else ' < '.join(f'{Path(x.filename).name}:{x.lineno} {x.name}' for x in reversed(traceback.extract_stack(fr)[-3:]))
                if pos != last or time.time() - t >= 10:
                    job.logf.write(f'[where {time.strftime("%H:%M:%S")}] {pos}' + (f' | {f() / 1e6:,.0f} MB free' if f else '') + f' | {threading.active_count()} threads\n'); job.logf.flush()
                    last, t = pos, time.time()
            except Exception: pass
    threading.Thread(target=loop, daemon=True).start()


def watch_memory(job):
    """A line in the log when the phone's free memory for this app changes much: an app that is closed for memory leaves no error, only this."""
    import ctypes, resource, threading
    try:
        f = ctypes.CDLL(None).os_proc_available_memory; f.restype = ctypes.c_size_t
    except (OSError, AttributeError): return
    def loop():
        last = None; t = 0
        while True:
            try:
                free = f() / 1e6; peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6
                if last is None or abs(free - last) > 250 or time.time() - t > (10 if free < 1500 else 120):
                    job.log(f'[memory] {free:,.0f} MB free for this app, peak {peak:,.0f} MB'); last = free; t = time.time()
            except Exception: pass
            time.sleep(5)
    threading.Thread(target=loop, daemon=True).start()
    def beat():   # status.json is also rewritten once a second, so the phone's clock and estimate never freeze between events
        while True:
            time.sleep(1)
            try: job.set()
            except Exception: pass
    threading.Thread(target=beat, daemon=True).start()


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
    import signal   # the tools install a SIGTERM handler; off the interpreter's main thread that raises, and there is nothing to terminate here anyway
    _sig = signal.signal
    def _safe_signal(num, handler):
        try: return _sig(num, handler)
        except ValueError: return signal.SIG_DFL
    signal.signal = _safe_signal
    watch_memory(job)
    try:   # a crash in native code leaves no Python error: its message and the Python stacks go to the log instead
        import faulthandler
        faulthandler.enable(file=job.logf, all_threads=True)
        os.dup2(job.logf.fileno(), 2); os.dup2(job.logf.fileno(), 1)
        job.log('[crash log on]')
        _trace_exits(job)
    except Exception as e: job.log(f'[crash log off: {e}]')
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
        job.finish_times()
        job.set(state='done', stage='done', progress=1.0, ipa=str(dst), detail='', eta=None)
        job.log(f'done: {dst.name}')
        return 0
    except BaseException as e:
        job.log(traceback.format_exc()); job.set(state='failed', error=str(e)); return 1
    finally:
        sys.stdout, sys.stderr = so, se
        shutil.rmtree(job.dir / 'input/keys', ignore_errors=True)   # never keep a copy of the keys
