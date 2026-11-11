#!/usr/bin/env python3
"""Put CPython and the Python packages into a built .app the way CPython's iOS support expects (PEP 730):
  <app>/python/lib/python3.X/        the standard library (from the XCframework's ios-arm64 slice)
  <app>/app_packages/, <app>/app/    the packages (capstone, lz4) and nxbuild
  every binary module (*.so)          -> <app>/Frameworks/<dotted.name>.framework/<dotted.name> (+ Info.plist, <dotted.name>.origin),
                                         with a <name>.fwork file left in its place naming the binary relative to the app
Usage: install_python.py <app> <Python.xcframework> <app_packages dir> <app code dir>"""
import os, plistlib, shutil, subprocess, sys
from pathlib import Path

app, xcfw, pkgs, code = (Path(a).resolve() for a in sys.argv[1:5])
# the pure-Python stdlib (a pythonX.Y folder holding os.py) and the device's binary modules (ios-arm64 lib-dynload) may sit in different folders of the XCframework
device = lambda p: 'simulator' not in str(p) and 'testbed' not in str(p)
cands = [p.parent for p in xcfw.rglob('os.py') if p.parent.name.startswith('python3') and device(p)]
if not cands: sys.exit(f'[RED] no standard library (pythonX.Y/os.py) in {xcfw}: ' + ' '.join(str(p.relative_to(xcfw)) for p in xcfw.glob('*/*')))
stdlib = sorted(cands, key=lambda p: ('ios-arm64' not in str(p), len(str(p))))[0]
ver = stdlib.name
dyn = [d for d in xcfw.rglob('lib-dynload') if device(d) and ver in str(d)]
print(f'stdlib: {stdlib.relative_to(xcfw)}; lib-dynload: {[str(d.relative_to(xcfw)) for d in dyn]}')
dst_lib = app / 'python/lib' / ver
shutil.rmtree(app / 'python', ignore_errors=True)
shutil.copytree(stdlib, dst_lib, symlinks=False, ignore=shutil.ignore_patterns('__pycache__', 'test', 'tests', 'idlelib', 'tkinter', 'turtledemo', 'ensurepip', '*.a', 'lib-dynload'))
if not dyn: sys.exit('[RED] no device lib-dynload in the XCframework')
shutil.copytree(dyn[0], dst_lib / 'lib-dynload', symlinks=False)
for name, src in (('app_packages', pkgs), ('app', code)):
    shutil.rmtree(app / name, ignore_errors=True); shutil.copytree(src, app / name, ignore=shutil.ignore_patterns('__pycache__'))
fw_root = app / 'Frameworks'; fw_root.mkdir(exist_ok=True)
n = 0
for so in sorted(list(dst_lib.rglob('*.so')) + list((app / 'app_packages').rglob('*.so'))):
    rel = so.relative_to(app)
    if 'lib-dynload' in rel.parts: dotted = so.name.split('.')[0]
    else:
        base = so.parent.relative_to(app / 'app_packages')
        dotted = '.'.join([*base.parts, so.name.split('.')[0]])
    fw = fw_root / f'{dotted}.framework'; fw.mkdir(parents=True, exist_ok=True)
    binpath = fw / dotted
    shutil.move(str(so), binpath)
    subprocess.run(['install_name_tool', '-id', f'@rpath/{dotted}.framework/{dotted}', str(binpath)], check=True, capture_output=True)
    (fw / 'Info.plist').write_bytes(plistlib.dumps({'CFBundleExecutable': dotted, 'CFBundleIdentifier': 'org.nxnativeios.py.' + dotted.replace('_', '-'),
        'CFBundlePackageType': 'FMWK', 'CFBundleName': dotted[:15], 'CFBundleVersion': '1', 'CFBundleShortVersionString': '1.0',
        'CFBundleSupportedPlatforms': ['iPhoneOS'], 'MinimumOSVersion': '26.0'}))
    fwork = so.with_name(so.name[:-3] + '.fwork')
    fwork.write_text(str(binpath.relative_to(app)))
    (fw / f'{dotted}.origin').write_text(str(fwork.relative_to(app)))
    n += 1
print(f'{ver}: stdlib + {n} binary modules as frameworks')
