"""Test of the Oodle decoder library (native/Oodle): python3 tools/test_oodle_lib.py <libOodle> <folder of ooz test streams>

Every sample file (dickens, mozilla, ...) exists in several Oodle formats (.kraken .mermaid .selkie .leviathan, each with ooz's 8-byte raw-size header); all of them
must decode to the same bytes, which proves the decoder without the originals. Also checks the library's guards: a short output, garbage, trailing bytes after the last block."""
import collections, ctypes, glob, hashlib, os, struct, sys, time

lib = ctypes.CDLL(sys.argv[1])
f = lib.nxb_oodle_decompress
f.restype = ctypes.c_int64
f.argtypes = [ctypes.c_char_p, ctypes.c_int64, ctypes.c_char_p, ctypes.c_int64]

def decode(comp, n):
    out = ctypes.create_string_buffer(n)
    return f(comp, len(comp), out, n), out.raw

by = collections.defaultdict(dict)
fails = 0
for p in sorted(glob.glob(sys.argv[2] + '/*.*')):
    name, kind = os.path.basename(p).rsplit('.', 1)
    if kind not in ('kraken', 'mermaid', 'selkie', 'leviathan'): continue
    d = open(p, 'rb').read()
    n = struct.unpack_from('<Q', d)[0]; hs = 8
    if n >= 1 << 40: n = struct.unpack_from('<I', d)[0]; hs = 4
    t = time.time(); got, raw = decode(d[hs:], n); dt = time.time() - t
    ok = got == n
    fails += not ok
    by[name][kind] = hashlib.sha1(raw).hexdigest()[:12] if ok else None
    print(f'{os.path.basename(p):22} {len(d):>9} -> {n:>9}  {"ok  " if ok else "FAIL"} {n / dt / 1e6:6.0f} MB/s')
    if kind == 'kraken' and ok and name == 'dickens':
        tail, _ = decode(d[hs:] + b'\0\0\0\0', n)   # bytes after the last block are not an error (the game's own decoder takes them)
        short, _ = decode(d[hs:], n - 1000)         # asked for less than the stream holds: the last block is cut short, never overruns
        junk, _ = decode(bytes(range(256)) * 8, 4096)
        print(f'   trailing bytes: {tail == n}; shorter output: {short in (n - 1000, -1)}; garbage: {junk == -1}')
        fails += (tail != n) + (junk != -1)

if hasattr(lib, 'nxb_lz5_compress'):   # the test build has LZ5's compressor too: a round trip over every level, on text and on binary data
    c, d5 = lib.nxb_lz5_compress, lib.nxb_lz5_decompress
    c.restype = d5.restype = ctypes.c_int64
    c.argtypes = [ctypes.c_char_p, ctypes.c_int64, ctypes.c_char_p, ctypes.c_int64, ctypes.c_int]
    d5.argtypes = [ctypes.c_char_p, ctypes.c_int64, ctypes.c_char_p, ctypes.c_int64]
    texts = [decode(open(sys.argv[2] + '/xml.kraken', 'rb').read()[8:], 5345280)[1][:1 << 20], decode(open(sys.argv[2] + '/mr.kraken', 'rb').read()[8:], 9970564)[1][:1 << 20], b'', b'a', b'abc' * 5000]
    for lv in (10, 11, 12, 13, 14, 15, 20, 21, 22, 23, 24, 25, 30, 31, 32, 33, 34, 35, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49):
        for i, data in enumerate(texts):
            buf = ctypes.create_string_buffer(len(data) + len(data) // 8 + 1024)
            n = c(data, len(data), buf, len(buf), lv)
            if len(data) == 0: continue
            out = ctypes.create_string_buffer(len(data))
            got = d5(buf.raw[:n], n, out, len(data))
            if n <= 0 or got != len(data) or out.raw != data: print(f'LZ5 level {lv} sample {i}: FAIL ({n}, {got})'); fails += 1
    print('LZ5 round trip at 28 levels:', 'ok' if not fails else 'FAILED')
mism = [k for k, v in by.items() if len(set(v.values())) != 1]
for k in mism: print('  ', k, by[k])
print('formats of one file that differ:', mism or 'none', '|', 'failures:', fails)
sys.exit(1 if (mism or fails) else 0)
