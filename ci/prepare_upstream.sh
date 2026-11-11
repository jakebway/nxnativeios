#!/bin/sh
# Clone nxnative at $NXNATIVE_COMMIT (default: HEAD) into ./upstream, apply patches/, and prepare the C# sources for the library builds.
set -eu
[ -d upstream/.git ] || git clone -q https://github.com/seedds/nxnative.git upstream
[ -z "${NXNATIVE_COMMIT:-}" ] || git -C upstream checkout -q "$NXNATIVE_COMMIT"
git -C upstream apply "$PWD"/patches/*.patch
x=upstream/dm/tools/nx_extract/Program.cs
cp "$x" "$x.orig"   # the original, for --source-sha
sed -i '' 's/^    static int Main(string\[\] a) {/    internal static int Main(string[] a) {/' "$x"
grep -q 'internal static int Main' "$x" || { echo "[RED] nx_extract's Main not found: upstream changed"; exit 1; }
echo "nxnative $(git -C upstream rev-parse --short HEAD) prepared"
