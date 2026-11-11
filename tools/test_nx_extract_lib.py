#!/usr/bin/env python3
"""Call nx_extract_main in the macOS build of NxExtract (same sources as the iOS framework): --source-sha must match
build_ipa_from_nsp.py's nx_extract_source_sha, and no arguments must print the usage and return 2."""
import ctypes, hashlib, sys
from pathlib import Path
lib = ctypes.CDLL(sys.argv[1]); up = Path(sys.argv[2])
LOG = ctypes.CFUNCTYPE(None, ctypes.c_char_p, ctypes.c_void_p)
lines = []; cb = LOG(lambda s, c: lines.append(s.decode()))
f = lib.nx_extract_main; f.restype = ctypes.c_int
f.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_char_p), LOG, ctypes.c_void_p]
def run(*a):
    lines.clear(); argv = (ctypes.c_char_p * max(1, len(a)))(*[x.encode() for x in a]); return f(len(a), argv, cb, None), list(lines)
rc, out = run('--source-sha')
want = hashlib.sha256((up / 'dm/tools/nx_extract/Program.cs.orig').read_bytes() + (up / 'dm/tools/nx_extract/nx_extract.csproj').read_bytes()).hexdigest()[:16]
print('source-sha', rc, out, 'want', want)
assert rc == 0 and out == [want]
rc, out = run()
print('no args ->', rc, out[:1])
assert rc == 2 and out and out[0].startswith('usage: nx_extract')
print('OK')
