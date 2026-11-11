#!/bin/sh
# Clone nxnative at $NXNATIVE_COMMIT (default: HEAD) into ./upstream, apply patches/, and prepare the C# sources for the library builds.
set -eu
[ -d upstream/.git ] || git clone -q https://github.com/seedds/nxnative.git upstream
[ -z "${NXNATIVE_COMMIT:-}" ] || git -C upstream checkout -q "$NXNATIVE_COMMIT"
git -C upstream apply "$PWD"/patches/*.patch
# Each C# tool: keep the original (for --source-sha), make Main internal, give its embedded sources their own resource names (both tools live in one assembly)
prep() {   # <Program.cs> <Main declaration line, as a sed pattern> <resource prefix>
    cp "$1" "${1%.cs}_cs.orig"
    sed -i '' -e "s/^\( *\)$2/\1internal $2/" -e "s/new\[\] { \"src0\", \"src1\" }/new[] { \"$3src0\", \"$3src1\" }/" "$1"
    grep -q "internal $2" "$1" && grep -q "\"$3src0\"" "$1" || { echo "[RED] $1: Main or its resource names not found: upstream changed"; exit 1; }
}
prep upstream/dm/tools/nx_extract/Program.cs 'static int Main(string\[\] a)' nx_
prep upstream/dm/gfx/tools/dmsh_xlate/Program.cs 'static int Main(string\[\] args)' xl_
echo "nxnative $(git -C upstream rev-parse --short HEAD) prepared"
