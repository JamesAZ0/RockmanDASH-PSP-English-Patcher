"""Research tool (not run by the build; read-only; historical): how many argument bytes the choice-menu op MULTI takes,
derived from the US executable ROCK_NEO.EXE, compared with what the converter assumed at the time (2026-09-29).

The symptom that led here: in the intro, after the text box about the Reaverbot overhead, the Reaverbot never
dropped. That block ends with a Yes / No MULTI followed by an op that starts the event; the converter sized MULTI by
counting 0xED cursor-slot characters, took the event op for a MULTI argument and so lost it.

Findings from the US text engine (docs/RESEARCH.md §3):
  - MULTI (0x97, and the variants 0xE8 / 0xEA) is skipped in the scan pass (0x80055304) as 2 + count bytes, i.e. the
    op, a type byte and one byte per choice; count is the byte at state + 0x72.
  - count + 1: SEL 0x96 (0x80054BE0), AD, B7, D7, DD.   count = first argument: CE, E9.
    count = 0: CLEAR 0x87, MULTI itself, 9D, B5, B8 / BE, BF / D5, C2, C3, CA, E6 (and engine init).
    On the PSP the PSP-only op 0xA3 (the save menu's choice) also adds one, and 0xAB is a PSP-only MULTI.
  - 0xED is only a 12-pixel blank (draw pass, 0x8005A858); it does NOT count choices. tools/msgtool.py then counted
    0xED characters, which is wrong whenever a block has more of them than choices (e.g. two before "No").
The rule above is what tools/msgtool.py implements today (CHOICE_ADD / CHOICE_SET / CHOICE_RESET / PSP_CHOICE_ADD), so
on current sources this script should report no differing blocks.

It parses every PS1 and PSP block with both msgtool.parse and the rule coded here (parse3) and writes
logs/multi_rule_report.md: each block that parses differently, its MULTI arguments under both rules, and the ops the
old rule swallowed. One report column says whether the block was already English in the test build that was current
then; the path of that build's manifest is hard-coded below and must exist for the report part to run.

Reads extracted/ps1, extracted/psp (tools/extract.py). Usage: python3 research/multi_choice_count.py [build/test/<tag>/manifest.json]"""
import os,sys,glob,collections,struct,json; sys.path.insert(0,'tools'); import msgtool as M
# INC: ops that add a choice; SET: count = first argument byte; MULTI: the menu ops; RESET: count back to 0
INC={0x96,0xAD,0xB7,0xD7,0xDD}; SET={0xCE,0xE9}; MULTI={0x97,0xE8,0xEA,0xAB}; RESET={0x87,0x9D,0xB5,0xB8,0xBE,0xBF,0xD5,0xC2,0xC3,0xCA,0xE6}
# parse3: tokenise a block with the executable-derived rule. wide = PSP (16-bit codes, op = code - 0x2EE); pad = an
# odd argument length is followed by one pad byte. Returns (tokens, parsed exactly to the end)
def parse3(block, wide, pad):
    t=[]; i=0; cnt=0; step=2 if wide else 1
    while i+step<=len(block):
        v=struct.unpack_from('<H',block,i)[0] if wide else block[i]; i+=step
        op=v-M.OP_SHIFT if wide else v
        is_op=(v>=M.FIRST_OP+M.OP_SHIFT) if wide else (v>=M.FIRST_OP and v not in (0x86,0xED))
        if wide and v==0x86+M.OP_SHIFT: is_op=False
        if not is_op: t.append(('c',0x86 if (wide and v==0x86+M.OP_SHIFT) else v)); continue
        n=M.ARGS.get(op,0)
        if wide and op in M.PSP_ARGS: n=M.PSP_ARGS[op]
        # D5 = a branch list that runs to a 0xFF byte; MULTI = type byte + one byte per counted choice
        if op==0xD5:
            j=block.find(b'\xff',i); n=(j-i+1) if j>=0 else 2
        elif op in MULTI: n=1+cnt; cnt=0
        a=block[i:i+n]; i+=n
        if wide and pad and n%2: i+=1
        if op in INC or (wide and op==0xA3): cnt+=1
        if op in SET and a: cnt=a[0]
        if op in RESET: cnt=0
        t.append(('op',op,a))
    return t, i==len(block)
res=collections.Counter(); diff=[]
for side,wide in (('ps1',False),('psp',True)):
    for f in sorted(glob.glob(f'extracted/{side}/**/*',recursive=True)):
        if not f.lower().endswith('.msg'): continue
        B,_=M.blocks(open(f,'rb').read())
        for i,b in enumerate(B):
            t1,ok1=M.parse(b,wide,wide); t3,ok3=parse3(b,wide,wide)
            res[(side,ok1,ok3)]+=1
            for x in t3:
                # sanity counters: a MULTI whose last argument byte looks like an op (A9, 9A, 84), or one with no
                # choices at all
                if x[0]=='op' and x[1] in MULTI and x[2] and len(x[2])>1 and x[2][-1] in (0xA9,0x9A,0x84): res[(side,'MULTI swallows op byte')]+=1
                if x[0]=='op' and x[1] in MULTI and len(x[2])==1: res[(side,'MULTI with 0 choices')]+=1
            if t1!=t3: diff.append((side,f.split(side+'/')[1],i))
print(res); print(collections.Counter(d[0] for d in diff))
# which files a build already replaced with English text, from that build's manifest
# argument 1: the manifest of a build; default: the newest one under build/test/
_mans=sorted(glob.glob('build/test/*/manifest.json'),key=os.path.getmtime)
_mp=sys.argv[1] if len(sys.argv)>1 else (_mans[-1] if _mans else None)
if not _mp or not os.path.exists(_mp): raise SystemExit('no build manifest: build once, or give build/test/<tag>/manifest.json')
man=json.load(open(_mp)); inb={x['msg'].lower() for x in man['replaced']}
L=['# MULTI choice count: current parser vs EXE-derived rule','',f'Blocks parsing differently: {dict(collections.Counter(d[0] for d in diff))}','',
   '| File | Block | In the build | Current MULTI args | Correct MULTI args | Ops the current parser swallows |','|---|---|---|---|---|---|']
for side,f,i in diff:
    wide=side=='psp'; b=M.blocks(open(f'extracted/{side}/'+f,'rb').read())[0][i]
    t1,_=M.parse(b,wide,wide); t3,_=parse3(b,wide,wide)
    o1=[(M.NAMES.get(x[1],'%02X'%x[1]),x[2].hex()) for x in t1 if x[0]=='op']; o3=[(M.NAMES.get(x[1],'%02X'%x[1]),x[2].hex()) for x in t3 if x[0]=='op']
    m1=[a for n,a in o1 if n in ('MULTI','E8','EA','AB')]; m3=[a for n,a in o3 if n in ('MULTI','E8','EA','AB')]
    lost=[f'{n} {a}'.strip() for n,a in o3 if (n,a) not in o1 and n not in ('MULTI','E8','EA','AB')]
    L.append(f'| {side}/{f} | {i:02X} | {"yes" if f.lower() in inb else "no (Japanese kept)"} | {",".join(m1)} | {",".join(m3)} | {", ".join(lost)} |')
open('logs/multi_rule_report.md','w').write(chr(10).join(L)+chr(10)); print('wrote logs/multi_rule_report.md')
# psp jp: list changed
for d in diff:
    if d[0]=='psp': print(d)
