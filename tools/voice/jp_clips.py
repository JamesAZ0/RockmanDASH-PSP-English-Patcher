"""Japanese voice clips: (bank, clip) -> .at3 path and length, from the EBOOT tables and the Japanese ISO (read-only)
-> build/voice_en/jp_clips.json. build.py runs it when that file is missing. Used by tools/voice/voice_map.py (clip
lengths for placing the Japanese voice ops) and tools/voice/build_audio.py (the stream paths, banks 0x33 / 0x34).
EBOOT (Sony's original, decrypted_eboot/ULJM05030_EBOOT.BIN): one flat array of 865 path pointers at va 0x24ECE0, and
a per-bank table at va 0x24FA64 (53 banks; each used bank points at its first path, 0 = unused bank). A bank's
clips run to the next bank's first path. Length = fact end sample / 44100. The tables were found by following the
voice lookup code (0xACA0 / 0xADAC); see docs/RESEARCH.md §10.
Usage: python3 tools/voice/jp_clips.py"""
import sys, os, struct, io, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..')); import inputs, pycdlib
# SEG: virtual address of segments 0 and 1. rel: {relocated address: info} from .rel.data (file offset 0x3CF6D0,
# 0x1E6F0 bytes; 8-byte entries offset + info, info = type | offset base << 8 | address base << 16)
E = open('decrypted_eboot/ULJM05030_EBOOT.BIN', 'rb').read(); SEG = [0, 0x245200]; rel = {}
for k in range(0x1E6F0 // 8):
    o, i = struct.unpack_from('<II', E, 0x3CF6D0 + 8 * k); rel[o + SEG[(i >> 8) & 0xFF]] = i
# ptr: the pointer stored at va as the loader would relocate it (None if the word has no relocation: an unused
# bank slot); cstr: the 0-terminated string at va. File offset = va + 0x80
def ptr(va): return struct.unpack_from('<I', E, 0x80 + va)[0] + SEG[(rel[va] >> 16) & 0xFF] if va in rel else None
def cstr(va): e = E.index(b'\0', 0x80 + va); return E[0x80 + va:e].decode()
iso = pycdlib.PyCdlib(); iso.open(inputs.PSP)
# starts: {bank: index of its first path in the flat array}; a bank ends where the next one (by index) starts
starts = {b: (ptr(0x24FA64 + 4 * b) - 0x24ECE0) // 4 for b in range(53) if ptr(0x24FA64 + 4 * b)}
order = sorted(starts.items(), key=lambda x: x[1]); out = {}
for n, (b, s) in enumerate(order):
    e = order[n + 1][1] if n + 1 < len(order) else 865
    for c in range(s, e):
        # the game path is 'disc0:/PSP_GAME/...'; the clip length comes from the file's fact chunk (first u32 =
        # end sample)
        p = cstr(ptr(0x24ECE0 + 4 * c)).replace('disc0:', '')
        bb = io.BytesIO(); iso.get_file_from_iso_fp(bb, iso_path=p); x = bb.getvalue(); fi = x.find(b'fact')
        out['%d,%d' % (b, c - s)] = dict(path=p.split('/at3/')[1], seconds=round(struct.unpack_from('<I', x, fi + 8)[0] / 44100, 3))
os.makedirs('build/voice_en', exist_ok=True)
json.dump(dict(bank_start=starts, clips=out), open('build/voice_en/jp_clips.json', 'w'), indent=0)
print(len(out), 'Japanese clips in', len(starts), 'banks')
