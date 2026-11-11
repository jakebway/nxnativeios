#!/usr/bin/env python3
"""Write a game's rewritten modules into a Mach-O dylib, with no compiler, assembler or linker.

This replaces nxnative's dm/ios/tools/gen_embed.py + clang + ld for the iPhone builder: the output
holds exactly the sections loader.c reads through dm_set_game_image_header():

  __TEXT,__dm<tag><name>x0   original text        (r-x)
  __DM<tag><name>W,__img     rest of ro+data+bss  (rw-, own segment)
  __TEXT,__dm<tag><name>x1   patch area           (r-x)
  __TEXT,__dm<tag><name>x2   back patch area, only when the module has one
  __TEXT,__dm<tag>_nro_x0 / __DM<tag>_NRO_W,__img / __TEXT,__dm<tag>_nro_x1 + __DATA,__dm<tag>_nro_tab   (packed NROs)
  __TEXT,__dm<tag>_jit       (optional nn::jit image)

Every piece is 16 KiB aligned, as gen_embed.py places them (vm_remap takes whole pages).
The dylib is unsigned: FlareStore (or any sideloader) signs it with the rest of the IPA.
Pure Python 3, standard library only, so it runs in the embedded Python on the phone.

Usage: mkgameframework.py [--tag T] [--jit jit.img] [--platform ios|macos] [--install-name N] <build out dir> <output dylib> <module name...>
Based on nxnative's gen_embed.py (MIT).
"""
import argparse, hashlib, os, struct

PG = 0x4000
def r16(x): return (x + PG - 1) & ~(PG - 1)

# ---- module pieces: same arithmetic as gen_embed.py pieces() ----
def pieces(out, n):
    hdr = dict(l[2:].split() for l in open(f'{out}/{n}.fixups.tsv'))
    te, po = int(hdr['TEXT_END'], 16), int(hdr['PATCH_OFF'], 16)
    ko, ks = int(hdr['KEY_PAGE_OFF'], 16), int(hdr['KEY_PAGE_SIZE'], 16)
    b = os.path.abspath(f'{out}/{n}.patched.bin'); sz = os.path.getsize(b)
    a, end = r16(te), r16(sz)
    if po < 0:
        fl, bl = int(hdr['FILE_IMAGE_LEN'], 16), int(hdr.get('BACK_LEN', '0'), 16)
        assert fl % PG == 0 and a <= fl and ko % PG == 0 and ks == PG and ko >= fl and bl % PG == 0 and (not bl or sz % PG == 0)
        return b, sz, ((0, a), (a, fl), (fl, end - bl)) + (((end - bl, end),) if bl else ())
    assert po % PG == 0 and a <= ko and ko + ks <= po and ko % PG == 0 and ks == PG
    return b, sz, ((0, a), (a, po), (po, end))

class Blob:
    """A section's content: a list of (file, lo, fill, total) chunks, or raw bytes."""
    def __init__(self): self.parts = []; self.size = 0
    def add_file(self, path, sz, lo, hi):
        assert self.size % PG == 0
        fill = max(0, min(hi, sz) - lo)
        self.parts.append(('f', path, lo, fill, r16(hi - lo))); self.size += r16(hi - lo)
    def add_bytes(self, data): self.parts.append(('b', data)); self.size += len(data)

def layout_sections(out, names, tag, jit):
    """[(segment, section, Blob)] in gen_embed.py's order."""
    secs = []
    for n in names:
        b, sz, parts = pieces(out, n)
        for (seg, sect), (lo, hi) in zip((('__TEXT', f'__dm{tag}{n}x0'), (f'__DM{tag}{n}W', '__img'),
                                          ('__TEXT', f'__dm{tag}{n}x1'), ('__TEXT', f'__dm{tag}{n}x2')), parts):
            assert len(seg) <= 16 and len(sect) <= 16, (seg, sect)
            bl = Blob(); bl.add_file(b, sz, lo, hi); secs.append((seg, sect, bl))
    tab = os.path.join(out, 'nro.tsv')
    nros = [l.split('\t')[0] for l in open(tab) if l.strip() and not l.startswith('#') and not l.startswith('refused\t')] if os.path.exists(tab) else []
    if nros:
        at, rows = [0, 0, 0], []
        for i, (seg, sect) in enumerate((('__TEXT', f'__dm{tag}_nro_x0'), (f'__DM{tag}_NRO_W', '__img'), ('__TEXT', f'__dm{tag}_nro_x1'))):
            bl = Blob()
            for k, n in enumerate(nros):
                b, sz, parts = pieces(out, n); lo, hi = parts[i]
                assert len(parts) == 3, f'NRO {n} has a back patch area'
                if i == 0: rows.append([n])
                rows[k] += [at[i], hi - lo]; at[i] += hi - lo
                bl.add_file(b, sz, lo, hi)
            secs.append((seg, sect, bl))
        t = Blob(); data = b''
        for r in rows:
            assert len(r[0]) < 32
            data += r[0].encode().ljust(32, b'\0') + struct.pack('<6Q', *r[1:])
        t.add_bytes(data); secs.append(('__DATA', f'__dm{tag}_nro_tab', t))
    if jit:
        bl = Blob(); sz = os.path.getsize(jit); bl.add_file(os.path.abspath(jit), sz, 0, r16(sz)); secs.append(('__TEXT', f'__dm{tag}_jit', bl))
    return secs

# ---- Mach-O constants ----
MH_MAGIC_64, CPU_TYPE_ARM64, MH_DYLIB = 0xfeedfacf, 0x0100000c, 6
MH_NOUNDEFS, MH_DYLDLINK, MH_TWOLEVEL, MH_NO_REEXPORTED_DYLIBS = 0x1, 0x4, 0x80, 0x100000
LC_SEGMENT_64, LC_SYMTAB, LC_DYSYMTAB, LC_ID_DYLIB, LC_LOAD_DYLIB = 0x19, 0x2, 0xb, 0xd, 0xc
LC_UUID, LC_BUILD_VERSION = 0x1b, 0x32
LC_DYLD_EXPORTS_TRIE, LC_DYLD_CHAINED_FIXUPS = 0x80000033, 0x80000034
PLATFORM = {'macos': 1, 'ios': 2}
VM_R, VM_W, VM_X = 1, 2, 4
S_ATTR_PURE_INSTRUCTIONS, S_ATTR_SOME_INSTRUCTIONS = 0x80000000, 0x400
HEADER_PAD = 0x1000   # room for the signer's LC_CODE_SIGNATURE (and any load command a sideloader adds)

def ver(s):
    p = [int(x) for x in s.split('.')] + [0, 0]
    return (p[0] << 16) | (p[1] << 8) | p[2]

def lc_str(cmd, fixed, s):
    raw = s.encode() + b'\0'
    size = (len(fixed) + 8 + len(raw) + 7) & ~7
    return struct.pack('<II', cmd, size) + fixed + raw.ljust(size - 8 - len(fixed), b'\0')

def write_dylib(secs, dst, platform='ios', install_name='@rpath/NXGame.framework/NXGame', minos='26.0', sdk='26.0'):
    # Group sections into segments, keeping first-seen order; __TEXT first (it holds the header), __DATA and the W segments next, __LINKEDIT last.
    order = ['__TEXT']
    for seg, _, _ in secs:
        if seg not in order: order.append(seg)
    segs = {s: [x for x in secs if x[0] == s] for s in order}
    nseg = len(order) + 1   # + __LINKEDIT
    nsect = len(secs)
    # load commands
    lc_sizes = 72 * nseg + 80 * nsect
    id_dylib = lc_str(LC_ID_DYLIB, struct.pack('<IIII', 24, 2, 0x10000, 0x10000), install_name)
    libsys = lc_str(LC_LOAD_DYLIB, struct.pack('<IIII', 24, 2, 0x10000, 0x10000), '/usr/lib/libSystem.B.dylib')
    other = len(id_dylib) + len(libsys) + 24 + 32 + 16 + 16 + 24 + 80   # uuid, build_version(+1 tool), chained fixups, exports trie, symtab, dysymtab
    sizeofcmds = lc_sizes + other
    hdr_end = 32 + sizeofcmds
    assert hdr_end + HEADER_PAD <= PG, 'too many sections for one header page'
    # assign file offsets / addresses: every section 16K aligned; each segment starts on a 16K boundary
    vm = 0; fo = 0; seginfo = []
    for s in order:
        start_vm, start_fo = vm, fo
        if s == '__TEXT': vm = fo = PG   # header page
        addr = []
        for seg, sect, bl in segs[s]:
            align = 14 if (seg == '__TEXT' or seg.startswith('__DM')) else 3
            if align == 14: vm, fo = r16(vm), r16(fo)
            else: vm, fo = (vm + 7) & ~7, (fo + 7) & ~7
            addr.append((vm, fo)); vm += bl.size; fo += bl.size
        vm, fo = r16(vm), r16(fo)
        if s != '__TEXT' and not segs[s]: continue
        seginfo.append((s, start_vm, vm - start_vm, start_fo, fo - start_fo, addr))
    # __LINKEDIT: chained fixups header + empty exports trie
    le_fo, le_vm = fo, vm
    nseg_starts = nseg
    # dyld_chained_fixups_header (28 bytes) then dyld_chained_starts_in_image {seg_count, seg_info_offset[seg_count]} (all 0 = no fixups)
    starts_off = 32
    starts = struct.pack('<I', nseg_starts) + b'\0' * 4 * nseg_starts
    imports_off = (starts_off + len(starts) + 3) & ~3
    fix = struct.pack('<7I', 0, starts_off, imports_off, imports_off, 0, 1, 0).ljust(starts_off, b'\0') + starts
    fix = fix.ljust(imports_off + 8, b'\0')   # symbols pool: one empty string
    fix = fix.ljust((len(fix) + 7) & ~7, b'\0')
    trie = b'\0\0'.ljust(8, b'\0')
    linkedit = fix + trie
    linkedit_size = r16(len(linkedit))
    # ---- build header ----
    cmds = b''
    for (s, svm, svmsize, sfo, sfosize, addr) in seginfo:
        is_text = s == '__TEXT'
        prot = VM_R | VM_X if is_text else VM_R | VM_W
        ss = segs[s]
        cmds += struct.pack('<II16sQQQQiiII', LC_SEGMENT_64, 72 + 80 * len(ss), s.encode(), svm, svmsize, sfo, sfosize, prot, prot, len(ss), 0)
        for (seg, sect, bl), (a, f) in zip(ss, addr):
            align = 14 if (is_text or seg.startswith('__DM')) else 3
            flags = (S_ATTR_PURE_INSTRUCTIONS | S_ATTR_SOME_INSTRUCTIONS) if is_text else 0
            cmds += struct.pack('<16s16sQQIIIIIIII', sect.encode(), seg.encode(), a, bl.size, f, align, 0, 0, flags, 0, 0, 0)
    cmds += struct.pack('<II16sQQQQiiII', LC_SEGMENT_64, 72, b'__LINKEDIT', le_vm, linkedit_size, le_fo, len(linkedit), VM_R, VM_R, 0, 0)
    cmds += id_dylib + libsys
    h = hashlib.sha256()
    for seg, sect, bl in secs: h.update(f'{seg},{sect},{bl.size};'.encode())
    u = bytearray(h.digest()[:16]); u[6] = (u[6] & 0x0f) | 0x40; u[8] = (u[8] & 0x3f) | 0x80
    cmds += struct.pack('<II16s', LC_UUID, 24, bytes(u))
    cmds += struct.pack('<IIIIIIII', LC_BUILD_VERSION, 32, PLATFORM[platform], ver(minos), ver(sdk), 1, 3, ver('1.0'))   # 1 tool: ld
    cmds += struct.pack('<IIII', LC_DYLD_CHAINED_FIXUPS, 16, le_fo, len(fix))
    cmds += struct.pack('<IIII', LC_DYLD_EXPORTS_TRIE, 16, le_fo + len(fix), len(trie))
    cmds += struct.pack('<IIIIII', LC_SYMTAB, 24, le_fo + len(linkedit), 0, le_fo + len(linkedit), 0)
    cmds += struct.pack('<20I', LC_DYSYMTAB, 80, *([0] * 18))
    assert len(cmds) == sizeofcmds, (len(cmds), sizeofcmds)
    ncmds = nseg + 8
    head = struct.pack('<IiiIIIII', MH_MAGIC_64, CPU_TYPE_ARM64, 0, MH_DYLIB, ncmds, sizeofcmds,
                       MH_NOUNDEFS | MH_DYLDLINK | MH_TWOLEVEL | MH_NO_REEXPORTED_DYLIBS, 0) + cmds
    # ---- write ----
    with open(dst, 'wb') as o:
        o.write(head)
        for (s, svm, svmsize, sfo, sfosize, addr) in seginfo:
            for (seg, sect, bl), (a, f) in zip(segs[s], addr):
                o.seek(f)
                for p in bl.parts:
                    if p[0] == 'b': o.write(p[1]); continue
                    _, path, lo, fill, total = p
                    start = o.tell()
                    with open(path, 'rb') as i:
                        i.seek(lo); left = fill
                        while left:
                            c = i.read(min(left, 8 << 20)); assert c, f'{path} ended early'; o.write(c); left -= len(c)
                    o.seek(start + total)   # zero fill up to the piece's 16K end
        o.seek(le_fo); o.write(linkedit)
        o.truncate(le_fo + len(linkedit))
    return dst

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--tag', default=''); ap.add_argument('--jit')
    ap.add_argument('--platform', default='ios', choices=PLATFORM)
    ap.add_argument('--install-name', default='@rpath/NXGame.framework/NXGame')
    ap.add_argument('out'); ap.add_argument('dst'); ap.add_argument('names', nargs='+')
    a = ap.parse_args()
    write_dylib(layout_sections(a.out, a.names, a.tag, a.jit), a.dst, a.platform, a.install_name)
    print(a.dst)

if __name__ == '__main__': main()
