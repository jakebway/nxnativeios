# nxnativeios design

Goal: an iPhone app (the **builder**) that turns the player's own Switch game (NSP/XCI + `prod.keys`) into a native nxnative game IPA **on the phone**, with no Mac. The finished game IPA is handed to FlareStore, which signs and installs it.

Upstream is [seedds/nxnative](https://github.com/seedds/nxnative), pinned per build (`ci/prepare_upstream.sh`, patches in `patches/`).

## Why a builder + game IPA (not one app)

iOS runs only signed code. A game's rewritten Switch code is produced on the phone, so it must end up in a binary FlareStore signs: `NXGame.framework` inside the game IPA. One all-in-one app would need the player's signing certificate inside the app.

## The game IPA

```
Payload/DmIOS.app/
  DmIOS                     player shell executable (CI, per game profile; no game code)
  Info.plist                name, bundle ID, version, DMChain, DMShowFPS, DMLanguage, icon files
  Frameworks/NXGame.framework/NXGame   rewritten modules (tools/mkgameframework.py, on the phone)
  dm/                       rewriter tables (*.fixups/gates/cuts/obs.tsv), shader tables, launcher.json, font/
  romfs.img                 the game files (nx_extract --romfs-image)
  msl/b-<chain>/            shader libraries: MSL source in place of .metallib (patch 0002 compiles them)
  aoc/                      DLC RomFS images
  html/, jit/               when the game has them
```

Reference for every file: upstream `dm/ios/tools/build_ipa.sh`, `stage_resources.sh`, `gen_resources.py`, `pack_ipa.py`. The builder replaces `build_ipa.sh` (xcodebuild) with: copy shell + add the files above + write Info.plist + zip (large files stored, as `pack_ipa.py` / the profile's `zip_store`).

The asset catalog cannot be compiled on the phone: the icon goes in as PNG files named in `CFBundleIcons`.

FlareStore must keep the **Increased Memory Limit** entitlement (`build_ipa.sh` signs it in ad hoc; FlareStore re-signs).

## Pieces

| Piece | Where it runs | State |
|---|---|---|
| `tools/mkgameframework.py`: modules → `NXGame.framework` with no compiler (replaces `gen_embed.py` + clang/ld) | phone (pure Python) | done; CI: codesign + dlopen + getsectiondata check every section |
| `patches/0001`: `main.m` dlopens `NXGame.framework`, calls `dm_set_game_image_header` | shell | done; compiles for iOS |
| `patches/0002`: `nvn_mtl.m lib_from_file_` compiles a shader file that is MSL source (not `MTLB`) with `newLibraryWithSource` | shell | done; compiles for iOS |
| Player shells (`tools/build_shell.py`, `shells.yml` → release `shells`) | CI | done for 3 profiles; fonts still to add |
| `NxTools.framework`: `nx_extract_main`, `dmsh_xlate_main` (NativeAOT, one .NET runtime) | phone | done; CI checks both `--source-sha` against upstream |
| `SpirvCross.framework`: `spirv_cross_main`, exit() made safe | phone | done; CI: same MSL as upstream's pinned binary |
| Embedded Python (CPython for iOS) + lz4 + capstone (+ zbic for system 22+ modules) | phone | next |
| `subprocess` shim: upstream scripts' `run()` / `Popen` → in-process (Python scripts via runpy, tools via the frameworks, `xcrun metal` → write MSL as the library, `build_ipa.sh` → our assembler) | phone | next |
| Builder app UI: Build / IPAs / Settings tabs, import `.zip` or files (no folder picker) | phone | later |

## On-device shader compile: known differences from the offline build

Offline iOS flags (`dm/ios/tools/ios_metal.py METAL`): `-O1 -mios-version-min=18.0 -fmetal-math-mode=relaxed -fpreserve-invariance -fwrapv -fbracket-depth=1024`.

- `-fpreserve-invariance` → `MTLCompileOptions.preserveInvariance = YES`. Same.
- `-fmetal-math-mode=relaxed` → `mathMode = MTLMathModeRelaxed`. Same (keeps the translated shaders' isnan selects; upstream: black bands on an A20 Pro without it).
- `-mios-version-min=18.0` → `languageVersion = MTLLanguageVersion3_2`.
- `-O1`: no runtime equivalent. Default optimization; upstream notes `-O2` folding made Odyssey's `alRenderMaterialUber` take 25 min / 17.3 MB vs 31 s / 1.3 MB. Watch first-launch compile times.
- `-fwrapv`: no runtime equivalent. Signed overflow is undefined in MSL; upstream traced Ocarina of Time's mesh shader lighting band to it. Fix later in the translator output (do the arithmetic in unsigned) if a game shows it.
- `-fbracket-depth=1024`: no runtime equivalent; sources nesting > 256 fail to compile (upstream: two OoT compute shaders).
- Upstream pins the Metal compiler (issue #242, corruption with another compiler, cause unconfirmed). The phone's compiler is the OS's.

## Scope of version 1

Games whose profile in `dm/games/<title ID>/` registers the exact version being built. Unregistered versions and provisional profiles need steps that boot the game in the Mac host (heap check, address regions, run-time shader capture, `jit_capture.py`): not on the phone. The Mac host's *decoder* step is different: games whose files are Oodle-compressed (Unreal pak shader archives, Trinity packs, PlatinumGames PKZ, IoStore) or LZ5-compressed (DRAGON QUEST XI S) are decoded by Oodle.framework (`native/Oodle`: ooz + LZ5 2.0.1) instead of the game's own code; `phone/nxbuild/oodle.py` plays the host for `DM_OODLE_SERVE` / `DM_OODLE_JOB`, and `driver.py` / `shim.py` route nxnative's `build_mac_host` / `boot_mac` / `subprocess` calls to it. NSZ/XCZ need `nsz` (Python, zstandard): later.

Builds are long (upstream: 30–60 min on a Mac for a first build). iOS suspends background apps: the builder keeps the screen awake and resumes from the build folder (upstream reuses finished steps by fingerprint).
