#!/usr/bin/env python3
"""The shim against nxnative's own scripts and tools. Usage: test_shim.py <nxnative checkout> [<.spv file>]
NXB_FRAMEWORKS: a folder with libSpirvCross.dylib (and libNxTools.dylib on a Mac) for the native-tool tests."""
import os, subprocess, sys, tempfile, textwrap
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, '..'))
from nxbuild import shim
up = os.path.abspath(sys.argv[1]); spv = sys.argv[2] if len(sys.argv) > 2 else None
lines = []; shim.install(log=lines.append)
ok = True
def check(name, cond, detail=''):
    global ok; ok &= bool(cond); print(('ok  ' if cond else 'FAIL'), name, detail if not cond else '')

d = tempfile.mkdtemp()
# 1. a Python script: argv, env, cwd, exit code, stdout PIPE as text, stderr merged
s = os.path.join(d, 'child.py')
open(s, 'w').write(textwrap.dedent('''
    import os, sys
    print('argv', sys.argv[1:]); print('env', os.environ.get('NXB_T')); print('cwd', os.path.basename(os.getcwd()))
    print('to stderr', file=sys.stderr)
    sys.exit(int(sys.argv[1]))'''))
r = subprocess.run([sys.executable, s, '3', 'x'], capture_output=True, text=True, env=dict(os.environ, NXB_T='yes'), cwd=d)
check('python: exit code', r.returncode == 3, r)
check('python: output', "argv ['3', 'x']" in r.stdout and 'env yes' in r.stdout and f'cwd {os.path.basename(d)}' in r.stdout and 'to stderr' in r.stdout, r.stdout)
check('python: env restored', os.environ.get('NXB_T') is None)
check('python: live log', any(l.startswith('argv') for l in lines))
# 2. nested: a script that runs a script; Popen streaming lines (build_ipa_from_nsp.run's way)
s2 = os.path.join(d, 'parent.py')
open(s2, 'w').write(f'import subprocess, sys\nr = subprocess.run([sys.executable, {s!r}, "0", "nested"], capture_output=True, text=True)\nprint("child said", r.stdout.splitlines()[0]); sys.exit(r.returncode)')
p = subprocess.Popen(['python3', s2], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors='replace', bufsize=1)
got = [l.rstrip('\n') for l in p.stdout]; rc = p.wait()
check('nested python + streaming', rc == 0 and got == ["child said argv ['0', 'nested']"], (rc, got))
# 3. an upstream script, in process: game.py lists the profiles
r = subprocess.run([sys.executable, os.path.join(up, 'dm/games/game.py'), 'list'], capture_output=True, text=True)
check('upstream game.py list', r.returncode == 0 and '010015100B514000' in r.stdout, r.stdout[:300])
# 4. the Metal chain: ios_metal.compile writes the MSL source as the library
sys.path.insert(0, os.path.join(up, 'dm/ios/tools')); import ios_metal
msl, air, lib = (os.path.join(d, n) for n in ('s.metal', 's.air', 's.metallib'))
open(msl, 'w').write('#include <metal_stdlib>\nusing namespace metal;\nkernel void k() {}\n')
ios_metal.compile(msl, air, lib)
check('metal chain: library is the MSL', open(lib).read() == open(msl).read())
r = subprocess.run(['xcrun', '-sdk', 'iphoneos', 'metal', '--version'], capture_output=True, text=True)
check('xcrun metal --version', r.returncode == 0 and 'nxnativeios' in r.stdout, r)
# 5. dmsh_side.cut on MSL: every piece the whole source
sys.path.insert(0, os.path.join(up, 'dm/gfx/tools')); import dmsh_side
src = open(lib, 'rb').read()
check('dmsh_side.cut on MSL', dmsh_side.cut(src, {'a'}, {'main0_f'}) == (src, src, src))
# 6. zstd -d through compression.zstd
try: import compression.zstd as z
except ImportError: z = None; print('skip zstd -d (no compression.zstd before Python 3.14; the phone has 3.15)')
if z:
    r = subprocess.run(['zstd', '-d', '-c', '-q'], input=z.compress(b'hello' * 100), capture_output=True)
    check('zstd -d', r.returncode == 0 and r.stdout == b'hello' * 100, r.returncode)
# 7. multiprocessing pools are thread pools
import multiprocessing
with multiprocessing.get_context('fork').Pool(2) as pool: res = pool.starmap(pow, [(2, 3), (3, 2)])
check('fork pool -> threads', res == [8, 9])
# 8. a command that cannot run says so
r = subprocess.run(['make', '-C', '/'], capture_output=True, text=True)
check('unknown command: 127 + message', r.returncode == 127 and 'cannot run on the phone' in r.stdout, r)
# 9. spirv-cross: MSL to stdout comes back through the temporary --output file
if spv and os.environ.get('NXB_FRAMEWORKS'):
    r = subprocess.run(['/x/spirv-cross', spv, '--msl'], capture_output=True, text=True)
    check('spirv-cross MSL on stdout', r.returncode == 0 and '#include <metal_stdlib>' in r.stdout, (r.returncode, r.stdout[:200]))
    r = subprocess.run(['/x/spirv-cross', '/nonexistent.spv', '--msl'], capture_output=True, text=True)
    check('spirv-cross bad input: error, process alive', r.returncode != 0)
print('OK' if ok else 'FAIL'); sys.exit(0 if ok else 1)
