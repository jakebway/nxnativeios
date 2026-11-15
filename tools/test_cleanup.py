"""phone/nxbuild/cleanup.py: the disk check, the sweep of leftovers, and the cleanup after a failure."""
import errno, os, sys, tempfile, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'phone'))
from nxbuild import cleanup

d = Path(tempfile.mkdtemp(prefix='nxb-cleanup-test-'))
(d / 'a.nsp').write_bytes(b'x' * (70 << 20)); (d / 'k.keys').write_text('x')
assert cleanup.game_bytes([str(d / 'a.nsp'), str(d / 'k.keys')]) == 70 << 20   # small files count for nothing
(d / 'b.nsz').write_bytes(b'x' * (70 << 20)); assert cleanup.game_bytes([str(d / 'b.nsz')]) == int((70 << 20) * 1.6)
logs = []; cleanup.preflight([str(d / 'a.nsp')], d, logs.append); assert logs and logs[0].startswith('[disk]')
real = cleanup.free_bytes
cleanup.free_bytes = lambda p: 100 << 20
try: cleanup.preflight([str(d / 'a.nsp')], d, logs.append); raise SystemExit('a full disk was not refused')
except RuntimeError as e: assert 'Not enough storage' in str(e)
cleanup.free_bytes = lambda p: int((70 << 20) * 2)   # between the refusal and the safe amount: a warning, the build goes on
logs.clear(); cleanup.preflight([str(d / 'a.nsp')], d, logs.append); assert any('[RED] storage is tight' in l for l in logs)
cleanup.free_bytes = real
j = d / 'job'
for sub, data in (('build/x/shader/pkg/a.bin', 1000), ('build/extract.partial/f', 500), ('input/game/g.nsp', 100), ('build/extract/keep', 1)): (j / sub).parent.mkdir(parents=True, exist_ok=True); (j / sub).write_bytes(b'.' * data)
cleanup.after_failure(j, lambda m: None)
left = sorted(str(p.relative_to(j)) for p in j.rglob('*') if p.is_file()); assert left == ['build/extract/keep'], left   # only the extraction stays
t = Path(tempfile.gettempdir()) / 'split-spill-test'; t.write_bytes(b'0' * 10); os.utime(t, (time.time() - 4000,) * 2)
assert cleanup.sweep_temp(None) >= 10 and not t.exists()
assert 'ran out of storage' in cleanup.friendly(OSError(errno.ENOSPC, 'No space left on device'), d)
assert cleanup.friendly(ValueError('other'), d) == 'other'
print('ok')
