"""phone/nxbuild/splitmem.py: the memory-bounded shader split writes exactly what upstream's split writes.

usage: test_splitmem.py <upstream checkout (dm/ inside)>
Builds a fake RomFS of loose GLSLC outputs (repeats, both stages, big and small code areas, two source groups), runs shader_split.main() on it as upstream has it and with splitmem's
edits, and compares every output file byte for byte. Also checks that a Blob reads like the bytes it stands for and that nothing is left in memory per shader."""
import concurrent.futures as cf, filecmp, os, random, shutil, struct, sys, tempfile
from pathlib import Path

UP = Path(sys.argv[1] if len(sys.argv) > 1 else '/tmp/up').resolve()
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'phone'))
os.environ.setdefault('DM_GAME', '0400A3A01EE4C000')
sys.path.insert(0, str(UP / 'dm/gfx/tools')); sys.path.insert(0, str(UP / 'dm/tools'))
from nxbuild import splitmem

SCRIPT = UP / 'dm/gfx/tools/shader_split.py'


def load(transformed):
    src = SCRIPT.read_text(encoding='utf-8')
    g = {'__name__': 'shader_split_t', '__file__': str(SCRIPT), '_sm': splitmem}
    if transformed:
        src, why = splitmem.transform(src)
        assert why is None, why
    exec(compile(src, str(SCRIPT), 'exec'), g)
    return g


def output(g, stage, seed, ncode, extra=0):
    rnd = random.Random(seed)
    ctl = bytearray(0x880); ctl[:4] = g['CTL_MAGIC']; struct.pack_into('<I', ctl, 0x20, len(ctl)); struct.pack_into('<I', ctl, 0x704, ncode)
    for i in range(0x40, 0x100): ctl[i] = rnd.randrange(256)
    code = bytearray(rnd.randbytes(ncode)); code[:4] = g['GFX_MAGIC']
    struct.pack_into('<I', code, 0x30, (g['STAGES'].index(stage) + 1) << 10 | 1)
    for i in range(6, 14): struct.pack_into('<I', code, 0x30 + 4 * i, rnd.randrange(1 << 32) if stage == 'ps' else 0)
    data = bytearray(0x70) + ctl + code
    data[:4] = bytes.fromhex('91688619'); struct.pack_into('<I', data, 0x44, len(data))
    return bytes(data)


def fixture(g, root):
    romfs = root / 'romfs'
    for d in ('motor_asset_re', 'other'): (romfs / d).mkdir(parents=True)
    n = 0
    for i in range(60):
        seed = i % 41   # 41 distinct, the rest repeat (same code, other files)
        stage = ('vs', 'ps')[seed % 2]
        ncode = 600 + (seed * 997) % 6000   # some under, most over the spill minimum
        blob = output(g, stage, seed, ncode)
        if i % 7 == 0: blob = blob + output(g, 'ps', 1000 + i, 3000)   # two outputs in one file
        (romfs / ('motor_asset_re' if i % 3 else 'other') / f'f{i:03d}.bin').write_bytes(blob); n += 1
    (romfs / 'other' / 'junk.txt').write_bytes(b'not a shader')
    main = root / 'main'; main.write_bytes(b'\0' * 64)
    return romfs, main


def run(transformed, root, tag):
    g = load(transformed)
    out = root / tag; out.mkdir()
    g['nso_image'] = lambda p: b'\0' * 64
    real = cf.ProcessPoolExecutor; cf.ProcessPoolExecutor = cf.ThreadPoolExecutor
    argv, sys.argv = sys.argv, ['shader_split.py', str(root / 'romfs'), str(root / 'main'), str(out / 'pkg'), str(out / 'map.tsv'), str(out / 'facts.tsv'), str(out / 'pairs.tsv'), str(out / 'pso.tsv')]
    try: g['main']()
    finally: sys.argv = argv; cf.ProcessPoolExecutor = real
    return out, g


def same_tree(a, b):
    fa = sorted(p.relative_to(a) for p in a.rglob('*') if p.is_file()); fb = sorted(p.relative_to(b) for p in b.rglob('*') if p.is_file())
    assert fa == fb, (fa, fb)
    for f in fa: assert filecmp.cmp(a / f, b / f, shallow=False), f'{f} differs'
    return fa


def blob_checks():
    sp = splitmem.Spill()
    try:
        data = random.Random(1).randbytes(5000); b = sp.put(data)
        assert len(b) == 5000 and bytes(b) == data and b == data and b == sp.put(data) and not (b != data)
        assert b[10:20] == data[10:20] and b[-5:] == data[-5:] and b[7] == data[7] and b[:0x80] == data[:0x80] and b[4990:6000] == data[4990:]
        assert b'abc' + b == b'abc' + data and b + b'abc' == data + b'abc' and data[100:104] in b
        assert b != data[:-1] and b != data[:-1] + b'x'
    finally: sp.close()


if __name__ == '__main__':
    blob_checks()
    root = Path(tempfile.mkdtemp(prefix='splitmem-test-'))
    try:
        g0 = load(False)
        romfs, main = fixture(g0, root)
        a, _ = run(False, root, 'orig')
        os.environ['NXB_SPILL_MIN'] = '1024'; splitmem.SMALL = 1024
        b, g = run(True, root, 'mem')
        files = same_tree(a, b)
        n = sum(1 for l in (a / 'map.tsv').read_text().splitlines() if l and not l.startswith('#') and not l.startswith('package'))
        assert n >= 40, f'only {n} shaders came out: the fixture is not being read'
        assert splitmem._spill is None
        print(f'ok: {len(files)} output files byte-identical, {n} shaders')
    finally: shutil.rmtree(root, ignore_errors=True)
