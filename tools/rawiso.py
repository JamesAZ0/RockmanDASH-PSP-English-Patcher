"""Read the PS1 disc image (the raw .bin of Track 1) with pycdlib, which expects a plain 2048-byte-sector ISO.

A PS1 data track is dumped as raw CD sectors: 2352 bytes each = 12 sync + 4 header + 8 sub-header + 2048 bytes of
user data + 280 bytes of error detection / correction (CD-ROM XA Mode 2, Form 1). The ISO 9660 file system lives in
the 2048-byte user parts. RawMode2 is a read-only file object that hides the framing: reading logical byte n returns
byte n % 2048 of sector n // 2048, taken from raw offset sector * 2352 + 24. open_ps1(path) wraps it and returns an
open pycdlib object, so the tools read PS1 files by path (e.g. '/CDDATA/DAT/ST00_01.BIN;1') exactly as they read the
PSP ISO.
Only Form 1 sectors (ordinary files: the DAT/*.BIN containers, ROCK_NEO.EXE) come out right this way. The XA audio
files use Form 2 sectors with 2324 data bytes; the voice tools (tools/voice/) read those from the raw image themselves.
Used by extract.py, build_title.py, build_textures.py and build_font.py. The image itself is never written."""
import io, pycdlib
class RawMode2(io.RawIOBase):
    """Presents a MODE2/2352 .bin as a 2048-byte/sector ISO (Form1 user data at offset 24).
    s.n = number of raw sectors, s.pos = position in the logical (2048-byte-sector) stream."""
    def __init__(s, path): s.f=open(path,'rb'); s.f.seek(0,2); s.n=s.f.tell()//2352; s.pos=0
    def readable(s): return True
    def seekable(s): return True
    # whence 0 / 1 / 2 = from the start / current position / logical end, like any file
    def seek(s,off,wh=0):
        s.pos = off if wh==0 else (s.pos+off if wh==1 else s.n*2048+off); return s.pos
    def tell(s): return s.pos
    def readinto(s,b):
        out=bytearray(); want=len(b)
        while len(out)<want and s.pos<s.n*2048:
            # logical position -> (sector, offset in its user data); read at most to the end of that sector
            sec,o=divmod(s.pos,2048); s.f.seek(sec*2352+24+o); d=s.f.read(min(2048-o,want-len(out)))
            out+=d; s.pos+=len(d)
        b[:len(out)]=out; return len(out)
def open_ps1(path):
    iso=pycdlib.PyCdlib(); iso.open_fp(io.BufferedReader(RawMode2(path))); return iso
