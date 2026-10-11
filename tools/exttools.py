"""Where the external program is (THIRD_PARTY.md). In this order: the environment variable if set, the
project's bin/<platform>/ folder (release binaries, or what build_atracdenc() compiled), bin/, then the PATH.
  atracdenc         ATRACDENC=           ATRAC3plus encoder; the project's modified copy is in src/atracdenc (LGPL)
<platform> is linux-x86_64, linux-aarch64, macos-arm64, macos-x86_64, windows-x86_64, ... (platform_tag()).
Used by build.py (pre-flight check, compiling atracdenc) and the voice tools in tools/voice/. Only builds with
English audio (--localization=audio|legends) need it (the PS1 audio itself is decoded by tools/voice/xa.py); the audio side is described in docs/RESEARCH.md §10."""
import os, sys, shutil, platform, subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# e.g. "linux-x86_64": operating system and CPU, with the usual aliases (amd64, x64, arm64) folded together
def platform_tag():
    osn = {'darwin': 'macos', 'win32': 'windows'}.get(sys.platform, 'linux' if sys.platform.startswith('linux') else sys.platform)
    m = platform.machine().lower()
    m = {'amd64': 'x86_64', 'x64': 'x86_64', 'arm64': 'arm64' if osn == 'macos' else 'aarch64'}.get(m, m)
    return f'{osn}-{m}'


def bin_dir():
    return os.path.join(ROOT, 'bin', platform_tag())


def find(name):
    """-> path of the program, or None. name is the lower-case program name; its environment variable is the same name
    in capitals and may hold a full path or a command name to look up on the PATH."""
    p = os.environ.get(name.upper())
    if p:
        p = os.path.expanduser(p)
        return p if os.path.isfile(p) else shutil.which(p)
    for d in (bin_dir(), os.path.join(ROOT, 'bin')):
        for cand in (os.path.join(d, name), os.path.join(d, name + '.exe')):
            if os.path.isfile(cand):
                return cand
    return shutil.which(name)


# find() or stop the build with a message that says where the program is expected
def require(name):
    p = find(name)
    if not p:
        raise SystemExit(f'{name} not found: put it in bin/{platform_tag()}/, on the PATH, or set {name.upper()}=<path to the '
                         f'program> (docs/BUILD.md section 1; THIRD_PARTY.md)')
    return p


def build_atracdenc():
    """Compile src/atracdenc into bin/<platform>/ (needs cmake and a C++ compiler; Linux/macOS also libsndfile's
    development files). Extra cmake arguments: ATRACDENC_CMAKE_ARGS (e.g. -DCMAKE_PREFIX_PATH=/opt/homebrew).
    -> path of the program, or exits with what is missing."""
    src = os.path.join(ROOT, 'src', 'atracdenc')
    cmake = shutil.which('cmake')
    if not os.path.isfile(os.path.join(src, 'CMakeLists.txt')):
        raise SystemExit('atracdenc not found and src/atracdenc is missing (docs/BUILD.md section 1)')
    if not cmake:
        raise SystemExit(f'atracdenc not found. To compile the included source (src/atracdenc) install cmake and a C++ '
                         f'compiler (Linux/macOS: also libsndfile), or put a release binary in bin/{platform_tag()}/ (docs/BUILD.md section 1)')
    bld = os.path.join(ROOT, 'build', 'atracdenc')
    extra = os.environ.get('ATRACDENC_CMAKE_ARGS', '').split()
    if sys.platform == 'darwin' and not any(a.startswith('-DCMAKE_OSX_ARCHITECTURES') for a in extra):
        # this machine's architecture only: the source's default, a universal build, needs a universal libsndfile
        extra.insert(0, '-DCMAKE_OSX_ARCHITECTURES=' + platform.machine())
    if sys.platform != 'win32':
        # no debug information in the program: it would record this machine's folder names (user name included)
        extra.insert(0, '-DCMAKE_EXE_LINKER_FLAGS=-Wl,-S')
    print('compiling src/atracdenc (once) ...', flush=True)
    for cmd in ([cmake, '-S', src, '-B', bld, '-DCMAKE_BUILD_TYPE=Release', *extra],
                [cmake, '--build', bld, '--target', 'atracdenc', '--config', 'Release']):
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        if r.returncode:
            raise SystemExit(r.stdout[-3000:] + '\ncompiling src/atracdenc failed (docs/BUILD.md sections 1 and 7: cmake, a C++ compiler, '
                             'libsndfile on Linux/macOS, the ATL component on Windows; ATRACDENC_CMAKE_ARGS for extra cmake arguments)')
    exe = 'atracdenc.exe' if sys.platform == 'win32' else 'atracdenc'
    built = [os.path.join(dp, f) for dp, _, fs in os.walk(bld) for f in fs if f == exe]
    if not built:
        raise SystemExit('compiling src/atracdenc gave no program')
    os.makedirs(bin_dir(), exist_ok=True)
    out = os.path.join(bin_dir(), exe)
    if os.path.exists(out):                                  # not overwritten in place: macOS kills a program whose
        try:                                                 # file was rewritten (code signature cached per file)
            os.remove(out)
        except OSError:
            pass
    shutil.copy2(built[0], out)
    home = os.path.expanduser('~').encode()
    if len(home) > 3 and home in open(out, 'rb').read():
        print(f'WARNING: {out} contains the path {home.decode()} (do not publish this file as it is)', flush=True)
    return out
