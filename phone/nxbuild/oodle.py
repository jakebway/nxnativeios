"""The Mac host's decoder step, on the phone.

nxnative decodes Oodle-compressed game files (Unreal pak shader archives, Trinity packs, PlatinumGames PKZ archives, Unreal IoStore) and LZ5 ones (DRAGON QUEST XI S) by running the
game's own statically linked decoder in its Mac host (dm/host/hle_oodle.c): either as a job file (DM_OODLE_JOB) or as a request / answer pipe (DM_OODLE_SERVE). A phone cannot run
that code. Oodle's block format is fixed, so Oodle.framework (native/Oodle: ooz, and LZ5 2.0.1's own decoder) decodes the same bytes, and this module stands in for the host:

  host_marker()            the file build_mac_host's result names (the scripts fingerprint it, and the shim runs "it" as a process)
  Process                  what subprocess.Popen([host, modules], env={DM_OODLE_SERVE: 1}) gives: stdin takes requests (u64 compressed length, u64 raw length, the bytes), stdout gives
                           the answers (u64 bytes decoded, 0 on failure, then the bytes). One conversation per thread, so a pool of threads can share one process object
  run_job(job path, log)   DM_OODLE_JOB: "DMOJ", u32 count, then per record u32 compressed length, u32 raw length and the bytes -> <job>.out: "DMOR", u32 count, per record u32 length (0 failed), bytes
"""
import ctypes, os, struct, sys, threading
from pathlib import Path

HOST_NAME = 'dmhost_oodle'      # the file name the shim recognises as "the Mac host"
VERSION = 'nxb-oodle-1'         # in the marker file: a change in what the decoder produces changes the scripts' cache keys
PAD = 0x40080                   # nxb_oodle_decompress_padded: output room past the raw length
_lib = None
_lock = threading.Lock()


def lib():
    global _lib
    with _lock:
        if _lib is None:
            from . import shim
            p = os.environ.get('NXB_OODLE_LIB')
            L = ctypes.CDLL(p) if p else shim._lib('Oodle')
            for name, cap in (('nxb_oodle_decompress_padded', None), ('nxb_oodle_decompress', None), ('nxb_lz5_decompress', None)):
                f = getattr(L, name); f.restype = ctypes.c_int64; f.argtypes = [ctypes.c_char_p, ctypes.c_int64, ctypes.c_void_p, ctypes.c_int64]
            _lib = L
        return _lib


def kind(comp):
    """'oodle' for a stream that starts with an Oodle block header (0x8C / 0xCC, then the decoder: 5 LZNA, 6 Kraken, 10 Mermaid / Selkie, 11 BitKnit, 12 Leviathan), 'lz5' for a level byte
    (10..49) of LZ5 2.0.1 (DRAGON QUEST XI S: 0x2d), else None. Level 12 is both a level and Oodle's first byte: the second byte then says which."""
    if len(comp) < 2: return None
    a, b = comp[0], comp[1] & 0x7F
    if (a & 0x0F) == 0x0C and ((a >> 4) & 3) == 0 and b in (5, 6, 10, 11, 12): return 'oodle'
    if 10 <= a <= 49: return 'lz5'
    return None


def decode(comp, n):
    """The raw bytes of a compressed stream n bytes long once decoded, or None when it does not decode to exactly n"""
    if n == 0: return b''
    k = kind(comp)
    if k is None: return None
    L = lib()
    buf = bytearray(n + PAD)
    ptr = ctypes.addressof((ctypes.c_char * len(buf)).from_buffer(buf))
    comp = bytes(comp)
    got = L.nxb_oodle_decompress_padded(comp, len(comp), ptr, n) if k == 'oodle' else L.nxb_lz5_decompress(comp, len(comp), ptr, n)
    if got != n: return None
    del buf[n:]
    return bytes(buf)


def host_marker(out):
    """The stand-in for the built Mac host: a small file named HOST_NAME under out. Returns its path"""
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    p = out / HOST_NAME
    p.write_text(VERSION + '\nthe decoder step of the Mac host, done by Oodle.framework on the phone\n')
    return p


class _In:
    def __init__(self, proc): self.p = proc
    def write(self, b): self.p._state().inb.extend(b); return len(b)
    def flush(self): self.p._serve()
    def close(self): self.p.returncode = 0 if self.p.returncode is None else self.p.returncode
    closed = property(lambda s: s.p.returncode is not None)


class _Out:
    def __init__(self, proc): self.p = proc
    def read(self, n=-1):
        s = self.p._state()
        if n is None or n < 0: n = len(s.outb)
        b = bytes(s.outb[:n]); del s.outb[:n]
        return b
    def close(self): pass


class Process:
    """The Mac host in DM_OODLE_SERVE mode as a subprocess.Popen object. A request is answered when the writer flushes; what it asked for is read back from stdout."""
    def __init__(self, args, stderr=None, log=None):
        self.args, self.returncode, self.pid = list(args), None, 2147483001
        self.stdin, self.stdout, self.stderr = _In(self), _Out(self), None
        self._err, self._log = stderr, log
        self._tl = threading.local()
        self.requests = self.failed = 0

    def _state(self):
        s = self._tl
        if not hasattr(s, 'inb'): s.inb, s.outb = bytearray(), bytearray()
        return s

    def _say(self, text):
        if self._err is not None and hasattr(self._err, 'write'):
            try: self._err.write(text.encode()); self._err.flush()
            except Exception: pass
        if self._log: self._log(text.rstrip('\n'))

    def _serve(self):
        s = self._state()
        while len(s.inb) >= 16:
            cl, rl = struct.unpack_from('<QQ', s.inb)
            if cl > 1 << 32 or rl > 1 << 32: self._say(f'[RED] DM_OODLE_SERVE: request too large ({cl:#x} -> {rl:#x})\n'); s.inb.clear(); s.outb += struct.pack('<Q', 0); return
            if len(s.inb) < 16 + cl: return          # the rest of the request has not been written yet
            comp = bytes(s.inb[16:16 + cl]); del s.inb[:16 + cl]
            raw = None
            try: raw = decode(comp, rl)
            except Exception as e: self._say(f'[RED] DM_OODLE_SERVE: {e!r}\n')
            self.requests += 1
            if raw is None:
                self.failed += 1
                if self.failed <= 8: self._say(f'[RED] DM_OODLE_SERVE: request {self.requests - 1} ({cl} -> {rl} bytes) failed (the stream does not decode to that length; first bytes {comp[:4].hex()})\n')
                s.outb += struct.pack('<Q', 0)
            else: s.outb += struct.pack('<Q', len(raw)) + raw

    def poll(self): return self.returncode
    def wait(self, timeout=None):
        if self.returncode is None: self.returncode = 0
        return self.returncode
    def kill(self): self.returncode = -9 if self.returncode is None else self.returncode
    terminate = kill
    def send_signal(self, sig): self.kill()
    def communicate(self, input=None, timeout=None): self.wait(); return b'', b''
    def __enter__(self): return self
    def __exit__(self, *e): self.wait()


def run_job(job, log=None):
    """DM_OODLE_JOB: decode every record of the job file into <job>.out. -> 0, or 1 when a record failed (as the host exits)"""
    say = log or (lambda s: None)
    with open(job, 'rb') as f:
        if f.read(4) != b'DMOJ': say(f'[RED] DM_OODLE_JOB: {job} is not a job file'); return 1
        n = struct.unpack('<I', f.read(4))[0]
        outp = str(job) + '.out'
        bad = 0; total = 0
        with open(outp, 'wb') as o:
            o.write(b'DMOR' + struct.pack('<I', n))
            for i in range(n):
                cl, rl = struct.unpack('<II', f.read(8))
                comp = f.read(cl)
                if len(comp) != cl: say(f'[RED] DM_OODLE_JOB: record {i} ends early'); return 1
                raw = None
                try: raw = decode(comp, rl)
                except Exception as e: say(f'[RED] DM_OODLE_JOB: record {i}: {e!r}')
                if raw is None and rl != 0:
                    bad += 1
                    if bad <= 8: say(f'[RED] DM_OODLE_JOB: record {i} ({cl} -> {rl} bytes) failed (first bytes {comp[:4].hex()})')
                    o.write(struct.pack('<I', 0))
                else:
                    raw = raw or b''; o.write(struct.pack('<I', len(raw))); o.write(raw); total += len(raw)
    say(f'DM_OODLE_JOB: {n - bad} records decoded on the phone ({bad} failed, {total / 1048576:.1f} MB out) -> {outp}')
    return 1 if bad else 0
