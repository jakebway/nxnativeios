#!/bin/sh
# build.sh <ios|macos> <out dir>: SpirvCross at the commit upstream nxnative pins (read from upstream/dm/gfx/tools/spirv_cross_bin/build.sh)
set -eu
HERE=$(cd "$(dirname "$0")" && pwd); ROOT=$HERE/../..; OUT=$2; mkdir -p "$OUT"
pin=$ROOT/upstream/dm/gfx/tools/spirv_cross_bin/build.sh
TAG=$(sed -n 's/^TAG=\([^ ]*\).*/\1/p' "$pin"); COMMIT=$(sed -n 's/^COMMIT=\([0-9a-f]*\).*/\1/p' "$pin")
src=$OUT/src; [ -d "$src" ] || git clone -q --depth 1 --branch "$TAG" https://github.com/KhronosGroup/SPIRV-Cross.git "$src"
[ "$(git -C "$src" rev-parse HEAD)" = "$COMMIT" ] || { echo "[RED] $TAG is not $COMMIT"; exit 1; }
case $1 in
  ios) extra="-DCMAKE_SYSTEM_NAME=iOS -DCMAKE_OSX_ARCHITECTURES=arm64 -DCMAKE_OSX_DEPLOYMENT_TARGET=26.0" ;;
  macos) extra="-DCMAKE_OSX_ARCHITECTURES=arm64" ;;
esac
cmake -S "$HERE" -B "$OUT/build-$1" -DCMAKE_BUILD_TYPE=Release -DSPVC_SRC="$src" $extra > "$OUT/configure-$1.log"
cmake --build "$OUT/build-$1" --target SpirvCross -j 4 > "$OUT/build-$1.log" || { tail -30 "$OUT/build-$1.log"; exit 1; }
find "$OUT/build-$1" -name 'libSpirvCross.dylib' -exec cp {} "$OUT/libSpirvCross-$1.dylib" \;
echo "SpirvCross $TAG ($1): $OUT/libSpirvCross-$1.dylib"
