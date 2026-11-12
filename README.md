# nxnativeios

An iPhone app that turns your own Switch game (NSP + `prod.keys`) into a native nxnative game IPA, entirely on the phone. The IPA is then signed and installed with FlareStore.

Built on [nxnative](https://github.com/seedds/nxnative) (MIT). No game files or keys are in this repository.

## App tabs
- **Build**: import from Files — a `.zip` holding `prod.keys` and the game (NSP/XCI/NSZ, update, DLC), or the files one by one. No folder picker. Tap Build, watch progress.
- **IPAs**: the downloaded and built IPAs: size, game, date; share to FlareStore, delete, rename.
- **Settings**

## Status
See [docs/DESIGN.md](docs/DESIGN.md) for the whole pipeline.
- [x] `tools/mkgameframework.py`: the game's rewritten code as `NXGame.framework` with no compiler
- [x] `patches/0001`: the game app loads its code from `NXGame.framework`
- [x] `patches/0002`: the game app compiles MSL source shaders on the phone
- [x] CI: per-profile player shells (no game data), release `shells`
- [x] `NxTools.framework`: NSP/XCI extraction (your `prod.keys`) and shader translation
- [x] `SpirvCross.framework`: SPIR-V to Metal source
- [x] Embedded Python + nxnative's build scripts on the phone (runs unpack, check, rewrite and the shader split on the phone; a later step still ends the build early, being fixed)
- [ ] Game IPA assembler (replaces xcodebuild): written, not yet run end to end on a phone
- [x] Builder app UI (Build / IPAs / Settings), with keys saved once, split zip and RAR input, background building
