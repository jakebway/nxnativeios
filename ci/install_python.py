#!/usr/bin/env python3
"""Install embedded Python, convert extension modules, and validate framework packaging.
Usage: install_python.py <app> <Python.xcframework> <app_packages dir> <app code dir>
"""
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

app, xcfw, pkgs, code = (Path(a).resolve() for a in sys.argv[1:5])
device = lambda p: 'simulator' not in str(p) and 'testbed' not in str(p)
cands = [p.parent for p in xcfw.rglob('os.py') if p.parent.name.startswith('python3') and device(p)]
if not cands:
    sys.exit(f'No device standard library in {xcfw}')
stdlib = sorted(cands, key=lambda p: ('ios-arm64' not in str(p), len(str(p))))[0]
ver = stdlib.name
dyn = [d for d in xcfw.rglob('lib-dynload') if device(d) and ver in str(d)]
if not dyn:
    sys.exit('No device lib-dynload in XCframework')
print(f'stdlib: {stdlib}; lib-dynload: {dyn[0]}')
dst_lib = app / 'python/lib' / ver
shutil.rmtree(app / 'python', ignore_errors=True)
shutil.copytree(stdlib, dst_lib, symlinks=False, ignore=shutil.ignore_patterns('__pycache__', 'test', 'tests', 'idlelib', 'tkinter', 'turtledemo', 'ensurepip', '*.a', 'lib-dynload'))
shutil.copytree(dyn[0], dst_lib / 'lib-dynload', symlinks=False)
for name, src in (('app_packages', pkgs), ('app', code)):
    shutil.rmtree(app / name, ignore_errors=True)
    shutil.copytree(src, app / name, ignore=shutil.ignore_patterns('__pycache__'))
fw_root = app / 'Frameworks'
fw_root.mkdir(exist_ok=True)
n = 0
for so in sorted(list(dst_lib.rglob('*.so')) + list((app / 'app_packages').rglob('*.so'))):
    rel = so.relative_to(app)
    if 'lib-dynload' in rel.parts:
        dotted = so.name.split('.')[0]
    else:
        base = so.parent.relative_to(app / 'app_packages')
        dotted = '.'.join([*base.parts, so.name.split('.')[0]])
    fw = fw_root / f'{dotted}.framework'
    fw.mkdir(parents=True, exist_ok=True)
    binpath = fw / dotted
    shutil.move(str(so), binpath)
    subprocess.run(['install_name_tool', '-id', f'@rpath/{dotted}.framework/{dotted}', str(binpath)], check=True, capture_output=True)
    (fw / 'Info.plist').write_bytes(plistlib.dumps({
        'CFBundleExecutable': dotted,
        'CFBundleIdentifier': 'org.nxnativeios.py.' + dotted.replace('_', '-'),
        'CFBundlePackageType': 'FMWK', 'CFBundleName': dotted[:15],
        'CFBundleVersion': '1', 'CFBundleShortVersionString': '1.0',
        'CFBundleSupportedPlatforms': ['iPhoneOS'], 'MinimumOSVersion': '26.0',
    }))
    fwork = so.with_name(so.name[:-3] + '.fwork')
    fwork.write_text(str(binpath.relative_to(app)))
    (fw / f'{dotted}.origin').write_text(str(fwork.relative_to(app)))
    n += 1
print(f'{ver}: stdlib + {n} binary modules as frameworks')

# Artifact extraction and wheels can leave Mach-O libraries with mode 0644.
# Normalize all framework executables, including frameworks embedded by Xcode.
seen = set()
for fw in sorted(fw_root.glob('*.framework')):
    plist = fw / 'Info.plist'
    data = plistlib.loads(plist.read_bytes())
    executable = data.get('CFBundleExecutable', '')
    if not executable or Path(executable).name != executable:
        sys.exit(f'Invalid CFBundleExecutable in {plist}: {executable!r}')
    binary = fw / executable
    if not binary.is_file():
        sys.exit(f'Missing framework executable: {binary}')
    identifier = data.get('CFBundleIdentifier')
    if not identifier or identifier in seen:
        sys.exit(f'Missing or duplicate framework identifier: {identifier!r}')
    seen.add(identifier)
    binary.chmod(0o755)
    data['CFBundleSupportedPlatforms'] = ['iPhoneOS']
    data['CFBundlePackageType'] = 'FMWK'
    data.setdefault('MinimumOSVersion', '26.0')
    if plistlib.loads(plist.read_bytes()) != data:
        plist.write_bytes(plistlib.dumps(data))
        # Metadata edits invalidate an existing ad-hoc resource seal.
        subprocess.run(['codesign', '--remove-signature', str(binary)], check=True, capture_output=True)
        shutil.rmtree(fw / '_CodeSignature', ignore_errors=True)
    if binary.stat().st_mode & 0o111 != 0o111:
        sys.exit(f'Framework executable is not executable: {binary}')
    print(f'Framework OK: {fw.name} executable={executable} mode=0755 platform=iPhoneOS')
print(f'Validated {len(seen)} framework bundles; final device signing remains the sideloader responsibility')
