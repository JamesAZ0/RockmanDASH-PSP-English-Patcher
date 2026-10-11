"""Print one block of a PSP dialogue file in readable form (reading aid; not a build step of its own).

dump(block) takes the raw bytes of a PSP (16-bit) block, without its 00 00 terminator, and returns one string:
  characters   decoded with tools/jptable.py's full table TK (digits, Latin, kana, symbols and the kanji read so far);
               a code the table does not know is printed as {XXX} (hex), a newline as the two characters backslash-n
  control ops  <NAME args> with the name from msgtool.NAMES (WIN, AUDIO, SEL, ...) or <OPxx args> for an unnamed op
               (xx = the PS1 opcode number, i.e. the PSP unit minus 0x2EE); args = the argument bytes in hex
The PSP's character codes are the game's own glyph numbers, not Shift-JIS, so the text cannot be read with a normal
text tool; see tools/jptable.py for how the table was worked out and docs/RESEARCH.md §3 / §4.
tools/build_text.py imports dump() to show the start of any block it could not fill (UNHANDLED lines).

Command line: python3 tools/jpdump.py <extracted PSP .msg file> <block index in hex>
  e.g. python3 tools/jpdump.py extracted/psp/ST00_01/mess/st00_01.msg 0A
(the file is an entry as tools/extract.py writes it: 0x800 header + data)."""
import sys; sys.path.insert(0,'tools'); import msgtool as M; from jptable import TK as T
def dump(block):
    # parse as PSP data (16-bit units, pad byte after odd-length arguments)
    t,_=M.parse(block,True,True); s=''
    for x in t:
        if x[0]=='c':
            c=x[1]; s+= '\\n' if c==0x86 else T.get(c,'{%X}'%c)
        else:
            s+='<%s %s>'%(M.NAMES.get(x[1],'OP%02X'%x[1]),x[2].hex())
    return s
if __name__=='__main__':
    f,i=sys.argv[1],int(sys.argv[2],16); B,_=M.blocks(open(f,'rb').read()); print(dump(B[i]))
