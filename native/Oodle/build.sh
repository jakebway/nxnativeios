#!/bin/sh
# build.sh <ios|macos|linux> <out dir>: the Oodle decoder (ooz + SIMDe, pinned commits) as a dynamic library. SIMDe turns ooz's SSE2 code into NEON on the iPhone.
set -eu
OOZ=${OOZ_COMMIT:-ff5aeb9e45e362e8d6bb1199aa82406285dd2a18}
LZ5=${LZ5_COMMIT:-3ca547e22a7688835587b098b75bc687b28a39d1}   # LZ5 2.0.1, the last release before the library was renamed Lizard (DRAGON QUEST XI S: LZ5_versionNumber 20001)
SIMDE=${SIMDE_COMMIT:-dd0b662fd8cf4b1617dbbb4d08aa053e512b08e4}
mkdir -p "$2"; OUT=$(cd "$2" && pwd); HERE=$(cd "$(dirname "$0")" && pwd)
fetch() {   # <repo> <commit> <dir>
  [ -d "$3/.git" ] && return 0
  mkdir -p "$3"; git -C "$3" init -q; git -C "$3" remote add origin "https://github.com/$1"
  git -C "$3" fetch -q --depth 1 origin "$2"; git -C "$3" checkout -q FETCH_HEAD
}
fetch zao/ooz "$OOZ" "$OUT/ooz"; fetch simd-everywhere/simde "$SIMDE" "$OUT/simde"; fetch inikep/lizard "$LZ5" "$OUT/lz5"
case $1 in
  ios)   cc="xcrun --sdk iphoneos clang++ -arch arm64 -miphoneos-version-min=26.0"; ext=dylib ;;
  macos) cc="xcrun --sdk macosx clang++ -arch arm64"; ext=dylib ;;
  linux) cc="${CXX:-clang++} -include $HERE/rotl_linux.h"; ext=so ;;
esac
# Leviathan (Oodle's slowest, hardly ever used by games) decodes wrongly when Apple's clang optimizes ooz's code for it (Kraken, Mermaid and Selkie are right at -O2, checked on an Apple silicon
# runner): that part is built without optimization (about 270 MB/s there, plenty)
mkdir -p "$OUT/nxb"
awk '/^struct LeviathanLzTable \{/ { print "#pragma clang optimize off" } { print } /^int Leviathan_DecodeQuantum/ { inq = 1 } inq && /^}/ { print "#pragma clang optimize on"; inq = 0 }' "$OUT/ooz/kraken.cpp" > "$OUT/nxb/kraken.cpp"
grep -c "pragma clang optimize" "$OUT/nxb/kraken.cpp" | grep -qx 2
# LZ5 2.0.1's decoder (BSD-2-Clause), with its Huffman / FSE parts. A test build (OODLE_TEST=1) also has its compressor, for a round trip
LZ5L="$OUT/lz5/lib"; ccc=$(echo "$cc" | sed 's/clang++/clang/')
for s in lz5_decompress.c entropy/huf_decompress.c entropy/fse_decompress.c entropy/entropy_common.c ${OODLE_TEST:+lz5_compress.c entropy/huf_compress.c entropy/fse_compress.c}; do
  $ccc -std=gnu99 ${OODLE_OPT:--O2} -fPIC -w -fvisibility=hidden -I"$LZ5L" -I"$LZ5L/entropy" -c "$LZ5L/$s" -o "$OUT/lz5_$(basename "$s" .c)-$1.o"
done
$cc -std=c++17 ${OODLE_OPT:--O2} -fPIC -w -fno-strict-aliasing -fwrapv -fvisibility=hidden -I"$LZ5L" ${OODLE_TEST:+-DNXB_TEST} -c "$HERE/nxb_lz5.cpp" -o "$OUT/nxb_lz5-$1.o"
# kraken.cpp (+ the two other decoders it dispatches to); -fno-exceptions: ooz reports errors by return value
$cc -std=c++17 ${OODLE_OPT:--O2} -fPIC -w -fno-strict-aliasing -fwrapv -fvisibility=hidden -I"$OUT/nxb" -I"$OUT/ooz" -I"$OUT/simde" -I"$HERE" -c "$HERE/nxb_oodle.cpp" -o "$OUT/nxb_oodle-$1.o"
$cc -std=c++17 ${OODLE_OPT:--O2} -fPIC -w -fno-strict-aliasing -fwrapv -DOOZ_BUILD_DLL=1 -I"$OUT/ooz" -I"$OUT/simde" -c "$OUT/ooz/bitknit.cpp" -o "$OUT/bitknit-$1.o"
$cc -std=c++17 ${OODLE_OPT:--O2} -fPIC -w -fno-strict-aliasing -fwrapv -DOOZ_BUILD_DLL=1 -I"$OUT/ooz" -I"$OUT/simde" -c "$OUT/ooz/lzna.cpp" -o "$OUT/lzna-$1.o"
if [ "$1" = linux ]; then $cc -shared -o "$OUT/libOodle-$1.$ext" "$OUT"/nxb_oodle-$1.o "$OUT"/bitknit-$1.o "$OUT"/lzna-$1.o "$OUT"/nxb_lz5-$1.o "$OUT"/lz5_*-$1.o
else $cc -dynamiclib -o "$OUT/libOodle-$1.$ext" "$OUT"/nxb_oodle-$1.o "$OUT"/bitknit-$1.o "$OUT"/lzna-$1.o "$OUT"/nxb_lz5-$1.o "$OUT"/lz5_*-$1.o -install_name @rpath/Oodle.framework/Oodle; fi
nm -gD "$OUT/libOodle-$1.$ext" 2>/dev/null | grep nxb_ || nm -gU "$OUT/libOodle-$1.$ext" | grep nxb_
