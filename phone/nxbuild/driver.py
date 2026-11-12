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
    argv = [str(game_dir), *(['-k', str(keys)] if keys else []), '--gpu', 'none', '--allow-other-metal', '--progress', 'json', *extra]
    if out_dir: argv += ['--work-dir', str(Path(out_dir) / 'build')]
    return mod.cli(argv)


if __name__ == '__main__':   # a test outside the app: python -m nxbuild.driver <game folder> <prod.keys> <shell .app> [out dir]
    a = sys.argv[1:]
    sys.exit(build(a[0], a[1], a[2], a[3] if len(a) > 3 else None, log=print))
