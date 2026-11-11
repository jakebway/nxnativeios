#!/usr/bin/env python3
"""Generate the builder app icon (1024x1024 RGB PNG, no alpha) into an asset catalog. Usage: make_icon.py <Assets.xcassets>"""
import json, sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
root = Path(sys.argv[1]); icons = root / "AppIcon.appiconset"
icons.mkdir(parents=True, exist_ok=True)
img = Image.new("RGB", (1024, 1024))
px = img.load()
for y in range(1024):
    for x in range(1024):
        px[x, y] = (20 + x // 12, 30 + y // 14, 120 + (x + y) // 12)
d = ImageDraw.Draw(img)
try: font = ImageFont.load_default(size=420)
except TypeError: font = ImageFont.load_default()
d.text((512, 512), "NX", fill=(255, 255, 255), font=font, anchor="mm")
img.save(icons / "icon-1024.png", "PNG")
(root / "Contents.json").write_text(json.dumps({"info": {"author": "xcode", "version": 1}}))
(icons / "Contents.json").write_text(json.dumps({"images": [{"filename": "icon-1024.png", "idiom": "universal", "platform": "ios", "size": "1024x1024"}], "info": {"author": "xcode", "version": 1}}))
print("icon written", icons / "icon-1024.png")
