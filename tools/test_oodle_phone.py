"""The phone's stand-in for the Mac host (phone/nxbuild/oodle.py + shim.py), driven by nxnative's own code: python3 tools/test_oodle_phone.py <upstream checkout> <ooz testdata folder>
with NXB_OODLE_LIB = the Oodle library. uepak.OodleHost (Unreal paks), shader_split.oodle_ask (Trinity / PKZ / legacy paks; eight threads at once) and a DM_OODLE_JOB file (boot_mac's way)."""
import os, sys, struct, io, importlib.util, tempfile, threading, subprocess, glob
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '../phone'))
UP, td = sys.argv[1], sys.argv[2]
assert os.environ.get('NXB_OODLE_LIB'), 'NXB_OODLE_LIB'
from nxbuild import shim, oodle
shim.install(log=print)
bad = []
def chk(name, ok): print(('ok   ' if ok else 'FAIL ') + name); (ok or bad.append(name))
host = oodle.host_marker(tempfile.mkdtemp() + '/tools/dmhost')
def sample(n):
    d = open(f'{td}/{n}', 'rb').read(); r = struct.unpack_from('<Q', d)[0]; h = 8
    if r >= 1 << 40: r = struct.unpack_from('<I', d)[0]; h = 4
    return d[h:], r
# 1. uepak.OodleHost
sys.path.insert(0, UP + '/dm/gfx/tools'); sys.path.insert(0, UP + '/dm/tools')
import uepak
dec = uepak.OodleHost(host, '/tmp/mods', dict(os.environ))
c, r = sample('xml.mermaid'); out = dec(c, r); chk('uepak.OodleHost decodes a Mermaid stream', len(out) == r and out[:8] == b'elts.xml')
c2, r2 = sample('xml.kraken'); chk('... and the Kraken stream of the same file to the same bytes', dec(c2, r2) == out)
try: dec(b'\x8c\x0a' + b'\0' * 30, 5000); chk('a bad stream is an error', False)
except ValueError as e: chk('a bad stream is a ValueError that carries the host output', 'DM_OODLE_SERVE' in str(e))
dec.close()
# 2. shader_split.oodle_ask, from several threads at once
os.environ['DM_GAME'] = '0100F43008C44000'
spec = importlib.util.spec_from_file_location('shader_split', UP + '/dm/gfx/tools/shader_split.py'); ss = importlib.util.module_from_spec(spec)
os.environ['DM_OODLE_HOST'] = str(host); os.environ['DM_OODLE_MODULES'] = '/tmp/mods'
spec.loader.exec_module(ss)
res = {}
def work(i):
    nm = ['xml.mermaid', 'xml.kraken', 'osdb.selkie', 'reymont.leviathan'][i % 4]
    c, r = sample(nm)
    for _ in range(3): s, gone = ss.oodle_ask(c, r); res[(i, _)] = (nm, s is not None and len(s) == r, gone)
ts = [threading.Thread(target=work, args=(i,)) for i in range(8)]; [t.start() for t in ts]; [t.join() for t in ts]
chk('shader_split.oodle_ask, 8 threads x 3 requests', len(res) == 24 and all(v[1] and not v[2] for v in res.values()))
s, gone = ss.oodle_ask(b'\x8c\x0a' + b'\0' * 30, 5000); chk('a bad stream: (None, host still there)', s is None and not gone)
# 3. a job file through the shim's dispatch (what boot_mac does)
jd = tempfile.mkdtemp(); job = f'{jd}/oodle.job'
recs = [sample('xml.mermaid'), sample('mr.selkie'), (b'\x8c\x0a' + b'\0' * 30, 64)]
with open(job, 'wb') as f:
    f.write(b'DMOJ' + struct.pack('<I', len(recs)))
    for c, r in recs: f.write(struct.pack('<II', len(c), r) + c)
log = open(f'{jd}/log', 'w')
p = subprocess.Popen([str(host), '/tmp/mods'], env=dict(os.environ, DM_OODLE_JOB=job), cwd=jd, stdout=log, stderr=subprocess.STDOUT)
chk('the job runs as the host would (one record is bad: exit 1)', p.poll() == 1 and 'record 2' in open(f'{jd}/log').read())
o = open(job + '.out', 'rb').read(); chk('the job output: DMOR, 3 records, the first one whole', o[:4] == b'DMOR' and struct.unpack_from('<II', o, 4) == (3, 5345280))
sys.exit(1 if bad else 0)
