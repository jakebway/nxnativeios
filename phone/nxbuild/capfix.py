"""capstone on iOS. Its Python loader (1) names the library by sys.platform, which is 'ios' here, so it looks for libcapstone.so (the framework holds
libcapstone.dylib): a symlink with that name in a temporary folder, named by LIBCAPSTONE_PATH, fixes it; (2) asks sysconfig for 'platlib' while building its
search list, which can raise on this Python: answered with '' instead (the failed call is not allowed to leave sysconfig half set up)."""
import os, sys, sysconfig, tempfile, traceback


def _link():
    fw = os.environ.get('LIBCAPSTONE_PATH', '')
    dylib = os.path.join(fw, 'libcapstone.dylib')
    if not os.path.isfile(dylib) or os.path.exists(os.path.join(fw, 'libcapstone.so')): return
    d = os.path.join(tempfile.gettempdir(), 'nxb-capstone'); os.makedirs(d, exist_ok=True)
    link = os.path.join(d, 'libcapstone.so')
    try:
        if os.path.islink(link) and os.readlink(link) != dylib: os.unlink(link)
        if not os.path.lexists(link): os.symlink(dylib, link)
        os.environ['LIBCAPSTONE_PATH'] = d
    except OSError: pass


def prepare(log=None):
    """Import capstone now (so the build script's later imports find it). Returns None, or the error text."""
    if 'capstone' in sys.modules: return None
    _link()
    real_get_path = sysconfig.get_path
    def get_path(name, *a, **k):
        try: return real_get_path(name, *a, **k)
        except Exception:
            sysconfig._CONFIG_VARS = None   # forget a half-finished setup
            return ''
    try:
        sysconfig.get_path = get_path
        import capstone   # noqa: F401
        return None
    except BaseException:
        err = traceback.format_exc()
        if log:
            for l in err.splitlines(): log('capstone: ' + l)
        return err
    finally:
        sysconfig.get_path = real_get_path
