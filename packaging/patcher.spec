# PyInstaller spec for the graphical patcher (gui.py):  pyinstaller packaging/patcher.spec
# One file per platform. Inside: gui.py and build.py (frozen), tools/ and script/ as data (the build steps are plain
# scripts that the frozen program runs with runpy), the licence files, and bin/<platform>/ with atracdenc,
# which must be in place before packaging (.github/workflows/release.yml puts them there).
# The tools are not analysed by PyInstaller, so every module they import is listed as a hidden import below.
# Run on Linux (aarch64, --headless: same ISO as build.py) and on macOS (Apple Silicon, with the window; the result
# was played on a PSP Go), and on Windows (x64, with the window: built by build_release.ps1, patched a UMD image).
import ast, glob, os

ROOT = os.path.abspath(os.path.join(SPECPATH, '..'))
tools = glob.glob(os.path.join(ROOT, 'tools', '**', '*.py'), recursive=True)
local = {os.path.splitext(os.path.basename(f))[0] for f in tools}
optional = {'unicorn', 'zstandard', 'mlx_whisper', 'cmake'}        # never needed by a build
hidden = set()
for f in tools + [os.path.join(ROOT, 'build.py')]:
    for n in ast.walk(ast.parse(open(f, encoding='utf-8').read())):
        if isinstance(n, ast.Import):
            hidden.update(a.name for a in n.names)
        elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
            hidden.add(n.module)
            hidden.update(f'{n.module}.{a.name}' for a in n.names)     # 'from PIL import Image' needs PIL.Image
hidden = sorted(m for m in hidden if m.split('.')[0] not in local | optional)

datas = [(os.path.join(ROOT, d), d) for d in ('tools', 'script', 'LICENSES')]
datas += [(os.path.join(ROOT, f), '.') for f in ('LICENSE', 'THIRD_PARTY.md', 'README.md')]
binaries = [(f, os.path.relpath(os.path.dirname(f), ROOT))
            for f in glob.glob(os.path.join(ROOT, 'bin', '*', '*')) if os.path.isfile(f)]
assert binaries, 'put atracdenc in bin/<platform>/ first (tools/exttools.py: platform_tag())'

a = Analysis([os.path.join(ROOT, 'gui.py')], pathex=[ROOT], datas=datas, binaries=binaries, hiddenimports=hidden,
             excludes=sorted(optional))
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [('X utf8', None, 'OPTION')],      # UTF-8 mode: the tools read text files without naming an encoding
          a.binaries, a.datas, name='RockmanDASH-PSP-English-Patcher', console=False, upx=False)
