"""nxnativeios: one game build on the phone, through nxnative's own scripts/build_ipa_from_nsp.py.

build(game_dir, keys, shell_app, out_dir, log) runs the NSP script's cli() in this process with the shim installed (shim.py) and returns its exit code.
The script is loaded as a module, not as __main__, so the Mac checks it starts with (Xcode, xcodegen, make, the Metal toolchain, an arm64 Mac Python) can be
replaced by the phone's before cli() runs. Everything else is the script's own: the game profile, extraction, rewrite, shader split, shader build, reuse of
finished steps by fingerprint, its progress events.
"""
import importlib.util, os, sys
from pathlib import Path
from . import shim

HERE = Path(__file__).resolve().parent


def upstream():
    return Path(os.environ.get('NXB_UPSTREAM') or HERE.parent / 'upstream').resolve()


def _phone_checks(mod):
    def check_prereqs(env, xlate, mac=False):
        missing = [m for m in ('lz4.block', 'capstone', 'fontTools', 'zbic', 'compression.zstd') if not mod._importable(m)]
        if missing: raise mod.BuildError(f'the app\'s Python is missing modules: {", ".join(missing)} (an nxnativeios packaging fault)')
        mod.check_capstone()
        mod.check_translator(xlate, env)   # dmsh_xlate --source-sha through NxTools.framework
    mod.check_prereqs = check_prereqs
    mod.check_native_python = lambda: None   # no Rosetta on a phone
    mod.check_ios_sdk = lambda env: None
    # the Mac host's decoder step (Oodle / LZ5 decoding of game files): Oodle.framework does it (oodle.py); what the scripts call "the host" is a marker file the shim answers for
    from . import oodle
    mod.build_mac_host = lambda repo, out, env, logs, g: oodle.host_marker(out)


def _phone_shaders(mod):
    """The iOS shader step, for a phone's disk and time.

    Some games' profiles list the shaders their playtests used (shader_seen.tsv: for Pokémon Pokopia 8,157 of 131,426). The script builds only those for a Mac (--seen-shaders) and refuses it for an
    iPhone build; dmsh_build.py itself takes a key list for either target, and a library with only those keys is what the Mac's partial build already runs on. So for these games the phone builds the
    listed shaders (and the pixel shaders paired with them) into the iOS library, in minutes and with a sixteenth of the disk; a shader the list does not cover is reported as missing by the game and
    draws without it. NXB_SEEN=0 builds the whole map (hours, and tens of GB). Either way the step's big work files (the shader package, the per-shader cache) go the moment it ends: the next step
    reads only the finished library."""
    from . import cleanup
    orig = mod.build_shaders

    def seen_for_phone(g, mac, seen):
        if mac or seen or os.environ.get('NXB_SEEN') == '0': return None
        try:
            if not g.table('shader_seen.tsv').is_file(): return None
            known = mod.shader_keys(g); listed = mod.seen_listed(g) & set(known)
        except Exception: return None
        return sorted(listed) if listed and len(listed) * 4 < len(known) else None

    def seen_ios(py, repo, sh, xlate, env, logs, g, keys, pull):
        chain = mod.chain_of(repo); ios = sh / 'ios'; log = logs / 'dmsh_build.log'
        mod.PROG.stage('iOS shaders')
        mod.say(f'building the {len(keys):,} shaders the game\'s playtests used (of {len(mod.shader_keys(g)):,}); the rest draw as missing (NXB_SEEN=0 in env builds the whole map)')
        mod.rmtree(ios / f'b-{chain}.key')
        for p in (ios / f'b-{chain}', ios / f'b-{chain}.img'): mod.rmtree(p)
        benv = dict(env, XLATE=str(xlate), IOSOUT=str(ios), DMSH_TARGETS='ios', DMSH_CAS=str(sh / 'cache/cas.db'))
        if mod.ALLOW_OTHER_METAL: benv['DM_ALLOW_OTHER_METAL'] = '1'
        if pull is False: benv['DMSH_IOS_PULL'] = '0'
        prog = sh / 'progress.json'; mod.rmtree(prog); benv['DMSH_PROGRESS'] = str(prog)
        try: mod.PROG.watch(mod.ShaderWatch(prog))
        except Exception: pass
        mod.run([py, repo / 'dm/gfx/tools/own_compilers.py', sh / 'pkg', sh / 'cache', *keys], log, env=benv)
        mod.PROG.watch(None)
        libs = ios / f'b-{chain}'
        n = sum(1 for _ in mod.shader_lib.view(libs).glob('*_b.metallib')) if mod.shader_lib.exists(libs) else 0
        if n == 0: raise mod.BuildError(f'no iOS shader libraries in {libs}')
        mod.shader_lib.pack(libs, mod.say, leave_out=pull is False)
        mod.say(f'{n:,} iOS shader libraries ({libs})')
        mod.PROG.end(f'{n:,} shaders ready (the playtests\' set)')
        return ios

    def build_shaders(py, repo, sh, xlate, env, logs, g, pkg_key=None, mac=False, seen=None, pull=None):
        keys = seen_for_phone(g, mac, seen)
        out = seen_ios(py, repo, sh, xlate, env, logs, g, keys, pull) if keys else orig(py, repo, sh, xlate, env, logs, g, pkg_key, mac, seen, pull)
        if not mac:   # the library is finished: the package it was built from and the per-shader cache are only for a later build of the same folder, and every build has a folder of its own
            n = 0
            for d in ('pkg', 'cache', 'partial'):
                n += cleanup._size(sh / d); mod.rmtree(sh / d)
            if n: mod.say(f'[cleanup] freed {n / 1e9:.1f} GB: the shader package and cache (the finished library stays)')
        return out
    mod.build_shaders = build_shaders


def _trace_steps(mod):
    """Marks (into the full log only) around the script's helper steps, and a chunked file hash: the script hashes every file of a package with read_bytes(), a whole file in memory at once."""
    import functools, hashlib, time
    def wrap(name):
        f = getattr(mod, name, None)
        if not callable(f): return
        @functools.wraps(f)
        def w(*a, **k):
            shim._mark(f'[step {time.strftime("%H:%M:%S")}] {name} ...')
            r = f(*a, **k)
            shim._mark(f'[step {time.strftime("%H:%M:%S")}] {name} done')
            return r
        setattr(mod, name, w)
    def fingerprint(*items, env=None):   # the script's own, but each file is hashed in chunks and a big one is logged
        h = hashlib.sha256()
        for it in items:
            kind, v = it if isinstance(it, tuple) and len(it) == 2 and it[0] in ('files', 'tree', 'stat', 'cmd') else ('repr', it)
            h.update(f'\0{kind}\0'.encode())
            if kind == 'files':
                for p in map(mod.rfs.Path, v):
                    h.update(p.name.encode() + b'\0')
                    try:
                        d = hashlib.sha256(); n = 0
                        with open(p, 'rb') as f:
                            while c := f.read(1 << 20): d.update(c); n += len(c)
                        if n > 200 << 20: shim._mark(f'[step] hashed {p.name}: {n >> 20} MB')
                        h.update(d.digest())
                    except OSError: h.update(b'missing')
            elif kind in ('tree', 'stat'):
                for rel, st in mod.files_under(v): h.update(f'{rel}\0{st.st_size}\0{st.st_mtime_ns if kind == "stat" else ""}\n'.encode())
            elif kind == 'cmd':
                try: r = mod.subprocess.run(v, env=env, capture_output=True, text=True, timeout=120); h.update((r.stdout + r.stderr).encode())
                except (OSError, mod.subprocess.TimeoutExpired): h.update(b'missing')
            else: h.update(repr(v).encode())
        return h.hexdigest()
    mod.fingerprint = fingerprint
    def package_key(pkg):   # file names and sizes, not their bytes: a phone does not read a multi-GB package again just to name it
        return mod.fingerprint([(rel, st.st_size) for rel, st in mod.files_under(pkg)])
    mod.package_key = package_key
    for n in ('split_shaders', 'package_key', 'split_output_key', 'swap_in', 'data_rows', 'table_difference', 'dlc_only_shader_change', 'compute_reader_additions',
              'reused', 'files_under', 'build_vk_shaders', 'build_gl_shaders', 'build_ios_shaders', 'capture_shaders', 'chain_header', 'provisional_prep', 'refine_after_rewrite'):
        if n not in ('files_under', 'reused', 'data_rows'): wrap(n)


def build(game_dir, keys, shell_app, out_dir=None, log=None, extra=()):
    repo = upstream()
    shim.install(log=log)
    os.environ['NXB_SHELL'] = str(shell_app) if shell_app else ''
    os.environ['NXB_UPSTREAM'] = str(repo)
    os.environ.setdefault('PATH', '/usr/bin:/bin')
    script = repo / 'scripts/build_ipa_from_nsp.py'
    spec = importlib.util.spec_from_file_location('nxnative_build_ipa', script)
    mod = importlib.util.module_from_spec(spec); sys.modules[spec.name] = mod
    sys.path.insert(0, str(script.parent))
    spec.loader.exec_module(mod)
    _phone_checks(mod)
    _phone_shaders(mod)
    _trace_steps(mod)
    argv = [str(game_dir), *(['-k', str(keys)] if keys else []), '--gpu', 'none', '--allow-other-metal', '--progress', 'json', *extra]
    if out_dir: argv += ['--work-dir', str(Path(out_dir) / 'build')]
    return mod.cli(argv)


if __name__ == '__main__':   # a test outside the app: python -m nxbuild.driver <game folder> <prod.keys> <shell .app> [out dir]
    a = sys.argv[1:]
    sys.exit(build(a[0], a[1], a[2], a[3] if len(a) > 3 else None, log=print))
