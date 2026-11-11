"""nxnativeios: the app's Self-test (Settings). Checks every piece a build needs, with no game: returns a report, one line per check."""
import os, sys, tempfile, traceback


def run(_arg=''):
    lines, ok = [], True
    def check(name, fn):
        nonlocal ok
        try: detail = fn(); lines.append(f'✅ {name}' + (f': {detail}' if detail else ''))
        except BaseException as e: ok = False; lines.append(f'❌ {name}: {type(e).__name__}: {e}'.strip()[:400])
    check('Python', lambda: sys.version.split()[0])
    check('zstd (built in)', lambda: __import__('compression.zstd').zstd.decompress(__import__('compression.zstd').zstd.compress(b'ok')).decode())
    check('lz4', lambda: __import__('lz4.block').block.decompress(__import__('lz4.block').block.compress(b'nxnative' * 4)).decode()[:8])
    def cs():
        import capstone
        md = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM)
        i = next(md.disasm(bytes.fromhex('e00300aa'), 0)); return f'{capstone.__version__}, {i.mnemonic} {i.op_str}'
    check('capstone', cs)
    from . import shim
    shim.install()
    import subprocess
    def tool(name):
        r = subprocess.run([f'/nxnativeios/{name}', '--source-sha'], capture_output=True, text=True)
        if r.returncode: raise RuntimeError(r.stdout.strip()[-200:] or f'exit {r.returncode}')
        return r.stdout.strip()
    check('nx_extract (NxTools)', lambda: tool('nx_extract'))
    check('dmsh_xlate (NxTools)', lambda: tool('dmsh_xlate'))
    def spvc():
        r = subprocess.run(['/nxnativeios/spirv-cross', '/nonexistent.spv', '--msl'], capture_output=True, text=True)
        if 'nxnativeios:' in r.stdout: raise RuntimeError(r.stdout.strip()[-200:])   # the framework did not load
        if r.returncode == 0: raise RuntimeError('a missing input did not fail')
        return 'loads, and a bad input returns an error'
    check('SpirvCross', spvc)
    def fw():
        from . import mkgameframework as mk
        d = tempfile.mkdtemp(); data = os.urandom(0x14000)
        open(f'{d}/m.patched.bin', 'wb').write(data)
        open(f'{d}/m.fixups.tsv', 'w').write('# TEXT_END 0x4000\n# PATCH_OFF 0xc000\n# KEY_PAGE_OFF 0x8000\n# KEY_PAGE_SIZE 0x4000\n')
        out = mk.write_dylib(mk.layout_sections(d, ['m'], '', None), f'{d}/NXGame', 'ios')
        return f'{os.path.getsize(out) // 1024} KB test framework'
    check('game framework writer', fw)
    def up():
        from pathlib import Path
        p = Path(os.environ.get('NXB_UPSTREAM', ''))
        if not (p / 'scripts/build_ipa_from_nsp.py').is_file(): return 'not unpacked yet (the first build unpacks it)'
        return f'{sum(1 for _ in (p / "dm/games").glob("*/game.tsv"))} game profiles'
    check('nxnative', up)
    lines.append('All good: ready to build.' if ok else 'Something is missing: share this report.')
    return '\n'.join(lines)
