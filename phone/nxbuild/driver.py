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
    for n in ('split_shaders', 'package_key', 'split_output_key', 'swap_in', 'data_rows', 'table_difference', 'dlc_only_shader_change', 'compute_reader_additions',
              'rmtree', 'reused', 'files_under', 'build_vk_shaders', 'build_gl_shaders', 'build_ios_shaders', 'capture_shaders', 'chain_header', 'provisional_prep', 'refine_after_rewrite'):
        if n not in ('files_under', 'reused', 'data_rows'): wrap(n)
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
    _trace_steps(mod)
    argv = [str(game_dir), *(['-k', str(keys)] if keys else []), '--gpu', 'none', '--allow-other-metal', '--progress', 'json', *extra]
    if out_dir: argv += ['--work-dir', str(Path(out_dir) / 'build')]
    return mod.cli(argv)


if __name__ == '__main__':   # a test outside the app: python -m nxbuild.driver <game folder> <prod.keys> <shell .app> [out dir]
    a = sys.argv[1:]
    sys.exit(build(a[0], a[1], a[2], a[3] if len(a) > 3 else None, log=print))
