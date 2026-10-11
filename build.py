#!/usr/bin/env python3
"""Rockman DASH PSP English: full rebuild, on Windows, macOS or Linux. See docs/BUILD.md (section numbers below refer to it).

Usage: python build.py <tag> [options] [iso]
  iso   the Japanese PSP image to build from (PSN release or retail UMD dump; identified from its contents).
        Default: the only .iso in originalDiskImages/psp/, or the PSN release if there are several.
  --localization=text|audio|legends   how much of the US PS1 game goes in (never changes the dog scene):
        text     English text and text-bearing textures (weapon labels, prologue, maps, mission banner, title menu
                 options). Japanese voices, the PSP title screen, PSP menu name and save name "Rockman DASH"
        audio    text + all English audio from the PS1 disc (needs atracdenc, docs/BUILD.md section 1; cached)
        legends  (default) audio + the PS1 title screen (4.6, 4.15) + PSP menu and save games as "Mega Man Legends" with
                 the PS1 logo picture (4.6, 4.16) + the US name/artwork textures (script/texture_swaps.json "legends")
  --hud=off|center|edge|hud-only   HUD, windows and text proportions in the Wide screen mode, game world untouched
        (4.12). hud-only (default): the HUD is corrected, pieces at the left/right keep to the screen edge; text,
        windows, subtitles and menus are left alone. edge: the same, with windows and text corrected too.
        center: everything corrected about the screen centre. edge and center have had little play testing.
  --paprika=good-dog|fair-game   the lamp-post scene's dog (4.13). good-dog: no kicking, as the US PS1;
        fair-game (default): unchanged
  --subtitles=on|off   the PSP's subtitles in voiced scenes (default on)
  --subtitle-language=en|jp   en (default): English subtitles; jp: the original Japanese ones
  --subtitle-background=on|off   on (default): a dark band behind English subtitles, screen-wide, without a border
Output: build/test/<tag>/RockmanDASH_EN_<tag>.iso and its MD5.
External program: atracdenc (ATRACDENC=, then bin/<platform>/, then the PATH; tools/exttools.py).
atracdenc is compiled from src/atracdenc on first use if it is not found (needs cmake and a C++ compiler)."""
import sys, os, shutil, struct, hashlib, subprocess

# How the build is put together (each step is a script in tools/, run in this order; every step only reads the
# original disc images, and each script's docstring explains the game-side facts it relies on; the research behind
# them is summarised in docs/RESEARCH.md):
#   plain_eboot      the game's program as a plain ELF, from the user's own PSP image
#   extract          dialogue files, font and the US executable out of the two images
#   build_text       English PS1 script -> PSP dialogue files
#   build_title, build_textures, build_ps1_title, build_savepic, build_font     textures, pictures and font glyphs
#   patch_eboot .. patch_ps1_title, voice/patch_eboot_voice     the program: text renderer, moved text buffers, system
#                    messages, save text, and the optional changes; each works on build/eboot/ULJM05030_EBOOT_*.BIN
#   build_sfo, build_subtitles, voice/build_audio, voice/build_vab     PSP menu name, subtitles, English audio
#   pack_inplace     everything into a copy of the PSP image, without moving any original file
#   checks/verify_*, compare_loaded, audit_eboot     checks; any failure stops the build
# The public options below are translated in main() into the tools' internal arguments (--audio=, --menu=, --legends,
# and the positional settings of the patch_* tools).

ROOT = os.path.dirname(os.path.abspath(__file__))
CHOICES = {'localization': ('text', 'audio', 'legends'), 'hud': ('off', 'center', 'edge', 'hud-only'),
           'paprika': ('good-dog', 'fair-game'), 'subtitles': ('on', 'off'), 'subtitle-language': ('en', 'jp'),
           'subtitle-background': ('on', 'off')}
DEFAULT = {'localization': 'legends', 'hud': 'hud-only', 'paprika': 'fair-game', 'subtitles': 'on', 'subtitle-language': 'en',
           'subtitle-background': 'on'}


# -> (tag, options, iso path or ""); prints the usage text (the module docstring) when no tag is given
def parse(argv):
    if not argv or argv[0].startswith('-'):
        sys.exit(__doc__)
    tag, opt, iso = argv[0], dict(DEFAULT), ''
    for a in argv[1:]:
        if a.startswith('--') and '=' in a and a[2:].split('=', 1)[0] in CHOICES:
            k, v = a[2:].split('=', 1)
            if v not in CHOICES[k]:
                sys.exit(f'--{k}: choose one of {", ".join(CHOICES[k])}')
            opt[k] = v
        elif a.startswith('-'):
            sys.exit(f'unknown option: {a} (python build.py for the list)')
        else:
            iso = a
    return tag, opt, iso


# A short heading for the log before each group of tools (tool file name -> heading); tools with the same heading
# in a row share one line
P, A_ = 'Game program', 'Audio'
STEP_TEXT = {
    'plain_eboot.py': 'Reading the disc images', 'extract.py': 'Reading the disc images',
    'extract_voice_en.py': 'Reading the disc images', 'extract_voice_en.py --streams': 'Reading the disc images',
    'jp_clips.py': 'Reading the disc images',
    'build_text.py': 'Text', 'build_title.py': 'Textures', 'build_textures.py': 'Textures',
    'build_ps1_title.py': 'Title screen', 'build_savepic.py': 'Save picture', 'build_xmb.py': 'PSP menu picture',
    'build_font.py': 'Font',
    'patch_eboot.py': P, 'build_sysmsg.py': P, 'build_savetext.py': P, 'patch_psp_menu.py': P, 'patch_wide_hud.py': P,
    'patch_ps1_dog.py': P, 'patch_subtitles.py': P, 'patch_subtitle_box.py': P, 'patch_ps1_title.py': P,
    'build_sfo.py': 'PSP menu name', 'build_subtitles.py': 'Subtitles',
    'patch_eboot_voice.py': A_, 'build_audio.py': A_, 'build_vab.py': A_,
    'pack_inplace.py': 'Writing the disc image',
}
CHECKS = 'Checking'
HEADINGS = set(STEP_TEXT.values()) | {CHECKS}                # gui.py shows these lines as the current step


class ToolFailed(Exception):
    """A build step stopped with an error (the step's own message has been printed or logged)."""


def main():
    """command line: python build.py <tag> [options] [path to the PSP .iso]"""
    tag, opt, iso = parse(sys.argv[1:])
    run(tag, opt, iso)


def run(tag, opt, iso='', root=ROOT, log=None, inprocess=False):
    """Build build/test/<tag>/RockmanDASH_EN_<tag>.iso under root (a folder holding tools/, script/ and
    originalDiskImages/) and return its path. opt: one value per key of CHOICES. iso: the PSP image, '' = automatic.
    log: None = the tools print to this process's output (command line); a function = it receives every output line
    (gui.py). inprocess: run the tools inside this interpreter instead of starting 'python tool.py' for each; needed in
    the packaged executable (gui.py), where there is no separate Python to start."""
    os.chdir(root)
    sys.path.insert(0, os.path.join(root, 'tools'))
    import exttools
    os.environ['PSP_ISO'] = iso
    env = dict(os.environ, PYTHONUTF8='1')                   # UTF-8 text files whatever the system's code page (Windows)
    import builtins
    real_out = sys.stdout                                    # (in-process tools redirect sys.stdout; messages must not loop)
    say = log or (lambda line: builtins.print(line, file=real_out, flush=True))

    # a short heading in the log when the kind of work changes ("Text", "Audio", "Checking", ...)
    last = {'text': None}
    def heading(script, args):
        name = os.path.basename(script)
        text = CHECKS if '/checks/' in script.replace(os.sep, '/') else STEP_TEXT.get(name + (' --streams' if '--streams' in args else ''), name)
        if text != last['text']:
            last['text'] = text; say(text)

    # run one tool; empty arguments are dropped. out: None = its output goes to the log, a path = written there,
    # '' = discarded
    def py(script, *args, out=None):
        args = [a for a in args if a]
        heading(script, args)
        sink = None if out is None else (open(out, 'w', encoding='utf-8') if out else open(os.devnull, 'w'))
        try:
            if inprocess:
                _run_inprocess(root, script, args, sink, say)
            else:
                cmd = [sys.executable, script, *args]
                if sink is None and log is None:
                    subprocess.run(cmd, check=True, env=env)
                elif sink is not None:
                    subprocess.run(cmd, check=True, env=env, stdout=sink)
                else:                                        # pass every line to the log function
                    p = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                         encoding='utf-8', errors='replace')
                    for line in p.stdout:
                        log(line.rstrip('\n'))
                    if p.wait():
                        raise subprocess.CalledProcessError(p.returncode, cmd)
        finally:
            if sink:
                sink.close()
    print = say                                              # noqa: A001 (the messages below go to the log too)

    # public options -> internal settings: localization -> (voice language, title screen, PSP menu / save naming);
    # hud and paprika -> the words patch_wide_hud.py and patch_ps1_dog.py take
    loc = opt['localization']
    audio, title, menu = {'text': ('jp', 'psp', 'original'), 'audio': ('en', 'psp', 'original'),
                          'legends': ('en', 'ps1', 'localized')}[loc]
    hud = {'off': 'off', 'center': 'center', 'edge': 'edges', 'hud-only': 'hudonly'}[opt['hud']]
    dog = {'good-dog': 'ps1', 'fair-game': 'jp'}[opt['paprika']]
    subs, sublang = opt['subtitles'], opt['subtitle-language']
    print('options: ' + ' '.join(f'{k}={v}' for k, v in opt.items()))

    # what must be there before anything is built
    need = ['script/ps1_charmap.tbl']
    missing = [p for p in need if not os.path.exists(p)]
    if missing:
        sys.exit('missing: ' + ', '.join(missing) + ' (docs/BUILD.md section 1)')
    if audio == 'en':
        if not exttools.find('atracdenc'):
            exttools.build_atracdenc()                       # compiles src/atracdenc into bin/<platform>/ (docs/BUILD.md section 1)

    py('tools/plain_eboot.py')                               # 4.1  the plain program, from the user's PSP image
    # Sony's program as a plain ELF, the reference for the checks: that file up to the end of the ELF (the furthest
    # of the section-header table and every section's file bytes; a PPSSPP dump carries a few unused bytes after it)
    d = open('decrypted_eboot/ULJM05030_EBOOT.BIN', 'rb').read()
    shoff, = struct.unpack_from('<I', d, 0x20); shnum, = struct.unpack_from('<H', d, 0x30)
    end = shoff + 40 * shnum
    for k in range(shnum):
        s = struct.unpack_from('<10I', d, shoff + 40 * k)
        if s[1] != 8:                                        # not .bss
            end = max(end, s[4] + s[5])
    for folder in ('build/diag', 'logs'):                    # logs/: the reports the tools write
        os.makedirs(folder, exist_ok=True)
    ref = 'build/diag/BOOT_sony_plain.BIN'
    if not os.path.exists(ref) or open(ref, 'rb').read() != d[:end]:
        open(ref, 'wb').write(d[:end])

    # texture replacements are rebuilt from scratch each time (a previous build may have had other options)
    for dirpath, _, files in os.walk('build/tex_psp'):
        for f in files:
            try:
                os.remove(os.path.join(dirpath, f))
            except OSError:                                  # a folder that refuses deletes: build_textures.py renames instead
                pass

    eboot = 'build/eboot/ULJM05030_EBOOT_en.BIN'
    out = f'build/test/{tag}'
    py('tools/extract.py')                                   # 4.2  read both original images -> extracted/
    if not os.path.exists('build/voice_en/index.csv'):
        py('tools/voice/extract_voice_en.py')                # 4.18 English clip list (clip lengths for the voice map)
    if audio == 'en' and not os.path.exists('build/voice_en/index_streams.csv'):
        py('tools/voice/extract_voice_en.py', '--streams')   # 4.18 English cutscene streams
    if not os.path.exists('build/voice_en/jp_clips.json'):
        py('tools/voice/jp_clips.py')                        # 4.18 Japanese clip list
    py('tools/build_text.py', f'--audio={audio}')            # 4.3  English PS1 script -> PSP dialogue in build/msg_psp/
    py('tools/build_title.py')                               # 4.4  title-menu words (PS1 texture) -> build/tex_psp/
    py('tools/build_textures.py', '--legends' if loc == 'legends' else '')   # 4.5  PS1 texture swaps -> build/tex_psp/
    # internal arguments for pack_inplace.py, filled in when the PS1 title screen / localized menu are built
    title_flag, pict_flags = '', []
    if title == 'ps1':
        py('tools/build_ps1_title.py'); title_flag = '--ps1-title=build/ps1_title'   # 4.6  PS1 title data
    if menu == 'localized':
        py('tools/build_savepic.py')                         # 4.6  save image + menu icon -> build/pict/savepic.png
        pict_flags = ['--pict=build/pict/savepic.png', '--icon0=build/pict/savepic.png', '--drop-icon1']
    py('tools/build_xmb.py')                                 # 4.16 PSP menu overlay without the Japanese tagline -> build/pict/PIC0.PNG
    py('tools/build_font.py')                                # 4.7  extra glyphs into the PSP font
    py('tools/patch_eboot.py')                               # 4.8  EBOOT: variable-width text, moved text buffers
    py('tools/build_sysmsg.py')                              # 4.9  EBOOT: English menus / item names / options
    py('tools/build_savetext.py', f'--menu={menu}')          # 4.10 EBOOT: English save-screen text
    py('tools/patch_psp_menu.py', menu)                      # 4.11 EBOOT: keep the new save image when a save is loaded
    py('tools/patch_wide_hud.py', hud)                       # 4.12 EBOOT: wide-mode HUD/text proportions
    py('tools/patch_ps1_dog.py', dog)                        # 4.13 EBOOT: dog scene
    py('tools/patch_subtitles.py', subs)                     # 4.14 EBOOT: subtitles off
    box = opt['subtitle-background'] == 'on' and sublang == 'en' and subs == 'on'   # the band behind English subtitles
    py('tools/patch_subtitle_box.py', 'on' if box else 'off')   # 4.14 EBOOT: window type 4 is drawn without its border
    py('tools/patch_ps1_title.py', title)                    # 4.15 EBOOT: PS1 title background, palette, title voice
    py('tools/build_sfo.py', f'--menu={menu}')               # 4.16 PSP menu name (PARAM.SFO)
    if sublang == 'en':
        py('tools/build_subtitles.py', '--box' if opt['subtitle-background'] == 'on' else '')                       # 4.17 English subtitles for the voiced scenes
    # English audio: voice path tables in the program, the .at3 files, the sound-bank samples; pack_inplace arguments
    audio_flags = []
    if audio == 'en':
        py('tools/voice/patch_eboot_voice.py')               # 4.18 English voice banks in the EBOOT
        py('tools/voice/build_audio.py', 'en')               # 4.18 English .at3 audio
        py('tools/voice/build_vab.py')                       # 4.18 English voice samples in the SPU sound banks
        audio_flags = ['--audio', '--drop-jp-voice']
    py('tools/pack_inplace.py', tag, '--eboot', '--relocate', f'--eboot-src={eboot}', *audio_flags,
       '--sfo=build/sfo/PARAM.SFO', title_flag, *pict_flags, '--pic0=build/pict/PIC0.PNG', '--drop-snd0')        # 4.19 the ISO
    for r in ('ps1_title', 'ps1_dog', 'psp_menu', 'wide_hud', 'subtitles', 'subtitle_box'):      # option reports, for the checks
        shutil.copy(f'build/eboot/{r}.json', out)

    A = 'tools/checks/'                                    # section 5: checks
    py(A + 'verify_voice_eboot.py', f'--audio={audio}')      # EBOOT voice tables resolve every clip
    py(A + 'compare_loaded.py', f'{out}/EBOOT_unflat.BIN', f'{out}/EBOOT_plain.BIN')   # flattened EBOOT loads identically
    py(A + 'audit_eboot.py', f'{out}/EBOOT_plain.BIN', out=f'{out}/audit_eboot.txt')   # every EBOOT change accounted for
    if sublang == 'en':
        py(A + 'verify_subtitles.py', tag)                   # English subtitles read back from the EBOOT
    py(A + 'verify_savetext.py', tag)                        # save-screen text; save identity unchanged
    py(A + 'verify_ps1_title.py', tag)                       # title / menu / dog options as built (or untouched)
    py(A + 'verify_voice.py', f'--audio={audio}')            # every voice op names a clip that exists
    py(A + 'verify_msg_args.py')                             # control-code arguments match the Japanese
    py(A + 'verify_headers.py', tag)                         # no container header/data changed unexpectedly
    py(A + 'verify_xmb.py', tag)                             # PSP menu overlay edited, background unchanged, music removed
    py(A + 'verify_sfo.py', tag)                             # PSP menu name set; other PARAM.SFO values unchanged
    if audio == 'en':
        py(A + 'jp_audio_audit.py', out='')                  # the dropped Japanese voice clips are unreachable
        py(A + 'verify_dropped.py', tag)
    py(A + 'verify_vab.py', tag, f'--audio={audio}')         # English voice samples in the sound banks
    py(A + 'verify_layout.py', tag)                          # no two files overlap
    py(A + 'verify_slack.py', tag)                           # disc space reused by grown files was empty
    py(A + 'verify_sysmsg.py', tag, out=f'{out}/verify_sysmsg.txt')   # system-message table
    # (the wide-HUD emulation check is a separate command: python research/verify_wide_hud.py <tag>; docs/BUILD.md section 5)

    iso_out = f'{out}/RockmanDASH_EN_{tag}.iso'
    h = hashlib.md5()
    with open(iso_out, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    print('All checks passed.')
    print(f'Done: {iso_out}\n{h.hexdigest()}  {iso_out}')
    return os.path.join(root, iso_out)


class _LineWriter:
    """File-like object that hands complete lines to a function (the tools' print output in the packaged executable)."""
    def __init__(self, fn): self.fn, self.buf = fn, ''
    def write(self, s):
        self.buf += s
        while '\n' in self.buf:
            line, self.buf = self.buf.split('\n', 1); self.fn(line)
        return len(s)
    def flush(self):
        pass


def _run_inprocess(root, script, args, sink, say):
    """Run tools/<script> as if started with 'python script args' but inside this interpreter. The tools are plain
    scripts that read sys.argv and print; their output goes to sink (a file) or to say (line by line). Modules the
    tools import from tools/ are forgotten afterwards, so the next tool starts as fresh as a new process would."""
    import runpy, contextlib
    tools_dir = os.path.join(root, 'tools')
    argv, sys.argv = sys.argv, [script, *args]
    out = sink or _LineWriter(say)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(_LineWriter(say)):
            runpy.run_path(os.path.join(root, script), run_name='__main__')
    except SystemExit as e:
        if e.code not in (None, 0):
            if isinstance(e.code, str):
                say(e.code)
            raise ToolFailed(f'{script} stopped') from None
    except Exception as e:
        import traceback
        for line in traceback.format_exc().splitlines():
            say(line)
        raise ToolFailed(f'{script} failed: {e}') from None
    finally:
        sys.argv = argv
        for name, mod in list(sys.modules.items()):
            f = getattr(mod, '__file__', None) or ''
            if f.startswith(tools_dir) and name != 'exttools':
                del sys.modules[name]
        _close_disc_images()


def _close_disc_images():
    """Close every disc image a tool left open. A tool run as its own process gives its files back when it ends; run
    inside this interpreter, a pycdlib image stays open (pycdlib keeps the object in a cache until close()), and
    Windows then refuses to move, overwrite or delete that file - the built ISO and the working folder included."""
    import gc
    cd = getattr(sys.modules.get('pycdlib'), 'PyCdlib', None)
    if cd:
        for o in gc.get_objects():
            if type(o) is cd:
                try:
                    o.close()
                except Exception:                            # not open, or already closed
                    pass
    gc.collect()                                             # images opened from a file object (the PS1 image)


if __name__ == '__main__':
    try:
        main()
    except subprocess.CalledProcessError as e:
        sys.exit(f'build stopped: {" ".join(map(str, e.cmd))} failed (exit {e.returncode})')
    except ToolFailed as e:
        sys.exit(f'build stopped: {e}')
