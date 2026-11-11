#!/usr/bin/env python3
"""Audit an unsigned IPA before it is published. Usage: audit_ipa.py <ipa> <summary.txt>. Exit 1 on any error."""
import plistlib, re, subprocess, sys
from pathlib import Path
ipa, summary = Path(sys.argv[1]), Path(sys.argv[2])
work = Path("audit-unpacked")
subprocess.run(["rm", "-rf", str(work)], check=True)
work.mkdir()
subprocess.run(["unzip", "-q", str(ipa), "-d", str(work)], check=True)
apps = list((work / "Payload").glob("*.app"))
errors, notes = [], []
MAGIC = {bytes.fromhex(h) for h in ["feedface", "cefaedfe", "feedfacf", "cffaedfe", "cafebabe", "bebafeca", "cafebabf", "bfbafeca"]}
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*(\.[A-Za-z0-9][A-Za-z0-9-]*)*$")
def ver(s): return tuple(int(x) for x in s.split("."))
if len(apps) != 1:
    errors.append(f"expected exactly one .app in Payload, found {len(apps)}")
    app = None
else:
    app = apps[0]
declared, ids = set(), {}
def check_plist(p, kind, need):
    try:
        d = plistlib.loads(p.read_bytes())
    except Exception as e:
        errors.append(f"{p.relative_to(work)}: unreadable plist ({e})"); return None
    for k in need:
        if k not in d: errors.append(f"{p.relative_to(work)}: missing {k}")
    i = d.get("CFBundleIdentifier", "")
    if i:
        if not ID_RE.match(i): errors.append(f"{p.relative_to(work)}: invalid bundle id {i!r}")
        if i in ids: errors.append(f"duplicate bundle id {i!r}: {ids[i]} and {p.parent.name}")
        ids[i] = p.parent.name
    if "MinimumOSVersion" in d and ver(d["MinimumOSVersion"]) > (26, 0):
        errors.append(f"{p.relative_to(work)}: MinimumOSVersion {d['MinimumOSVersion']} above 26.0")
    return d
if app:
    d = check_plist(app / "Info.plist", "app", ["CFBundleExecutable", "CFBundleIdentifier", "CFBundleVersion", "CFBundleShortVersionString", "MinimumOSVersion", "UIDeviceFamily", "DTPlatformName", "CFBundleSupportedPlatforms"])
    if d:
        declared.add(app / d["CFBundleExecutable"])
        if "CFBundleIcons" not in d and "CFBundleIcons~ipad" not in d: errors.append("app Info.plist has no CFBundleIcons (icon missing)")
        if d.get("DTPlatformName") != "iphoneos": errors.append("DTPlatformName is not iphoneos")
    for fw in sorted((app / "Frameworks").glob("*.framework")):
        fd = check_plist(fw / "Info.plist", "framework", ["CFBundleExecutable", "CFBundleIdentifier", "CFBundlePackageType", "CFBundleSupportedPlatforms", "MinimumOSVersion"])
        if fd and fd.get("CFBundleExecutable"):
            b = fw / fd["CFBundleExecutable"]
            declared.add(b)
            if not b.is_file(): errors.append(f"{fw.name}: executable {b.name} missing")
        if (fw / "_CodeSignature").exists():
            r = subprocess.run(["codesign", "--verify", "--strict", str(fw)], capture_output=True, text=True)
            if r.returncode: errors.append(f"{fw.name}: stale or invalid signature: {r.stderr.strip()[:200]}")
count = 0
for p in sorted(work.rglob("*")):
    if p.is_symlink():
        errors.append(f"symlink: {p.relative_to(work)}")
        continue
    if not p.is_file(): continue
    with p.open("rb") as f: head = f.read(4)
    if head not in MAGIC: continue
    count += 1
    rel = p.relative_to(work)
    if p not in declared: errors.append(f"Mach-O outside a declared bundle executable: {rel}")
    if not p.stat().st_mode & 0o100: errors.append(f"not executable: {rel}")
    o = subprocess.run(["otool", "-l", str(p)], capture_output=True, text=True).stdout
    m = re.search(r"cmd LC_BUILD_VERSION.*?platform (\S+)\s+minos (\S+)", o, re.S)
    if not m: errors.append(f"no LC_BUILD_VERSION: {rel}")
    else:
        if m[1] not in ("2", "IOS"): errors.append(f"platform {m[1]} is not iOS: {rel}")
        if ver(m[2]) > (26, 0): errors.append(f"minos {m[2]} above 26.0: {rel}")
notes.append(f"Mach-O binaries checked: {count}; bundle ids: {len(ids)}")
lines = ["IPA AUDIT: " + ("FAILED" if errors else "PASSED"), f"IPA: {ipa} ({ipa.stat().st_size} bytes)", *notes, ""]
lines += [f"ERROR: {e}" for e in errors] or ["No errors."]
summary.write_text("\n".join(lines) + "\n")
print("\n".join(lines))
sys.exit(1 if errors else 0)
