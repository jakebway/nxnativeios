#!/usr/bin/env python3
"""Call the tools in the macOS build of NxTools (same sources as the iOS framework): each tool's --source-sha must match the hash
nxnative's scripts compute over its original sources, and nx_extract without arguments must print its usage and return 2."""
import ctypes, hashlib, sys
from pathlib import Path
lib = ctypes.CDLL(sys.argv[1]); up = Path(sys.argv[2])
LOG = ctypes.CFUNCTYPE(None, ctypes.c_char_p, ctypes.c_void_p)
lines = []; cb = LOG(lambda s, c: lines.append(s.decode()))
def tool(name):
    f = getattr(lib, name + '_main'); f.restype = ctypes.c_int
    f.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_char_p), LOG, ctypes.c_void_p]
    def run(*a):
        lines.clear(); argv = (ctypes.c_char_p * max(1, len(a)))(*[x.encode() for x in a]); return f(len(a), argv, cb, None), list(lines)
    return run
ok = True
for name, d, proj in (('nx_extract', 'dm/tools/nx_extract', 'nx_extract.csproj'), ('dmsh_xlate', 'dm/gfx/tools/dmsh_xlate', 'dmsh_xlate.csproj')):
    rc, out = tool(name)('--source-sha')
    want = hashlib.sha256((up / d / 'Program_cs.orig').read_bytes() + (up / d / proj).read_bytes()).hexdigest()[:16]
    print(name, 'source-sha', rc, out, 'want', want)
    ok &= rc == 0 and out == [want]
rc, out = tool('nx_extract')()
print('nx_extract no args ->', rc, out[:1])
ok &= rc == 2 and bool(out) and out[0].startswith('usage: nx_extract')
print('OK' if ok else 'FAIL'); sys.exit(0 if ok else 1)
