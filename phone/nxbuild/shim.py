"""nxnativeios: run nxnative's build scripts on an iPhone, where no process can start another.

install() replaces subprocess.Popen (subprocess.run / check_output / call use it) with InProcess, which runs
each command in this process:

  python <script> args      the script, through runpy, one at a time (sys.argv / stdout / environ / cwd swapped)
  .../nx_extract, .../dmsh_xlate   NxTools.framework (nx_extract_main, dmsh_xlate_main)
  .../spirv-cross           SpirvCross.framework (spirv_cross_main); MSL meant for stdout goes through a temporary --output file
  xcrun ... metal / metallib   no compiler on the phone: the MSL source is written where the library goes
                            (nvn_mtl.m, patch 0002, compiles it on the device); other xcrun queries get fixed answers
  zstd -d -c                compression.zstd
  sysctl, xcode-select      fixed answers for an arm64 device

and multiprocessing pools with ThreadPool below (threads, no multiprocessing machinery): iOS has no fork.
Anything else fails with exit code 127 and says so.
"""
import contextlib, ctypes, io, os, runpy, shutil, subprocess, sys, tempfile, threading, types

PIPE, STDOUT, DEVNULL = subprocess.PIPE, subprocess.STDOUT, subprocess.DEVNULL
_RealPopen = subprocess.Popen
_py_lock = threading.RLock()      # Python scripts share sys.argv / sys.stdout / os.environ / cwd: one at a time
_tool_locks = {}                  # NxTools' tools share Console: one call at a time per framework
LOG = None                        # optional callable(line): every line any command prints, as it comes (the app's live log)
FRAMEWORKS = os.environ.get('NXB_FRAMEWORKS') or os.path.join(os.path.dirname(sys.executable), 'Frameworks')
METAL_VERSION = 'nxnativeios on-device Metal (MSL compiled at run time)'


class Result(Exception):
    def __init__(self, code): self.code = code


class _Sink(io.TextIOBase):
    """A text stream that collects what a command writes (and passes whole lines to LOG)."""
    def __init__(self): self.buf = io.StringIO(); self.line = ''
    def writable(self): return True
    def write(self, s):
        self.buf.write(s)
        if LOG:
            self.line += s
            *done, self.line = self.line.split('\n')
            for l in done: LOG(l)
        return len(s)
    def flush(self): pass
    @property
    def encoding(self): return 'utf-8'
    def fileno(self): raise io.UnsupportedOperation('fileno')
    def value(self): return self.buf.getvalue()


# ---- native tools ----
_LOGFN = ctypes.CFUNCTYPE(None, ctypes.c_char_p, ctypes.c_void_p)
_libs = {}

def _lib(framework):
    if framework not in _libs:
        p = os.path.join(FRAMEWORKS, f'{framework}.framework', framework)
        if not os.path.exists(p): p = os.path.join(FRAMEWORKS, f'lib{framework}.dylib')   # a test outside the app: NXB_FRAMEWORKS holds plain dylibs
        _libs[framework] = ctypes.CDLL(p)
    return _libs[framework]

def _nxtools(entry, args, out):
    lib = _lib('NxTools')
    f = getattr(lib, entry); f.restype = ctypes.c_int; f.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_char_p), _LOGFN, ctypes.c_void_p]
    cb = _LOGFN(lambda s, c: out.write(s.decode('utf-8', 'replace') + '\n'))
    argv = (ctypes.c_char_p * max(1, len(args)))(*[os.fsencode(a) for a in args])
    with _tool_locks.setdefault('NxTools', threading.Lock()):
        return f(len(args), argv, cb, None)

def _spirv_cross(args, out):
    lib = _lib('SpirvCross')
    f = lib.spirv_cross_main; f.restype = ctypes.c_int; f.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_char_p)]
    tmp = None
    if '--output' not in args and any(a.endswith('.spv') or os.path.isfile(a) for a in args) and '--revision' not in args:
        fd, tmp = tempfile.mkstemp(suffix='.metal'); os.close(fd); args = [*args, '--output', tmp]   # stdout is one per process: the MSL comes back through a file
    argv = (ctypes.c_char_p * (len(args) + 1))(b'spirv-cross', *[os.fsencode(a) for a in args])
    rc = f(len(args) + 1, argv)
    if tmp:
        try:
            if rc == 0: out.write(open(tmp, encoding='utf-8', errors='replace').read())
        finally: os.unlink(tmp)
    return rc


# ---- no Metal compiler on the phone ----
def _opt(args, name):
    return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else None

def _xcrun(args, out, stdin):
    a = list(args)
    while a and a[0] in ('-sdk', '--sdk'): a = a[2:]
    if not a: return 1
    if a[0] in ('-f', '--find'): out.write(f'/nxnativeios/xcrun/{a[1]}\n'); return 0
    if a[0] == '--show-sdk-path': out.write('/nxnativeios/sdk\n'); return 0
    if a[0] in ('--show-sdk-version', '--show-sdk-build-version'): out.write('26.0\n'); return 0
    return _metal(a[0], a[1:], out, stdin)

def _metal(tool, a, out, stdin):
    tool = os.path.basename(tool)
    if '--version' in a: out.write(f'{METAL_VERSION}\n'); return 0
    dst = _opt(a, '-o')
    if tool == 'metal':
        if '-x' in a and _opt(a, '-x') == 'metal-header':   # a precompiled header: nothing to precompile
            open(dst, 'wb').close(); return 0
        if '-' in a: data = stdin if stdin is not None else b''   # the source on stdin (dmsh_pch._run)
        else:
            srcs = [x for x in a if x.endswith('.metal')]
            data = open(srcs[-1], 'rb').read()
        with open(dst, 'wb') as f: f.write(data)   # "AIR" = the MSL source
        return 0
    if tool == 'metallib':
        ins = [x for x in a if not x.startswith('-') and x != dst]
        shutil.copyfile(ins[0], dst)   # the "library" = the MSL source (one input: the chain links one AIR per library)
        return 0
    out.write(f'[RED] nxnativeios: {tool} is not available on the phone\n'); return 127

def _sysctl(args, out):
    known = {'hw.optional.arm64': '1', 'sysctl.proc_translated': '0', 'hw.ncpu': str(os.cpu_count() or 1), 'hw.memsize': str(8 << 30)}
    k = args[-1]
    if k in known: out.write(known[k] + '\n'); return 0
    return 1

def _zstd(args, out_bin, stdin):
    import compression.zstd as z
    if '-d' in args:
        out_bin.write(z.decompress(stdin or b'')); return 0
    return 127


# ---- Python scripts ----
def _set_environ(want):
    """Make os.environ equal to want by changing only what differs: clearing and refilling it all frees and rebuilds the process's environment while the app's other threads read it."""
    for k in [k for k in os.environ if k not in want]: del os.environ[k]
    for k, v in want.items():
        if os.environ.get(k) != v: os.environ[k] = v


def _python(args, out, env, cwd):
    a = list(args)
    while a and a[0] in ('-I', '-u', '-B', '-E', '-s', '-S', '-O'): a = a[1:]
    if not a: return 2
    if a[0] == '-c':
        code, argv = a[1], ['-c', *a[2:]]
        target = lambda: exec(compile(code, '<string>', 'exec'), {'__name__': '__main__'})
    elif a[0] == '-m':
        argv = [a[1], *a[2:]]; target = lambda: runpy.run_module(a[1], run_name='__main__', alter_sys=True)
    else:
        script = os.path.abspath(a[0]) if cwd is None else os.path.abspath(os.path.join(cwd, a[0]))
        argv = [script, *a[1:]]; target = lambda: runpy.run_path(script, run_name='__main__')
    with _py_lock:
        saved = (sys.argv, list(sys.path), dict(os.environ), os.getcwd())
        sys.argv = argv
        if argv and argv[0] not in ('-c',) and os.path.isfile(argv[0]): sys.path.insert(0, os.path.dirname(argv[0]))
        if env is not None: _set_environ(env)
        if cwd: os.chdir(cwd)
        code = 0
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                target()
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else (0 if e.code is None else (out.write(f'{e.code}\n') and 1))
        except BaseException as e:
            import traceback; out.write(traceback.format_exc()); code = 1
        finally:
            sys.argv, sys.path[:] = saved[0], saved[1]
            _set_environ(saved[2]); os.chdir(saved[3])
        return code


def _dispatch(args, out, out_bin, stdin, env, cwd):
    exe = os.path.basename(str(args[0]))
    rest = [os.fspath(x) for x in args[1:]]
    if exe.startswith('python') or os.path.abspath(str(args[0])) == os.path.abspath(sys.executable): return _python(rest, out, env, cwd)
    if exe == 'nx_extract': return _nxtools('nx_extract_main', rest, out)
    if exe == 'dmsh_xlate': return _nxtools('dmsh_xlate_main', rest, out)
    if exe == 'spirv-cross': return _spirv_cross(rest, out)
    if exe == 'xcrun': return _xcrun(rest, out, stdin)
    if exe in ('metal', 'metallib'): return _metal(exe, rest, out, stdin)
    if exe == 'sysctl': return _sysctl(rest, out)
    if exe == 'xcode-select': out.write('/nxnativeios/xcode\n'); return 0
    if exe == 'zstd': return _zstd(rest, out_bin, stdin)
    if exe == 'bash' and rest and rest[0].endswith('build_ipa.sh'): return _build_ipa(rest[1:], out, env)
    out.write(f'[RED] nxnativeios: "{exe}" cannot run on the phone ({" ".join(map(str, args))[:200]})\n')
    return 127


def _build_ipa(args, out, env):
    """build_ipa.sh <out.ipa>: assemble.py puts the IPA together from the shell (no xcodebuild on the phone)"""
    if not args or args[0].startswith('--'): out.write('[RED] nxnativeios: only "build_ipa.sh <out.ipa>" runs on the phone (no Xcode project)\n'); return 2
    from . import assemble
    saved = dict(os.environ)
    try:
        if env is not None: os.environ.clear(); os.environ.update(env)
        assemble.assemble(__import__('pathlib').Path(args[0]), log=lambda l: out.write(l + '\n'))
        return 0
    except assemble.AssembleError as e: out.write(f'[RED] {e}\n'); return 1
    finally: _set_environ(saved)


class InProcess:
    """subprocess.Popen's interface; the command runs in this process: at construction, or at communicate() when it reads stdin."""
    def __init__(self, args, bufsize=-1, executable=None, stdin=None, stdout=None, stderr=None, preexec_fn=None, close_fds=True, shell=False,
                 cwd=None, env=None, universal_newlines=None, startupinfo=None, creationflags=0, restore_signals=True, start_new_session=False,
                 pass_fds=(), *, user=None, group=None, extra_groups=None, encoding=None, errors=None, text=None, umask=-1, pipesize=-1, process_group=None):
        if shell or isinstance(args, (str, bytes)): args = ['/bin/sh', '-c', args] if shell else [args]
        self.args = list(args); self.pid = 0; self.returncode = None
        self._text = bool(text or universal_newlines or encoding or errors)
        self._enc, self._err = encoding or 'utf-8', errors or 'strict'
        self._spec = (stdin, stdout, stderr); self._env = env; self._cwd = os.fspath(cwd) if cwd else None
        self.stdin = io.BytesIO() if stdin == PIPE else None
        self.stdout = self.stderr = None
        self._out = self._errout = None
        if stdin != PIPE: self._run(None)

    def _run(self, data):
        stdin, stdout, stderr = self._spec
        if data is None and stdin not in (None, PIPE, DEVNULL):   # a file
            f = stdin if hasattr(stdin, 'read') else open(stdin, 'rb', closefd=False)
            data = f.read()
        if isinstance(data, str): data = data.encode(self._enc)
        out, bin_ = _Sink(), io.BytesIO()
        try: self.returncode = _dispatch(self.args, out, bin_, data, self._env, self._cwd)
        except Exception as e: out.write(f'[RED] nxnativeios: {self.args[0]}: {e!r}\n'); self.returncode = 1
        payload = bin_.getvalue() + out.value().encode('utf-8', 'replace')
        self._deliver(payload, stdout, 'stdout')
        if stderr not in (None, STDOUT, DEVNULL, PIPE): pass   # everything went to stdout's payload; a separate stderr file gets nothing
        if stderr == PIPE: self.stderr = self._wrap(b''); self._errout = b''

    def _wrap(self, b):
        return io.StringIO(b.decode(self._enc, self._err)) if self._text else io.BytesIO(b)

    def _deliver(self, payload, target, name):
        if target == PIPE:
            self._out = payload; self.stdout = self._wrap(payload)
        elif target in (None, DEVNULL):
            if target is None and LOG is None: sys.stdout.write(payload.decode('utf-8', 'replace'))
        elif isinstance(target, int):
            os.write(target, payload)
        else:
            try: target.write(payload if 'b' in getattr(target, 'mode', 'b') else payload.decode('utf-8', 'replace'))
            except TypeError: target.write(payload.decode('utf-8', 'replace'))
            with contextlib.suppress(Exception): target.flush()

    def communicate(self, input=None, timeout=None):
        if self.returncode is None:
            if input is None and self.stdin is not None: input = self.stdin.getvalue()
            self._run(input)
        conv = lambda b: None if b is None else (b.decode(self._enc, self._err) if self._text else b)
        return conv(self._out), conv(self._errout)

    def wait(self, timeout=None):
        if self.returncode is None: self.communicate()
        return self.returncode
    def poll(self): return self.returncode
    def kill(self): pass
    terminate = kill
    def send_signal(self, sig): pass
    def __enter__(self): return self
    def __exit__(self, *exc):
        for s in (self.stdout, self.stderr, self.stdin):
            if s: s.close()
        if self.returncode is None: self.wait()


class ThreadPool:
    """multiprocessing.Pool's interface on concurrent.futures threads: no fork, no semaphores, no pipes."""
    def __init__(self, processes=None, initializer=None, initargs=(), maxtasksperchild=None, context=None):
        import concurrent.futures as cf
        self._ex = cf.ThreadPoolExecutor(processes or os.cpu_count() or 1, initializer=initializer, initargs=initargs)
    def map(self, fn, it, chunksize=None): return list(self._ex.map(fn, it))
    def starmap(self, fn, it, chunksize=None): return list(self._ex.map(lambda a: fn(*a), it))
    def imap(self, fn, it, chunksize=1): return self._ex.map(fn, it)
    def imap_unordered(self, fn, it, chunksize=1):
        import concurrent.futures as cf
        for f in cf.as_completed([self._ex.submit(fn, x) for x in it]): yield f.result()
    def apply(self, fn, args=(), kwds={}): return fn(*args, **kwds)
    def apply_async(self, fn, args=(), kwds={}, callback=None, error_callback=None):
        f = self._ex.submit(fn, *args, **kwds)
        class R:
            def get(self, timeout=None): return f.result(timeout)
            def wait(self, timeout=None): f.exception(timeout)
            def ready(self): return f.done()
            def successful(self): return f.done() and f.exception() is None
        if callback or error_callback:
            def done(x):
                e = x.exception()
                if e is None and callback: callback(x.result())
                elif e is not None and error_callback: error_callback(e)
            f.add_done_callback(done)
        return R()
    def map_async(self, fn, it, chunksize=None, callback=None, error_callback=None):
        return self.apply_async(lambda: self.map(fn, it), callback=callback, error_callback=error_callback)
    def starmap_async(self, fn, it, chunksize=None, callback=None, error_callback=None):
        return self.apply_async(lambda: self.starmap(fn, it), callback=callback, error_callback=error_callback)
    def close(self): pass
    def join(self): self._ex.shutdown(wait=True)
    def terminate(self): self._ex.shutdown(wait=False, cancel_futures=True)
    def __enter__(self): return self
    def __exit__(self, *e): self.terminate() if e[0] else self.join()


class _Context:
    """multiprocessing.get_context('fork') and friends: the real context, with Pool replaced"""
    def __init__(self, real): self._real = real
    def __getattr__(self, name): return getattr(self._real, name)
    Pool = ThreadPool
    def get_start_method(self, allow_none=False): return 'thread'


def install(log=None):
    """Make every subprocess and multiprocessing pool of this interpreter run in it."""
    global LOG
    LOG = log
    subprocess.Popen = InProcess
    import multiprocessing, concurrent.futures as cf
    real_ctx = multiprocessing.get_context
    multiprocessing.Pool = ThreadPool
    multiprocessing.get_context = lambda method=None: _Context(real_ctx(None))
    cf.ProcessPoolExecutor = lambda max_workers=None, mp_context=None, initializer=None, initargs=(), **k: cf.ThreadPoolExecutor(max_workers, initializer=initializer, initargs=initargs)
    os.environ.setdefault('DM_REWRITE_J', '1')     # patch_nso.py: no worker processes
    os.environ.setdefault('DMSH_PROCS', '0')       # dmsh_build.py: threads, not processes
    os.environ.setdefault('DMSH_PCH', '0')         # no precompiled Metal header: there is no Metal compiler
    os.environ.setdefault('DM_ALLOW_OTHER_METAL', '1')   # the lock's compiler cannot be on the phone (docs/DESIGN.md)
    _patch_on_import('dmsh_side', _side_patch)
    _patch_on_import('tool_lock', _lock_patch)


def _lock_patch(m):
    """tool_lock.tools_now fingerprints the committed macOS executables of the translator and SPIRV-Cross. The phone runs NxTools.framework and SpirvCross.framework instead,
    built from the same pinned sources (CI: dmsh_xlate's embedded source digest equals the in-repo one, SpirvCross gives the pinned binary's MSL byte for byte), so those two
    report the lock's values. The translator's embedded source digest is still asked of the real tool; the Metal compilers report what runs here (METAL_VERSION), which only
    DM_ALLOW_OTHER_METAL lets through."""
    real = m.tools_now
    def tools_now():
        want = dict(l.rstrip('\n').split('\t', 1) for l in open(m.LOCK) if '\t' in l and not l.startswith('#'))
        t = dict(want)
        t['xlate_source'] = m.xlate_embedded()
        for sdk in ('macosx', 'iphoneos'): t['metal_' + sdk] = METAL_VERSION
        return t
    m.tools_now = tools_now


def _side_patch(m):
    """dmsh_side.cut parses a compiled metallib. A library here is MSL source: each piece is the whole source (the host finds each entry point by name)."""
    real = m.cut
    def cut(lib, *groups):
        if lib[:4] == b'MTLB': return real(lib, *groups)
        return tuple(lib for _ in range(len(groups) + 1))
    m.cut = cut


def _patch_on_import(name, fn):
    import importlib.abc, importlib.machinery
    if name in sys.modules: fn(sys.modules[name]); return
    class Hook(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path, target=None):
            if fullname != name: return None
            sys.meta_path.remove(self)
            spec = importlib.machinery.PathFinder.find_spec(fullname, path)
            if spec and spec.loader:
                real_exec = spec.loader.exec_module
                def exec_module(module): real_exec(module); fn(module)
                spec.loader.exec_module = exec_module
            return spec
    sys.meta_path.insert(0, Hook())
