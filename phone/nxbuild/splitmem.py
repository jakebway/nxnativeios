"""A shader split that fits in a phone's memory.

dm/gfx/tools/shader_split.py holds every shader's code area in memory from the moment it is found until the packages are written: the scan returns each file's shaders to the parent,
the merge keeps all of them, and the writer then builds a copy of each record, a list of the copies, and one more joined copy of each package. Pokémon Pokopia's code areas are 4.4 GB
(131,426 shaders): about three times that at the peak, on a phone that gives the app 6 to 7 GB. A Mac with 64 GB never notices.

This module changes how the split holds them, not what it writes (the output is byte-identical; tools/test_splitmem.py checks that on upstream's own fixtures):

  - the code area of a shader is written to one spill file the moment the scan finds it (SpillList, which stands in for the scan's `found` list), and the entry keeps a Blob: the
    file offset and the length. A Blob reads like the bytes it stands for (len, slices, ==, +, bytes()), one pread at a time. The same code area found twice is stored once
  - the packages are written one record at a time, in the same order, instead of being built whole
  - the spill file lives in the work folder and goes away with the run

transform(source) rewrites shader_split.py's text at the few places that need it, each one an exact anchor: when upstream changes one of them the split runs unmodified (and says so),
because a changed split that is not byte-identical would be worse than a slow one. run(script) executes the (transformed) script as __main__.
"""
import hashlib, os, sys, tempfile, threading

SMALL = int(os.environ.get('NXB_SPILL_MIN', '1024'))   # code areas shorter than this stay bytes

# (name, old text, new text): each old text must occur exactly once
EDITS = [
    ('scan found list',
     "    found = []; trees = {}\n    if len(args) > 2 and args[2][0] == b'ARH1':",
     "    found = _sm.SpillList(globals()); trees = {}\n    if len(args) > 2 and args[2][0] == b'ARH1':"),
    ('ps_inputs reads the first bytes only',
     "    return {i for i in range(32) if struct.unpack_from('<I', code, 0x30 + 4 * (6 + (i >> 2)))[0] >> ((i & 3) * 8) & 0xff}",
     "    code = bytes(code[:0x80])\n    return {i for i in range(32) if struct.unpack_from('<I', code, 0x30 + 4 * (6 + (i >> 2)))[0] >> ((i & 3) * 8) & 0xff}"),
    ('records are written as they are made',
     "    recs = collections.defaultdict(list); rows = []; facts = {}; stat = collections.Counter()",
     "    recs = {}; pkg_n = collections.Counter(); rows = []; facts = {}; stat = collections.Counter()"),
    ('record from a Blob',
     "rec = bytearray(b'BTCDBTCD' + bytes.fromhex(key) + bytes(0x28)); struct.pack_into('<2I', rec, 0x28, len(ctl), len(code)); rec += code + ctl",
     "rec = bytearray(b'BTCDBTCD' + bytes.fromhex(key) + bytes(0x28)); struct.pack_into('<2I', rec, 0x28, len(ctl), len(code)); rec += bytes(code) + ctl"),
    ('row index and streamed write',
     "rows.append((name, len(recs[name]), STAGE_NAME[st], key, where)); recs[name].append(bytes(rec)); stat[st] += 1",
     "rows.append((name, pkg_n[name], STAGE_NAME[st], key, where)); pkg_n[name] += 1\n        if name not in recs: recs[name] = open(os.path.join(pkg, name), 'wb')\n        recs[name].write(rec); stat[st] += 1"),
    ('no joined copy',
     "    for name, rr in recs.items():\n        with open(os.path.join(pkg, name), 'wb') as f: f.write(b''.join(rr))\n",
     "    for f in recs.values(): f.close()\n    _sm.end(globals())\n"),
]


def transform(src):
    """→ (new source, None) or (src, why it was left as it is)"""
    out = src
    for name, old, new in EDITS:
        if out.count(old) != 1: return src, f'{name}: {out.count(old)} matches'
        out = out.replace(old, new)
    return out, None


class Spill:
    """the spill file and the table of code areas already stored"""
    def __init__(self, directory=None):
        fd, self.path = tempfile.mkstemp(prefix='split-spill-', dir=directory or os.environ.get('NXB_SPILL_DIR') or None)
        self.fd, self.size, self.lock, self.seen = fd, 0, threading.Lock(), {}
        self.stored = self.reused = 0
    def put(self, data):
        with self.lock: off = self.size; self.size += len(data)
        mv, done = memoryview(data), 0
        while done < len(data): done += os.pwrite(self.fd, mv[done:], off + done)
        return Blob(self, off, len(data))
    def get(self, off, n):
        out = bytearray()
        while len(out) < n:
            b = os.pread(self.fd, n - len(out), off + len(out))
            if not b: raise OSError('the split spill file is shorter than its table says')
            out += b
        return bytes(out)
    def close(self):
        try: os.close(self.fd)
        except OSError: pass
        try: os.unlink(self.path)
        except OSError: pass


class Blob:
    """a code area that lives in the spill file, readable like bytes"""
    __slots__ = ('sp', 'off', 'n')
    def __init__(self, sp, off, n): self.sp, self.off, self.n = sp, off, n
    def __len__(self): return self.n
    def __bool__(self): return self.n > 0
    def __bytes__(self): return self.sp.get(self.off, self.n)
    def __getitem__(self, i):
        if isinstance(i, slice):
            a, b, step = i.indices(self.n)
            if step == 1: return self.sp.get(self.off + a, max(0, b - a)) if b > a else b''
            return bytes(self)[i]
        if i < 0: i += self.n
        if not 0 <= i < self.n: raise IndexError('Blob index out of range')
        return self.sp.get(self.off + i, 1)[0]
    def __eq__(self, o):
        if isinstance(o, Blob):
            if o.sp is self.sp and o.off == self.off and o.n == self.n: return True
            if o.n != self.n: return False
            step = 1 << 20
            return all(self.sp.get(self.off + a, min(step, self.n - a)) == o.sp.get(o.off + a, min(step, self.n - a)) for a in range(0, self.n, step))
        if isinstance(o, (bytes, bytearray, memoryview)):
            if len(o) != self.n: return False
            return bytes(self) == bytes(o)
        return NotImplemented
    def __ne__(self, o):
        r = self.__eq__(o); return r if r is NotImplemented else not r
    def __hash__(self): return hash(bytes(self))
    def __add__(self, o): return bytes(self) + bytes(o)
    def __radd__(self, o): return bytes(o) + bytes(self)
    def __iter__(self): return iter(bytes(self))
    def __contains__(self, x): return x in bytes(self)
    def find(self, *a): return bytes(self).find(*a)
    def startswith(self, *a): return bytes(self).startswith(*a)
    def __repr__(self): return f'<Blob {self.n} bytes at {self.off}>'


_spill = None
_spill_lock = threading.Lock()


def spill(directory=None):
    global _spill
    with _spill_lock:
        if _spill is None: _spill = Spill(directory)
        return _spill


class SpillList(list):
    """stands in for the `found` list of scan_file_in: an entry is (where, stage, control section, code area); the code area goes to the spill file as it is added (once per distinct
    key), and the entry that stays holds a Blob. The control sections stay in memory (they are small, and every reader takes slices of them)"""
    def __init__(self, g=None):
        super().__init__()
        self.g = g if g is not None else {}
    def _one(self, t):
        if isinstance(t, tuple) and len(t) == 4 and isinstance(t[3], (bytes, bytearray, memoryview)) and len(t[3]) >= SMALL:
            where, st, ctl, code = t
            sp = spill()
            code = bytes(code)
            try: key = self.g['skey'](bytes(ctl), code)
            except Exception: key = None
            if key is not None:
                with sp.lock: hit = sp.seen.get(key)
                if hit is not None and len(hit) == len(code) and hit == code: sp.reused += 1; return (where, st, ctl, hit)
            blob = sp.put(code); sp.stored += 1
            if key is not None:
                with sp.lock: sp.seen.setdefault(key, blob)
            return (where, st, ctl, blob)
        return t
    def append(self, t): super().append(self._one(t))
    def extend(self, it): super().extend(self._one(t) for t in it)
    def __iadd__(self, it): self.extend(it); return self
    def insert(self, i, t): super().insert(i, self._one(t))


def end(g=None):
    """the packages are written: the spill file is not needed any more"""
    global _spill
    with _spill_lock:
        sp, _spill = _spill, None
    if sp:
        print(f'split spill: {sp.stored:,} code areas stored ({sp.size / 1048576:,.0f} MB), {sp.reused:,} repeats not stored', flush=True)
        sp.close()


def run(script, log=None):
    """run the shader split script as __main__ with the memory-bounded edits; unmodified when an anchor no longer matches"""
    import runpy, types
    src = open(script, encoding='utf-8').read()
    new, why = transform(src)
    if why:
        if log: log(f'[split] memory-bounded split not applied ({why}): upstream changed, running the original')
        return runpy.run_path(script, run_name='__main__')
    g = {'__name__': '__main__', '__file__': script, '__builtins__': __builtins__, '_sm': sys.modules[__name__]}
    try: exec(compile(new, script, 'exec'), g)
    finally: end()
    return g
