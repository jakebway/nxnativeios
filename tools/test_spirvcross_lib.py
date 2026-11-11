#!/usr/bin/env python3
"""Same MSL from libSpirvCross (our build) as from nxnative's pinned spirv-cross executable, for each .spv given; a missing input returns an error instead of ending the process.
Usage: test_spirvcross_lib.py <libSpirvCross dylib> <upstream spirv-cross executable> <file.spv>..."""
import ctypes, os, subprocess, sys, tempfile
lib = ctypes.CDLL(sys.argv[1]); ref = sys.argv[2]
f = lib.spirv_cross_main; f.restype = ctypes.c_int; f.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_char_p)]
def run(*a):
    a = ('spirv-cross',) + a; v = (ctypes.c_char_p * len(a))(*[x.encode() for x in a]); return f(len(a), v)
ok = run('/nonexistent.spv', '--msl') != 0
print('missing input returns an error:', ok)
d = tempfile.mkdtemp()
for spv in sys.argv[3:]:
    for opts in (['--msl', '--msl-version', '30000'], ['--msl', '--msl-ios', '--msl-version', '30000']):
        a, b = os.path.join(d, 'lib.metal'), os.path.join(d, 'ref.metal')
        rc = run(spv, *opts, '--output', a)
        subprocess.run([ref, spv, *opts, '--output', b], check=True)
        same = rc == 0 and open(a, 'rb').read() == open(b, 'rb').read()
        print(os.path.basename(spv), ' '.join(opts), 'same MSL' if same else 'DIFFERENT'); ok &= same
print('OK' if ok else 'FAIL'); sys.exit(0 if ok else 1)
