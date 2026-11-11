"""capstone's Python loader picks the library name from sys.platform; on iOS that is 'ios', so it looks for libcapstone.so
(the framework holds libcapstone.dylib). Importing it while sys.platform says 'darwin' makes it load libcapstone.dylib from LIBCAPSTONE_PATH."""
import sys, traceback


def prepare(log=None):
    """Import capstone now (so the build script's later imports find it). Returns None, or the error text."""
    if 'capstone' in sys.modules: return None
    real = sys.platform
    try:
        sys.platform = 'darwin'
        import capstone   # noqa: F401
        return None
    except BaseException:
        err = traceback.format_exc()
        if log:
            for l in err.splitlines(): log('capstone: ' + l)
        return err
    finally:
        sys.platform = real
