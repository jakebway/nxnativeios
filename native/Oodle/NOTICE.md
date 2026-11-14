# Oodle.framework

The decoder step of nxnative's Mac host (it runs the game's own Oodle / LZ5 code), done on the phone.

- `nxb_oodle.cpp` wraps **ooz** (https://github.com/zao/ooz, a portable fork of Powzix's Kraken decompressor), **GPL-3.0-or-later**, built from the pinned commit in `build.sh` together with
  SIMDe (MIT), which turns its SSE2 code into NEON. Oodle's compressed-block format is fixed, so the same bytes the game's own Oodle decodes come out.
- `nxb_lz5.cpp` wraps LZ5 2.0.1's decoder (https://github.com/inikep/lizard at the last commit before it was renamed Lizard), BSD-2-Clause.

Because ooz is GPL-3, the framework (and so the app that carries it) is distributed under the GPL-3: this repository holds all its source, `build.sh` fetches the rest at the pinned commits.
`tools/test_oodle_lib.py` checks it (every Kraken / Mermaid / Selkie / Leviathan sample of ooz's test set must decode to the same bytes; LZ5 round trip); `tools/test_oodle_phone.py` drives it through nxnative's own scripts.
