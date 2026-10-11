"""English voice samples in the SPU sound banks (VAB entries inside container BINs). Run by build.py for
--localization=audio|legends only (English audio; 2026-09-30); with Japanese audio the banks stay untouched.
A few short voices are not .at3 files but SPU samples: the title screen / title-menu voices (DEMO_DAT.BIN e_title.vab,
3 samples) and two in-game banks (BS16VAB1.BIN t_lb01b.vab, ST1A_02B.BIN t_lb02b.vab). The US PS1 disc has English
versions of the same banks (ee_title / et_lb01b / et_lb02b), found by comparing every VAB of both discs.
Rules: script/vab_voices.json. Output: build/vab_psp/<BIN>/<entry path> = the complete new container entry (0x800
header + VAB header padded to a sector + VAG body), which tools/pack_inplace.py --audio (internal flag, set by
build.py) splices in place of the PSP entry (entries after it shift, like a resized MSG).
Report: build/vab_psp/report.json. Check: tools/checks/verify_vab.py.

Container VAB entry (type 5): header +4 size = VAB header size + body, +8 sectors = 1 + sectors(VAB header) + sectors(body),
+0x14 SPU address, +0x18 VAB header size (checked on all six banks). The data holds the VAB header ('pBAV', programs,
tones, VAG size table), zero padding to the next sector, then the VAGs back to back. Each VAG: a zero block, data
blocks (flag 4 on the first, 1 on the last), then 00 07 77.. (Sony one-shot framing; asserted on the replaced VAGs,
both discs, and on everything written).
Each listed VAG = the PS1 English VAG verbatim, and its tone record = the PS1 English bank's record for it (same slot and
keys asserted; only pitch/volume may differ). The title voices play at 44.1 kHz on the PS1 (centre = key); the Japanese
PSP samples were ~30.4 kHz with a matching tone, so the English samples bring their own tone. No resampling or
re-encoding (project decision, 2026-09-30; an earlier version resampled the title voices to the PSP rate).
Everything else in the PSP bank (other VAGs, programs, tones, SPU address) stays PSP. The title bank grows to the PS1
English bank's size (SPU end 0x7A4D0, the PS1's own). See docs/RESEARCH.md §10 and §2 (container entries).
Usage: python3 tools/voice/build_vab.py"""
import sys, os, io, json, struct
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from rawiso import open_ps1
import inputs as IN, pycdlib
PS1 = 'originalDiskImages/ps1/Mega Man Legends (USA) (Track 1).bin'
OUT = 'build/vab_psp'
# pad: round up to a 0x800 sector. TAIL: the last 16-byte block of a one-shot VAG
def pad(n): return (n + 0x7FF) & ~0x7FF
TAIL = bytes([0, 7]) + b'\x77' * 14

# entry: offset of the container entry with this name (name at header + 0x40; type 5 = VAB)
def entry(data, name):
    for off in range(0, len(data) - 0x7FF, 0x800):
        if data[off+0x40:off+0x80].split(b'\0')[0] == name.encode():
            assert struct.unpack_from('<I', data, off)[0] == 5, name
            return off
    raise KeyError(name)

# parse: one VAB entry -> its parts. VAB header: 'pBAV' at +0, total size at +0xC, counts of programs / tones /
# VAGs (u16) at +0x12; 0x20 header + 0x800 program table, then 0x200 per program (16 tone records of 0x20 bytes),
# then the VAG size table (256 u16 in units of 8 bytes; entry 0 unused). In a tone record the VAG number
# (1-based) is the u16 at +0x16; bytes 6-7 are its key range
def parse(data, off):
    size, secs = struct.unpack_from('<II', data, off + 4); hs = struct.unpack_from('<I', data, off + 0x18)[0]
    o = off + 0x800; assert data[o:o+4] == b'pBAV'
    ps, ts, vs = struct.unpack_from('<HHH', data, o + 0x12)
    vo = 0x20 + 0x800 + 0x200 * ps; assert vo + 0x200 == hs, (hex(vo), hex(hs))
    sizes = [x << 3 for x in struct.unpack_from('<256H', data, o + vo)][1:vs + 1]
    assert struct.unpack_from('<I', data, o + 0xC)[0] == size == hs + sum(sizes)
    assert secs == 1 + pad(hs) // 0x800 + pad(sum(sizes)) // 0x800, (secs, hs, sum(sizes))
    # the VAG bodies start at the next sector after the VAB header
    p = o + pad(hs); v = []
    for s in sizes: v.append(bytes(data[p:p+s])); p += s
    tones = {}
    for pr in range(ps):
        for i in range(16):
            a = data[o+0x820+0x200*pr+0x20*i: o+0x820+0x200*pr+0x20*i+0x20]; n = struct.unpack_from('<H', a, 0x16)[0]
            if n: tones.setdefault(n, []).append((0x820 + 0x200 * pr + 0x20 * i, bytes(a)))
    return dict(off=off, hdr=bytes(data[off:off+0x800]), vabhdr=bytes(data[o:o+hs]), hs=hs, vags=v, tones=tones, secs=secs)

# framing_ok: 16-byte blocks; first all zero, last = TAIL, flag byte (block byte 1) 4 on the first data block,
# 1 on the last, 0 between
def framing_ok(v):
    b = [v[i:i+16] for i in range(0, len(v), 16)]
    return (len(v) % 16 == 0 and b[0] == b'\0' * 16 and b[-1] == TAIL and b[1][1] == 4 and b[-2][1] == 1
            and all(x[1] == 0 for x in b[2:-2]))

def main():
    rules = json.load(open('script/vab_voices.json'))['banks']
    ps1 = open_ps1(PS1); psp = pycdlib.PyCdlib(); psp.open(IN.PSP); rep = []
    for r in rules:
        get = lambda iso, p: (lambda f: (iso.get_file_from_iso_fp(f, iso_path=p), f.getvalue())[1])(io.BytesIO())
        A = get(ps1, f'/CDDATA/DAT/{r["bin"]}.BIN;1'); B = get(psp, f'/PSP_GAME/USRDIR/DAT/{r["bin"]}.BIN')
        a = parse(A, entry(A, r['ps1_entry'])); b = parse(B, entry(B, r['psp_entry']))
        assert len(a['vags']) == len(b['vags']) and all(framing_ok(a['vags'][n-1]) and framing_ok(b['vags'][n-1]) for n in r['vags'])
        vags = list(b['vags']); info = []; tone_set = []
        for n in r['vags']:
            ta, tb = a['tones'][n], b['tones'][n]; assert len(ta) == len(tb) == 1
            # the tone that plays VAG n must sit in the same slot and cover the same keys in both banks
            assert ta[0][0] == tb[0][0] and ta[0][1][6:8] == tb[0][1][6:8], ('tone slot/keys differ', r['bin'], n)
            vags[n-1] = a['vags'][n-1]; info.append(dict(vag=n, bytes=len(vags[n-1]), old=len(b['vags'][n-1])))
            if ta[0][1] != tb[0][1]:
                tone_set.append((tb[0][0], ta[0][1])); info[-1]['tone_from_ps1'] = [i for i in range(32) if ta[0][1][i] != tb[0][1][i]]
        # untouched VAGs byte-identical to the PSP; replaced ones are exactly the English
        body = b''.join(vags); vh = bytearray(b['vabhdr'])
        for pos, t in tone_set: vh[pos:pos+32] = t
        # new VAB header: PS1 tone records where they differ, total size, and the VAG size table (bytes / 8)
        struct.pack_into('<I', vh, 0xC, b['hs'] + len(body))
        vo = 0x20 + 0x800 + 0x200 * struct.unpack_from('<H', vh, 0x12)[0]
        for i, v in enumerate(vags): assert len(v) % 8 == 0 and len(v) >> 3 < 0x10000; struct.pack_into('<H', vh, vo + 2 * (i + 1), len(v) >> 3)
        # new entry header: size (+4) and sector count (+8); the SPU address (+0x14) is unchanged
        h = bytearray(b['hdr']); struct.pack_into('<I', h, 4, b['hs'] + len(body))
        secs = 1 + pad(b['hs']) // 0x800 + pad(len(body)) // 0x800; struct.pack_into('<I', h, 8, secs)
        ent = bytes(h) + bytes(vh) + b'\0' * (pad(b['hs']) - b['hs']) + body + b'\0' * (pad(len(body)) - len(body))
        spu = struct.unpack_from('<I', h, 0x14)[0]
        p = os.path.join(OUT, r['bin'], r['psp_entry'][3:].replace('\\', '/')); os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, 'wb').write(ent)
        rep.append(dict(bin=r['bin'], entry=r['psp_entry'], sectors=[b['secs'], secs], body=[sum(map(len, b['vags'])), len(body)],
                        spu_end=[hex(spu + sum(map(len, b['vags']))), hex(spu + len(body))], ps1_spu_end=hex(spu + sum(map(len, a['vags']))), vags=info))
        print(f"{r['bin']}: {len(r['vags'])} VAGs, body {sum(map(len, b['vags']))} -> {len(body)}, sectors {b['secs']} -> {secs}, SPU end {rep[-1]['spu_end'][1]}")
    json.dump(rep, open(OUT + '/report.json', 'w'), indent=1)

if __name__ == '__main__': main()
