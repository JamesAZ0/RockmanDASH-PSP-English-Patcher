"""English voice banks on the PSP: which free bank slot each PS1 English voice bank uses, and the clip file names.
Used with English audio (--localization=audio|legends). Shared by build_text.py, build_audio.py,
patch_eboot_voice.py and verify_voice.py.
The PSP voice lookup (EBOOT 0xACA0/0xADAC, static analysis): sound id = type<<28 | bank<<16 | clip; per-bank table at
va 0x24FA64 (53 slots, seg-1 offset 0xA864; 16 used by the Japanese: 0,3,5,6,8,A,B,C,19,1C,1D,30-34) -> array of
path pointers. Only null checks. Bank 6 is special (clips 0x12-0x2E also start the TV-news subtitle scenes), so
English banks use free slots only. PS1 English bank b (0-35, XA1806E..XA1880E in name order) -> SLOTS[b], the first 36
of the 37 free slots. Clip n = the clip's rank by first sector in its bank (tools/voice/extract_voice_en.py; checked
against the PS1 script: 630/646). build_text.py rewrites each English AUDIO op's bank b to SLOTS[b]; without that
the PS1 bank numbers name missing banks (nothing plays and the text box waits) or wrong Japanese clips.
See docs/RESEARCH.md §10."""
import csv, os
# the bank slots the Japanese game uses (non-zero entries of the bank table in Sony's EBOOT)
JP_USED = {0, 3, 5, 6, 8, 0xA, 0xB, 0xC, 0x19, 0x1C, 0x1D, 0x30, 0x31, 0x32, 0x33, 0x34}
SLOTS = [s for s in range(53) if s not in JP_USED][:36]
assert len(SLOTS) == 36 and 6 not in SLOTS
BANK_TABLE_SEG1 = 0xA864            # seg-1 offset of the per-bank table (va 0x24FA64)
DIR = 'xaen'                        # new folder /PSP_GAME/USRDIR/DAT/at3/xaen (sorts after xa37s00: last in at3 and in the path table)
# clip_name: eBB_CC.at3 with the PS1 bank and clip numbers in decimal; iso_path / game_path: its place on the disc
# and the path string the game opens
def clip_name(bank, clip): return 'e%02d_%02d.at3' % (bank, clip)
def iso_path(bank, clip): return '/PSP_GAME/USRDIR/DAT/at3/%s/%s' % (DIR, clip_name(bank, clip))
def game_path(bank, clip): return 'disc0:' + iso_path(bank, clip)
def clips(index='build/voice_en/index.csv'):
    """{bank: [clip file path by clip number]}"""
    rows = list(csv.DictReader(open(index))); out = {}
    for b in sorted({int(r['bank']) for r in rows}):
        rs = sorted([r for r in rows if int(r['bank']) == b], key=lambda r: int(r['first_sector']))
        out[b] = ['build/voice_en/b%02d_c%02d_%s.xa' % (b, int(r['channel']), r['clip_in_channel']) for r in rs]
    return out
