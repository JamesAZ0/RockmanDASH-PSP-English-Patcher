"""Is this file the right PS1 image? Used by gui.py when a file is picked and by tools/extract.py at the start of a build.

The build reads the US Mega Man Legends disc from the .bin file of Track 1, the data track, of a .bin/.cue image with
one .bin per track (the Redump layout). Track 2 is CD audio and holds nothing the build uses; the .cue is only a list.
check(path) -> (level, message):
  'ok'    Track 1 of Mega Man Legends (USA), SHA-1 as recorded by Redump
  'warn'  Track 1 of Mega Man Legends (USA), but not that dump: patching may still work; every step checks what it reads
  'bad'   not usable, with the reason (a .cue, an audio track, another game, ...)
How it is recognised: a data track is raw 2352-byte sectors, each starting with the sync pattern 00 FF x10 00; sector
16 holds the ISO 9660 volume descriptor ("CD001") at byte 24, with the volume name MEGAMAN_LEGENDS; the boot file name
SLUS_006.03 (the US serial) appears in the first sectors."""
import os, hashlib

SHA1 = '904489e2e8d06e1c44e60d8925329f9472b2d037'     # Mega Man Legends (USA) (Track 1).bin, Redump
SECTOR, SYNC = 2352, bytes([0] + [0xFF] * 10 + [0])
TRACK1 = 'Select Track 1 (.bin).'


def check(path):
    """-> (level, message) as described at the top; the message is what the patcher shows under the file picker"""
    if not os.path.isfile(path):
        return 'bad', 'Not valid: file not found.'
    if path.lower().endswith('.cue'):
        return 'bad', 'Not valid: this is the .cue file. ' + TRACK1
    size = os.path.getsize(path)
    with open(path, 'rb') as f:
        head = f.read(4 * 1024 * 1024)
    if size % SECTOR or head[:12] != SYNC:
        return 'bad', 'Not valid: not a PS1 data track. ' + TRACK1
    pvd = 16 * SECTOR + 24
    if head[pvd:pvd + 6] != b'\x01CD001':
        return 'bad', 'Not valid: not a PS1 data track. ' + TRACK1
    if head[pvd + 40:pvd + 72].strip() != b'MEGAMAN_LEGENDS' or b'SLUS_006.03' not in head:
        return 'bad', 'Not valid: not Mega Man Legends (USA).'
    h = hashlib.sha1()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 22), b''):
            h.update(chunk)
    if h.hexdigest() == SHA1:
        return 'ok', 'Verified: Mega Man Legends (USA), Track 1.'
    return 'warn', 'Unverified: Mega Man Legends (USA), Track 1. Checksum differs.'


if __name__ == '__main__':
    import sys
    print(*check(sys.argv[1]), sep=': ')
