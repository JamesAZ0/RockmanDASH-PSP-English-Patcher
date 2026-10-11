#!/usr/bin/env python3
"""Graphical patcher: pick the two disc images, choose the options, press Patch.

It is a front end to build.py: the same steps and checks run, in a working folder. Nothing is written to the disc
images. When patching has finished, the program asks where to save the new .iso. From source: python gui.py (needs Tk, which ships with most Python installers). The release
downloads are this program packaged with Python, the tools and the external programs (packaging/patcher.spec).

Without a window, for testing:  python gui.py --headless <ps1 Track 1 .bin> <psp .iso> <output .iso> [build.py options]

Working folder: RockmanDASH_work next to the PSP image (in the system's temporary folder if that place cannot be
written to; next to the output file with --headless). It receives a copy of tools/ and script/,
links to the disc images under the names the tools expect, and everything the build produces (extracted game files,
the encoded audio, the reports). It is deleted afterwards unless "Keep working files" is ticked; keeping it makes a
second build with other options much faster, because the encoded audio is reused."""
import os, sys, shutil, threading, queue, traceback

HERE = os.path.dirname(os.path.abspath(__file__))
RES = getattr(sys, '_MEIPASS', HERE)                 # where tools/ and script/ are: the repository, or the unpacked bundle
# packaged executable: no separate Python to start, so the tools run inside this process (PATCHER_INPROCESS=1 forces
# the same from source, for testing)
FROZEN = bool(getattr(sys, 'frozen', False)) or os.environ.get('PATCHER_INPROCESS') == '1'
sys.path.insert(0, RES); sys.path.insert(0, os.path.join(RES, 'tools'))
import ps1check                                      # noqa: E402  (tools/ps1check.py: is this Track 1 of the US disc?)
import pspcheck                                      # noqa: E402  (tools/pspcheck.py: is this Rockman DASH ULJM05030?)
import build                                         # noqa: E402  (build.py: CHOICES, DEFAULT, run)

PS1_NAME = 'Mega Man Legends (USA) (Track 1).bin'    # the name tools/inputs.py reads the PS1 image under
TITLE = 'Rockman DASH (PSP) English Patcher'

# option key -> (label, tooltip, [(value, shown text, tooltip), ...]); values and defaults are build.py's.
# The HUD fix is not offered here (project decision 2026-10-02): the patcher always uses build.py's default, hud-only,
# and the game itself has the switch (Triangle on the options screen while Screen = Wide is highlighted).
OPTIONS = [
    ('localization', 'Localization', 'Sets how much is changed to English.', [
        ('text', 'Text only', 'English text. Japanese audio.'),
        ('audio', 'Text and audio', 'English text and audio.'),
        ('legends', 'Legends', 'English text and audio. Mega Man Legends title screen, icon and save data.')]),
    ('paprika', 'Paprika', 'Sets whether the dog can be kicked.', [
        ('fair-game', 'Fair game', 'The dog can be kicked. Same as the Japanese release.'),
        ('good-dog', 'Good dog', 'The dog cannot be kicked. Same as the English release.')]),
    ('subtitles', 'Cutscene subtitles', 'Sets whether cutscenes show subtitles.', [
        ('on', 'On', 'Cutscenes show subtitles.'),
        ('off', 'Off', 'Cutscenes show no subtitles.')]),
    ('subtitle-language', 'Subtitle language', 'Sets the language of cutscene subtitles.', [
        ('en', 'English', 'Cutscene subtitles are English.'),
        ('jp', 'Japanese', 'Cutscene subtitles are Japanese.')]),
    ('subtitle-background', 'Subtitle background', 'Sets whether cutscene subtitles have a dark background.', [
        ('on', 'On', 'Cutscene subtitles have a dark background.'),
        ('off', 'Off', 'Cutscene subtitles have no background.')]),
]


# The Credits window: (heading, [(name, what it is used for, link)]). Licences and details: THIRD_PARTY.md.
CREDITS = [
    ('Software', [
        ('atracdenc', 'Encodes the English audio as ATRAC3plus. Includes libgha and KISS FFT.',
         'https://github.com/dcherednik/atracdenc'),
        ('libsndfile', 'Reads audio files for atracdenc (Linux and macOS).', 'https://github.com/libsndfile/libsndfile'),
        ('pyeboot', 'Decrypts the game program of the PSN release. Includes pspdecrypt and sign_np.',
         'https://github.com/Illidanz/pyeboot'),
        ('pycdlib', 'Reads and writes the disc images.', 'https://github.com/clalancette/pycdlib'),
        ('Pillow', 'Makes the PSP menu and save pictures.', 'https://python-pillow.org'),
        ('NumPy', 'Decodes and processes audio.', 'https://numpy.org'),
        ('Capstone', 'Disassembles code in one of the build checks.', 'https://www.capstone-engine.org'),
        ('Python and Tk', 'Run the patcher.', 'https://www.python.org'),
        ('PyInstaller', 'Packages the patcher.', 'https://pyinstaller.org'),
    ]),
    ('Used during development', [
        ('PPSSPP', 'Testing.', 'https://www.ppsspp.org'),
        ('Unicorn', 'Emulation for the HUD check.', 'https://www.unicorn-engine.org'),
        ('Whisper', 'Transcription for the subtitle timings.', 'https://github.com/openai/whisper'),
        ('python-zstandard', 'Reads save states in research tools.', 'https://github.com/indygreg/python-zstandard'),
    ]),
    ('References', [
        ('DashEditor by Ombra (SadNES cITy Translations)', 'Documentation of the game\'s file formats and character table.',
         'https://github.com/OmbraRD/DashEditor'),
        ('Mega Man Legends - Game Script (PS) by Estil, GameFAQs', 'Reference for checking the subtitle transcripts.',
         'https://gamefaqs.gamespot.com/ps/197896-mega-man-legends/faqs/18334'),
        ('Redump', 'Checksum of the PS1 disc image.', 'http://redump.org'),
    ]),
]
CREDITS_NOTE = 'Mega Man Legends and Rockman DASH belong to Capcom. This patcher contains no game data.'
CREDITS_FOOT = 'Made (with good intentions) using Claude Opus 5.5'


def prepare(work, ps1, log):
    """Fill the working folder: tools/, script/ (and src/ if present) copied from the program's resources; the external program atracdenc stays where it is (ATRACDENC= points at it), and
    the PS1 image under the name the tools expect."""
    os.makedirs(work, exist_ok=True)
    # The external programs are used where they are, not copied: in the packaged program they find their libraries
    # (libsndfile, ...) relative to their own place in the bundle, and macOS stops a copy that cannot find them.
    import exttools
    for prog in ('atracdenc',):
        for d in (os.path.join(RES, 'bin', exttools.platform_tag()), os.path.join(RES, 'bin')):
            for cand in (os.path.join(d, prog), os.path.join(d, prog + '.exe')):
                if os.path.isfile(cand):
                    os.environ.setdefault(prog.upper(), cand)
    for name in ('tools', 'script', 'src'):
        src = os.path.join(RES, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(work, name), dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns('__pycache__', '.DS_Store'))
    d = os.path.join(work, 'originalDiskImages', 'ps1'); os.makedirs(d, exist_ok=True)
    dst = os.path.join(d, PS1_NAME)
    if os.path.lexists(dst):
        os.remove(dst)
    for how, fn in (('link', os.link), ('symbolic link', os.symlink)):
        try:
            fn(os.path.abspath(ps1), dst); return
        except OSError:
            pass
    log('copying the PS1 image into the working folder (it could not be linked) ...')
    shutil.copyfile(ps1, dst)


def work_folder(psp):
    """Where the build works (about 2 GB): next to the PSP image if that folder can be written to, else the system's
    temporary folder."""
    import tempfile
    for d in (os.path.dirname(os.path.abspath(psp)), tempfile.gettempdir()):
        try:
            p = os.path.join(d, 'RockmanDASH_work'); os.makedirs(p, exist_ok=True)
            with open(os.path.join(p, '.write_test'), 'w'):
                pass
            os.remove(os.path.join(p, '.write_test')); return p
        except OSError:
            continue
    raise RuntimeError('no folder to work in: neither the PSP image\'s folder nor the temporary folder can be written to')


def build_iso(ps1, psp, work, opt, log):
    """Run the whole build in the working folder and return the path of the new .iso inside it. Raises on failure (the
    reason has been logged)."""
    for path, what in ((ps1, 'PS1 image'), (psp, 'PSP image')):
        if not os.path.isfile(path):
            raise RuntimeError(f'{what} not found: {path}')
    level, msg = ps1check.check(ps1)
    if level == 'bad':
        raise RuntimeError('PS1 image: ' + msg)
    level, msg = pspcheck.check(psp)
    if level == 'bad':
        raise RuntimeError('PSP image: ' + msg)
    cwd = os.getcwd()
    try:
        prepare(work, ps1, log)
        return build.run('patch', opt, os.path.abspath(psp), root=work, log=log, inprocess=FROZEN)
    finally:
        os.chdir(cwd)


def patch(ps1, psp, out_iso, opt, keep, log):
    """Build and leave the result at out_iso (used by --headless; the window asks for the place afterwards)."""
    work = os.path.join(os.path.dirname(os.path.abspath(out_iso)) or os.getcwd(), 'RockmanDASH_work')
    try:
        shutil.move(build_iso(ps1, psp, work, opt, log), out_iso)
        log(f'Written: {out_iso}')
    finally:
        if not keep:
            shutil.rmtree(work, ignore_errors=True)


def headless(argv):
    """--headless <ps1> <psp> <out.iso> [build.py options]: the same patching as the window, with the log printed"""
    if len(argv) < 3:
        sys.exit(__doc__)
    ps1, psp, out = argv[:3]
    _, opt, _ = build.parse(['x', *argv[3:]])
    try:
        patch(ps1, psp, out, opt, keep='--keep' in os.environ.get('PATCHER_FLAGS', ''),
              log=lambda line: print(line, file=sys.__stdout__, flush=True))
    except (build.ToolFailed, RuntimeError, SystemExit) as e:
        sys.exit(f'patching stopped: {e}')


def gui():
    """The window: file pickers, options, Patch button, progress bar with a status line, and the log."""
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    from tkinter.scrolledtext import ScrolledText

    class Tip:
        """A small tooltip window shown while the pointer is over a widget."""
        def __init__(self, widget, text):
            self.widget, self.text, self.win = widget, text, None
            widget.bind('<Enter>', self.show, add='+'); widget.bind('<Leave>', self.hide, add='+')
        def show(self, _=None):
            if self.win or not self.text:
                return
            self.win = w = tk.Toplevel(self.widget); w.wm_overrideredirect(True)
            w.wm_geometry(f'+{self.widget.winfo_rootx() + 16}+{self.widget.winfo_rooty() + self.widget.winfo_height() + 4}')
            tk.Label(w, text=self.text, justify='left', wraplength=380, background='#ffffe0', foreground='#000000',
                     relief='solid', borderwidth=1, padx=6, pady=4).pack()
        def hide(self, _=None):
            if self.win:
                self.win.destroy(); self.win = None

    root = tk.Tk(); root.title(TITLE); root.minsize(640, 0)
    frm = ttk.Frame(root, padding=12); frm.grid(sticky='nsew'); root.columnconfigure(0, weight=1); frm.columnconfigure(1, weight=1)
    row = 0
    ttk.Label(frm, text='Source Images:', font=('', 10, 'bold')).grid(
        row=row, column=0, columnspan=3, sticky='w', pady=(0, 6)); row += 1
    paths = {}
    status = {}
    COLOUR = {'ok': '#1a7f37', 'warn': '#9a6700', 'bad': '#cf222e', '': ''}
    def picker(key, label, tip, types, check=None):
        # one row: label, path field, Browse button; check (ps1check / pspcheck) fills a coloured status line below it
        nonlocal row
        var = tk.StringVar(); paths[key] = var
        lab = ttk.Label(frm, text=label); lab.grid(row=row, column=0, sticky='w', padx=(0, 8), pady=2); Tip(lab, tip)
        ent = ttk.Entry(frm, textvariable=var); ent.grid(row=row, column=1, sticky='ew', pady=2); Tip(ent, tip)
        def browse():
            p = filedialog.askopenfilename(filetypes=types)
            if p:
                var.set(p)
                if check:                                    # checked in the background (reads the whole file)
                    status[key].configure(text='Checking the file ...', foreground='')
                    threading.Thread(target=lambda: q.put(('status', (key, p, *check(p)))), daemon=True).start()
        ttk.Button(frm, text='Browse...', command=browse).grid(row=row, column=2, padx=(8, 0), pady=2); row += 1
        if check:
            status[key] = ttk.Label(frm, text='', wraplength=520, justify='left')
            status[key].grid(row=row, column=1, columnspan=2, sticky='w'); row += 1
    picker('ps1', 'Mega Man Legends (PS1, USA): Track 1 .bin', 'Track 1 (.bin) of the US PS1 disc image. Not the .cue file or Track 2.',
           [('PS1 image, Track 1 (.bin)', '*.bin'), ('All files', '*.*')], check=ps1check.check)
    picker('psp', 'Rockman DASH (PSP, Japan)', 'The Japanese PSP disc image (.iso). UMD or PSN release.',
           [('PSP image', '*.iso'), ('All files', '*.*')],
           check=pspcheck.check)

    ttk.Separator(frm).grid(row=row, column=0, columnspan=3, sticky='ew', pady=10); row += 1
    ttk.Label(frm, text='Options:', font=('', 10, 'bold')).grid(
        row=row, column=0, columnspan=3, sticky='w', pady=(0, 6)); row += 1
    chosen = {}
    widgets = {}                                             # option key -> its label and radio buttons
    for key, label, tip, values in OPTIONS:
        lab = ttk.Label(frm, text=label); lab.grid(row=row, column=0, sticky='w', padx=(0, 8), pady=2); Tip(lab, tip)
        var = tk.StringVar(value=build.DEFAULT[key]); chosen[key] = var
        box = ttk.Frame(frm); box.grid(row=row, column=1, columnspan=2, sticky='w', pady=2)
        widgets[key] = [lab]
        for value, text, vtip in values:
            rb = ttk.Radiobutton(box, text=text, value=value, variable=var); rb.pack(side='left', padx=(0, 12)); Tip(rb, vtip)
            widgets[key].append(rb)
        row += 1
    def subtitle_rows(*_):
        # the language and background choices only matter while cutscene subtitles are on; their values are kept
        state = 'normal' if chosen['subtitles'].get() == 'on' else 'disabled'
        for key in ('subtitle-language', 'subtitle-background'):
            for wdg in widgets[key]:
                wdg.configure(state=state)
    chosen['subtitles'].trace_add('write', subtitle_rows); subtitle_rows()
    keep = tk.BooleanVar(value=False)
    cb = ttk.Checkbutton(frm, text='Keep working files', variable=keep); cb.grid(row=row, column=0, columnspan=3, sticky='w', pady=(8, 0))
    Tip(cb, 'Keeps the working folder (over 1 GB). Patching again is faster.'); row += 1

    ttk.Separator(frm).grid(row=row, column=0, columnspan=3, sticky='ew', pady=10); row += 1
    logbox = ScrolledText(frm, height=12, state='disabled', wrap='word'); logbox.grid(row=row, column=0, columnspan=3, sticky='nsew')
    frm.rowconfigure(row, weight=1); root.rowconfigure(0, weight=1); row += 1
    bar = ttk.Progressbar(frm, mode='indeterminate'); bar.grid(row=row, column=0, columnspan=3, sticky='ew', pady=(8, 0)); row += 1
    # status strip under the bar: the current step while patching, green when finished, red when stopped
    status_bar = tk.Label(frm, text='', anchor='w', padx=8, pady=6); status_bar.grid(row=row, column=0, columnspan=3, sticky='ew', pady=(4, 0)); row += 1
    PLAIN = (status_bar.cget('background'), status_bar.cget('foreground'))
    def show_status(text, kind=''):
        # the line under the progress bar; kind 'done' turns it green, 'fail' red, anything else plain
        bg, fg = {'done': ('#1a7f37', '#ffffff'), 'fail': ('#cf222e', '#ffffff')}.get(kind, PLAIN)
        status_bar.configure(text=text, background=bg, foreground=fg)
    go = ttk.Button(frm, text='Patch'); go.grid(row=row, column=0, columnspan=3, pady=(10, 0), ipadx=24, ipady=4)

    def credits():
        """A window listing the software and references, each with its use and a link that opens in the browser."""
        import webbrowser
        w = tk.Toplevel(root); w.title('Credits'); w.transient(root)
        t = tk.Text(w, width=78, height=30, wrap='word', padx=14, pady=10, borderwidth=0, highlightthickness=0, cursor='arrow')
        sb = ttk.Scrollbar(w, command=t.yview); t.configure(yscrollcommand=sb.set)
        t.grid(row=0, column=0, sticky='nsew'); sb.grid(row=0, column=1, sticky='ns')
        w.columnconfigure(0, weight=1); w.rowconfigure(0, weight=1)
        t.tag_configure('head', font=('', 12, 'bold'), spacing1=10, spacing3=4)
        t.tag_configure('name', font=('', 10, 'bold'), spacing1=6)
        t.tag_configure('foot', justify='center', spacing1=16, font=('', 10, 'italic'))
        t.tag_configure('note', spacing1=14)
        for heading, items in CREDITS:
            t.insert('end', heading + '\n', 'head')
            for n, (name, use, url) in enumerate(items):
                tag = f'link{heading}{n}'
                t.insert('end', name + '\n', 'name'); t.insert('end', use + '\n'); t.insert('end', url + '\n', tag)
                t.tag_configure(tag, foreground='#0969da', underline=True)
                t.tag_bind(tag, '<Button-1>', lambda _e, u=url: webbrowser.open(u))
                t.tag_bind(tag, '<Enter>', lambda _e: t.configure(cursor='hand2'))
                t.tag_bind(tag, '<Leave>', lambda _e: t.configure(cursor='arrow'))
        t.insert('end', CREDITS_NOTE + '\n', 'note'); t.insert('end', CREDITS_FOOT + '\n', 'foot')
        t.configure(state='disabled')
        ttk.Button(w, text='Close', command=w.destroy).grid(row=1, column=0, columnspan=2, pady=8)
    ttk.Button(frm, text='Credits', command=credits).grid(row=row, column=2, sticky='e', pady=(10, 0))

    # The build runs in a worker thread. It never touches the window: it puts ('log' | 'status' | 'built' | 'fail', value)
    # on this queue, and pump() - run by the window every 100 ms - shows them.
    q = queue.Queue()
    def log(line):
        q.put(('log', str(line)))
    job = {}
    def worker(ps1, psp, opt):
        try:
            job['work'] = work_folder(psp)
            q.put(('built', build_iso(ps1, psp, job['work'], opt, log)))
        except (build.ToolFailed, RuntimeError) as e:
            q.put(('fail', str(e)))
        except SystemExit as e:
            q.put(('fail', str(e.code)))
        except Exception:
            log(traceback.format_exc()); q.put(('fail', 'unexpected error (see the log)'))
    def start():
        # the Patch button: clear the log, start the worker
        ps1, psp = (paths[k].get().strip() for k in ('ps1', 'psp'))
        if not (ps1 and psp):
            messagebox.showwarning(TITLE, 'Choose the two disc images first.'); return
        go.configure(state='disabled'); bar.configure(mode='indeterminate', value=0); bar.start(12); show_status('Starting ...')
        logbox.configure(state='normal'); logbox.delete('1.0', 'end'); logbox.configure(state='disabled')
        threading.Thread(target=worker, args=(ps1, psp, {**build.DEFAULT, **{k: v.get() for k, v in chosen.items()}}),
                         daemon=True).start()
    def pump():
        try:
            while True:
                kind, text = q.get_nowait()
                if kind == 'log':
                    if text in build.HEADINGS: show_status(text + ' ...')
                    logbox.configure(state='normal'); logbox.insert('end', text + '\n'); logbox.see('end'); logbox.configure(state='disabled')
                elif kind == 'status':                       # result of a file check: (key, path, level, message)
                    key, path, level, msg = text
                    if paths[key].get() == path:
                        status[key].configure(text=msg, foreground=COLOUR[level])
                else:
                    bar.stop(); bar.configure(mode='determinate', maximum=100, value=100 if kind == 'built' else 0); go.configure(state='normal')
                    if kind == 'built':
                        finish(text)
                    else:
                        cleanup()
                        log(f'PATCHING STOPPED: {text}'); show_status(f'Patching stopped: {text}', 'fail')
                        messagebox.showerror(TITLE, f'Patching stopped:\n\n{text}\n\nThe log has the details.')
        except queue.Empty:
            pass
        root.after(100, pump)
    def cleanup():
        # remove the working folder unless "Keep working files" is ticked
        if job.get('work') and not keep.get():
            shutil.rmtree(job['work'], ignore_errors=True)
    def finish(made):
        """Patching is done: ask where to save the new game, then move it there."""
        show_status('Choose where to save the patched game.')
        while True:
            out = filedialog.asksaveasfilename(title='Save the English game as', defaultextension='.iso',
                                               filetypes=[('PSP image', '*.iso')], initialfile='RockmanDASH_EN.iso',
                                               initialdir=os.path.dirname(paths['psp'].get()) or None)
            if out:
                break
            if messagebox.askyesno(TITLE, 'The patched game has not been saved.\n\nDiscard it?'):
                cleanup(); log('Not saved.'); bar.configure(value=0); show_status('Patching finished, but the game was not saved.'); return
        try:
            shutil.move(made, out)
        except OSError as e:
            show_status(f'Could not save to {out}', 'fail')
            messagebox.showerror(TITLE, f'Could not save to\n{out}\n\n{e}\n\nThe patched game is still at\n{made}'); return
        cleanup(); log(f'Written: {out}'); log('PATCHING COMPLETE.')
        show_status(f'Patching complete. Saved as {out}', 'done')
        messagebox.showinfo(TITLE, f'Finished.\n\n{out}')
    go.configure(command=start); pump(); root.mainloop()


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--headless':
        headless(sys.argv[2:])
    else:
        gui()
