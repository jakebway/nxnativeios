#!/bin/sh
# build.sh <ios|macos> <out dir>: libunrar (RARLAB's UnRAR source, the DLL interface) as a dynamic library. Used only to unpack RAR archives (the UnRAR license allows that).
# The object lists come from the source's own makefile, so a new UnRAR release keeps building.
set -eu
VER=${UNRAR_VERSION:-7.3.2}
mkdir -p "$2"; OUT=$(cd "$2" && pwd)
src=$OUT/unrar
if [ ! -d "$src" ]; then
  curl -fL --retry 5 -o "$OUT/unrar.tgz" "https://www.rarlab.com/rar/unrarsrc-$VER.tar.gz"
  tar xzf "$OUT/unrar.tgz" -C "$OUT"
fi
cd "$src"
# OBJECTS and LIB_OBJ from the makefile (joined continuation lines), .o -> .cpp
objs=$(sed -e ':a' -e '/\\$/N; s/\\\n//; ta' makefile | sed -n -e 's/^OBJECTS *= *//p' -e 's/^LIB_OBJ *= *//p' | tr ' \t' '\n\n' | sed -n 's/\.o$/.cpp/p' | sort -u)
echo "$objs" | tr '\n' ' '; echo
case $1 in
  ios)   cc="xcrun --sdk iphoneos clang++ -arch arm64 -miphoneos-version-min=26.0" ;;
  macos) cc="xcrun --sdk macosx clang++ -arch arm64" ;;
esac
mkdir -p "$OUT/obj-$1"
cat > "$OUT/cc-$1.sh" <<EOS
#!/bin/sh
f=\$1; exec $cc -std=c++11 -O2 -fPIC -w -D_FILE_OFFSET_BITS=64 -D_LARGEFILE_SOURCE -DRARDLL -c "\$f" -o "$OUT/obj-$1/\$(basename "\$f" .cpp).o"
EOS
chmod +x "$OUT/cc-$1.sh"
echo "$objs" | xargs -n1 -P4 "$OUT/cc-$1.sh"
$cc -dynamiclib -o "$OUT/libUnrar-$1.dylib" "$OUT"/obj-$1/*.o -install_name @rpath/Unrar.framework/Unrar
nm -gU "$OUT/libUnrar-$1.dylib" | grep -E '_RAR(OpenArchiveEx|ReadHeaderEx|ProcessFile|CloseArchive|GetDllVersion)$'
