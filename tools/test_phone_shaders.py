"""phone/nxbuild/driver.py _phone_shaders: which games get the playtests' shader set on the phone, how dmsh_build.py is called for it, and what the step gives back. Upstream's script is stubbed."""
import sys, tempfile, types
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'phone'))
from nxbuild import driver

calls = []; said = []
class G:
    def __init__(s, seen): s.seen = seen
    def table(s, n):
        class T:
            def is_file(t): return s.seen
        return T()
mod = types.SimpleNamespace(
    PROG=types.SimpleNamespace(stage=lambda *a, **k: calls.append(('stage', a)), watch=lambda w: None, end=lambda *a: None),
    say=said.append, ALLOW_OTHER_METAL=False, BuildError=RuntimeError,
    chain_of=lambda repo: 'abc123abc123',
    shader_keys=lambda g: [f'{i:016x}' for i in range(1000)],
    seen_listed=lambda g: {f'{i:016x}' for i in range(0, 1000, 20)} | {'ffffffffffffffff'},   # one key the map does not know
    rmtree=lambda p: __import__('shutil').rmtree(p, ignore_errors=True) if Path(p).is_dir() else (Path(p).unlink() if Path(p).exists() else None),
    ShaderWatch=lambda p: None,
    shader_lib=types.SimpleNamespace(view=lambda p: Path(p), exists=lambda p: True, pack=lambda *a, **k: calls.append(('pack', a[0].name, k))),
)
def run(cmd, log, env=None, **k):
    calls.append(('run', [str(c) for c in cmd[1:]], {k2: env[k2] for k2 in ('DMSH_TARGETS', 'IOSOUT', 'DMSH_CAS', 'DMSH_IOS_PULL') if k2 in env}))
    (Path(env['IOSOUT']) / 'b-abc123abc123').mkdir(parents=True, exist_ok=True); (Path(env['IOSOUT']) / 'b-abc123abc123/k_b.metallib').write_bytes(b'x')
mod.run = run
mod.build_shaders = lambda *a, **k: calls.append(('FULL',)) or Path(a[2]) / 'ios'
driver._phone_shaders(mod)

def go(seen_file, **kw):
    calls.clear(); sh = Path(tempfile.mkdtemp()) / 'sh'
    for d in ('pkg', 'cache', 'partial'): (sh / d).mkdir(parents=True); (sh / d / 'big').write_bytes(b'0' * 1000)
    out = mod.build_shaders('py', Path('/repo'), sh, '/x', {}, sh, G(seen_file), 'k', False, None, kw.get('pull'))
    assert not any((sh / d).exists() for d in ('pkg', 'cache', 'partial')), 'the big work files stay'
    return sh, out

sh, out = go(True)
r = [c for c in calls if c[0] == 'run'][0]
assert r[1][1:3] == [str(sh / 'pkg'), str(sh / 'cache')] or r[1][2:4] == [str(sh / 'pkg'), str(sh / 'cache')], r
keys = r[1][3:]; assert len(keys) == 50 and 'ffffffffffffffff' not in keys and keys == sorted(keys), len(keys)   # only keys the map knows
assert r[2]['DMSH_TARGETS'] == 'ios' and r[2]['IOSOUT'] == str(sh / 'ios') and r[2]['DMSH_CAS'].endswith('cache/cas.db')
assert out == sh / 'ios' and ('pack', 'b-abc123abc123', {'leave_out': False}) in calls
sh, out = go(True, pull=False); assert [c for c in calls if c[0] == 'run'][0][2]['DMSH_IOS_PULL'] == '0'
go(False); assert ('FULL',) in calls and not any(c[0] == 'run' for c in calls), 'a game without a list builds the whole map'
import os; os.environ['NXB_SEEN'] = '0'; go(True); assert ('FULL',) in calls, 'NXB_SEEN=0 builds the whole map'
print('ok')
