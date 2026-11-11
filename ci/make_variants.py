#!/usr/bin/env python3
"""Install-failure bisect: from the full .app build smaller IPAs. Usage: make_variants.py <full.ipa> <outdir>
  A  Python.framework only (no extra frameworks, no python/ app/ app_packages/ Resources/)
  B  A + the Python module frameworks (no _test*/xxlimited*)
  C  A + NxTools, SpirvCross, capstone
  D  full app, but without UIBackgroundModes and without Resources/ (the 96 MB nxnative.zip and shells)"""
import plistlib, shutil, subprocess, sys, zipfile, tempfile
from pathlib import Path
ipa, out = Path(sys.argv[1]), Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
NATIVE = {'NxTools.framework', 'SpirvCross.framework', 'capstone.framework', 'Python.framework'}
def build(name, keep_fw, drop_dirs=(), no_bg=False):
    with tempfile.TemporaryDirectory() as t:
        t = Path(t); zipfile.ZipFile(ipa).extractall(t)
        app = next((t / 'Payload').glob('*.app'))
        for f in list((app / 'Frameworks').iterdir()):
            if not keep_fw(f.name): shutil.rmtree(f)
        for d in drop_dirs: shutil.rmtree(app / d, ignore_errors=True)
        if no_bg:
            p = plistlib.loads((app / 'Info.plist').read_bytes()); p.pop('UIBackgroundModes', None)
            (app / 'Info.plist').write_bytes(plistlib.dumps(p))
        dst = (out / f'NXBuilder-{name}.ipa').resolve()
        dst.unlink(missing_ok=True)
        subprocess.run(['zip', '-qr', '-y', str(dst), 'Payload'], cwd=t, check=True)
        print(name, dst.stat().st_size)
junk = lambda n: n.startswith(('_test', 'xxlimited', '_xxtest'))
build('A', lambda n: n == 'Python.framework', ['python', 'app', 'app_packages', 'Resources'])
build('B', lambda n: n == 'Python.framework' or (n not in NATIVE and not junk(n)), ['Resources'])
build('C', lambda n: n in NATIVE, ['python', 'app', 'app_packages', 'Resources'])
build('D', lambda n: True, ['Resources'], no_bg=True)
