#!/usr/bin/env python3
"""Generate the builder app icon (1024x1024 RGB PNG, no alpha) into an asset catalog. Usage: make_icon.py <Assets.xcassets>"""
import json, sys
from pathlib import Path
from PIL import Image
root = Path(sys.argv[1]); icons = root / "AppIcon.appiconset"
icons.mkdir(parents=True, exist_ok=True)
img = Image.open(Path(__file__).with_name("icon-1024.png")).convert("RGB")   # the NX on a red / blue split (ci/icon-1024.png)
img.save(icons / "icon-1024.png", "PNG")
(root / "Contents.json").write_text(json.dumps({"info": {"author": "xcode", "version": 1}}))
(icons / "Contents.json").write_text(json.dumps({"images": [{"filename": "icon-1024.png", "idiom": "universal", "platform": "ios", "size": "1024x1024"}], "info": {"author": "xcode", "version": 1}}))
print("icon written", icons / "icon-1024.png")
