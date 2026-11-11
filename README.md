# nxnativeios

An iPhone app that turns your own Switch game (NSP + `prod.keys`) into a native nxnative game IPA, entirely on the phone. The IPA is then signed and installed with FlareStore.

Built on [nxnative](https://github.com/seedds/nxnative) (MIT). No game files or keys are in this repository.

## App tabs
- **Build**: pick `prod.keys` and the game folder from Files, tap Build, watch progress.
- **IPAs**: the downloaded and built IPAs: size, game, date; share to FlareStore, delete, rename.
- **Settings**

## Status
- [x] `tools/mkgameframework.py`: writes the game's rewritten code as `NXGame.framework` with no compiler (replaces nxnative's `gen_embed.py` + clang/ld)
- [x] `patches/0001`: nxnative's iOS app loads game code from `NXGame.framework`
- [ ] CI: per-profile player shells (no game data)
- [ ] On-device extraction (keys + NSP)
- [ ] On-device rewriter (embedded Python)
- [ ] On-device shaders (runtime Metal compile)
- [ ] Builder app UI (Build / IPAs / Settings)
