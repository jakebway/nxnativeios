"""capstone's Python loader picks the library name from sys.platform, and on iOS that is 'ios', so it looks for libcapstone.so
(the framework holds libcapstone.dylib). A symlink named libcapstone.so in a temporary folder, named by LIBCAPSTONE_PATH, gets it loaded."""
import os, tempfile


def prepare():
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
