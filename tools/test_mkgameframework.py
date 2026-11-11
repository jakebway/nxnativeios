#!/usr/bin/env python3
"""Synthetic modules -> mkgameframework -> check every section's bytes against gen_embed.py's piece arithmetic.
With lief installed, the Mach-O is parsed by lief; on macOS (--dlopen) it is also built for macOS and dlopen'ed,
and each section is read back with getsectiondata(), the way loader.c reads it."""
import ctypes, os, random, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mkgameframework as mk
PG = mk.PG

def module(d, name, size, hdr):
    data = random.Random(name).randbytes(size)
    open(f'{d}/{name}.patched.bin', 'wb').write(data)
    open(f'{d}/{name}.fixups.tsv', 'w').write(''.join(f'# {k} {v:#x}\n' for k, v in hdr.items()))
    return data

def expected(d, names, tag):
    """(seg, sect) -> bytes, from the same pieces gen_embed.py would .incbin"""
    exp = {}
    for seg, sect, bl in mk.layout_sections(d, names, tag, None):
        buf = bytearray()
        for p in bl.parts:
            if p[0] == 'b': buf += p[1]; continue
            _, path, lo, fill, total = p
            with open(path, 'rb') as f: f.seek(lo); buf += f.read(fill).ljust(total, b'\0')
        exp[(seg, sect)] = bytes(buf)
    return exp

def main():
    d = tempfile.mkdtemp()
    module(d, 'main', 0x23000 + 123, dict(TEXT_END=0x5100, PATCH_OFF=0x20000, KEY_PAGE_OFF=0x1c000, KEY_PAGE_SIZE=PG))
    module(d, 'sdk', 0x48000, dict(TEXT_END=0x9000, PATCH_OFF=-0x8000, FILE_IMAGE_LEN=0x30000, KEY_PAGE_OFF=0x34000, KEY_PAGE_SIZE=PG, BACK_LEN=0x8000))
    for n in ('nroa', 'nrob'): module(d, n, 0x14000, dict(TEXT_END=0x4000, PATCH_OFF=0xc000, KEY_PAGE_OFF=0x8000, KEY_PAGE_SIZE=PG))
    open(f'{d}/nro.tsv', 'w').write('# name\nnroa\t1\nrefused\tx\nnrob\t2\n')
    names = ['main', 'sdk']
    plat = 'macos' if '--dlopen' in sys.argv else 'ios'
    out = mk.write_dylib(mk.layout_sections(d, names, '', None), f'{d}/NXGame', plat)
    exp = expected(d, names, '')
    raw = open(out, 'rb').read()
    ok = True
    try:
        import lief
        b = lief.MachO.parse(out).at(0)
        got = {(s.segment_name, s.name): s for s in b.sections}
        for k, v in exp.items():
            s = got.get(k)
            if s is None: print('MISSING', k); ok = False; continue
            fbytes = raw[s.offset:s.offset + s.size]
            if s.size != len(v) or fbytes != v: print('BAD', k, hex(s.size), hex(len(v))); ok = False
            elif s.offset % (PG if k[0] != '__DATA' else 8): print('MISALIGNED', k); ok = False
        print('lief: %d sections, %d segments, file %d bytes' % (len(b.sections), len(b.segments), len(raw)))
    except ImportError:
        print('lief not installed: header parse skipped')
    if '--dlopen' in sys.argv:   # macOS only: what loader.c actually does
        h = ctypes.CDLL(out)   # dlopen
        dyld = ctypes.CDLL(None)
        dyld._dyld_image_count.restype = ctypes.c_uint32
        dyld._dyld_get_image_name.restype = ctypes.c_char_p
        dyld._dyld_get_image_header.restype = ctypes.c_void_p
        mh = next(dyld._dyld_get_image_header(i) for i in range(dyld._dyld_image_count()) if os.path.realpath(dyld._dyld_get_image_name(i).decode()) == os.path.realpath(out))
        dyld.getsectiondata.restype = ctypes.c_void_p
        dyld.getsectiondata.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.POINTER(ctypes.c_ulong)]
        for (seg, sect), v in exp.items():
            n = ctypes.c_ulong()
            p = dyld.getsectiondata(mh, seg.encode(), sect.encode(), ctypes.byref(n))
            if not p or n.value != len(v) or ctypes.string_at(p, n.value) != v or (seg != '__DATA' and p & (PG - 1)):
                print('DLOPEN BAD', seg, sect); ok = False
        print('dlopen + getsectiondata: checked', len(exp), 'sections')
    print('OK' if ok else 'FAIL'); sys.exit(0 if ok else 1)

if __name__ == '__main__': main()
