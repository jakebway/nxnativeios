"""capstone on iOS. Its Python loader (1) names the library by sys.platform, which is 'ios' here, so it looks for libcapstone.so (the framework holds
libcapstone.dylib): the packaged capstone is patched at build time to treat 'ios' like 'darwin' (LIBCAPSTONE_PATH names the framework folder); (2) asks sysconfig for 'platlib' while building its
search list, which can raise on this Python: answered with '' instead (the failed call is not allowed to leave sysconfig half set up)."""
import os, sys, sysconfig, traceback


def prepare(log=None):
    """Import capstone now (so the build script's later imports find it). Returns None, or the error text."""
    if 'capstone' in sys.modules: return None
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
