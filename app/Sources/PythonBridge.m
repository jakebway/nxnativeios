#import <Foundation/Foundation.h>
#include <Python/Python.h>
#include "PythonBridge.h"

static int g_started;

int nxb_python_start(const char *bundle, const char *upstream, char *err, int errlen) {
    if (g_started) return 0;
    NSString *b = @(bundle);
    NSString *home = [b stringByAppendingPathComponent:@"python"];
    PyConfig config; PyConfig_InitIsolatedConfig(&config);
    config.install_signal_handlers = 0; config.write_bytecode = 0; config.buffered_stdio = 0;
    PyStatus st = PyConfig_SetBytesString(&config, &config.home, home.fileSystemRepresentation);
    if (PyStatus_Exception(st)) goto fail;
    // sys.executable = this app's executable: CPython's iOS importer finds the binary modules (.fwork) relative to it, and the NSP script runs "sys.executable script.py"
    st = PyConfig_SetBytesString(&config, &config.executable, NSBundle.mainBundle.executablePath.fileSystemRepresentation);
    if (PyStatus_Exception(st)) goto fail;
    // the search path: the stdlib from home, then app_packages (capstone, lz4) and app (nxbuild)
    NSString *ver = [NSString stringWithFormat:@"python%d.%d", PY_MAJOR_VERSION, PY_MINOR_VERSION];
    NSArray *paths = @[[home stringByAppendingPathComponent:[@"lib" stringByAppendingPathComponent:ver]],
                       [[home stringByAppendingPathComponent:[@"lib" stringByAppendingPathComponent:ver]] stringByAppendingPathComponent:@"lib-dynload"],
                       [b stringByAppendingPathComponent:@"app_packages"], [b stringByAppendingPathComponent:@"app"]];
    config.module_search_paths_set = 1;
    for (NSString *p in paths) {
        wchar_t *w = Py_DecodeLocale(p.fileSystemRepresentation, NULL);
        st = PyWideStringList_Append(&config.module_search_paths, w); PyMem_RawFree(w);
        if (PyStatus_Exception(st)) goto fail;
    }
    st = Py_InitializeFromConfig(&config);
    if (PyStatus_Exception(st)) goto fail;
    PyConfig_Clear(&config);
    setenv("NXB_UPSTREAM", upstream, 1);
    setenv("NXB_FRAMEWORKS", [b stringByAppendingPathComponent:@"Frameworks"].fileSystemRepresentation, 1);
    setenv("LIBCAPSTONE_PATH", [b stringByAppendingPathComponent:@"Frameworks/capstone.framework"].fileSystemRepresentation, 1);
    PyEval_SaveThread();   // release the GIL: builds take it on their own thread
    g_started = 1; return 0;
fail:
    snprintf(err, errlen, "%s: %s", st.func ? st.func : "Python", st.err_msg ? st.err_msg : "start failed");
    PyConfig_Clear(&config); return 1;
}

int nxb_python_build(const char *job_dir) {
    PyGILState_STATE g = PyGILState_Ensure();
    int rc = 1;
    PyObject *m = PyImport_ImportModule("nxbuild.app_entry");
    if (m) {
        PyObject *r = PyObject_CallMethod(m, "run", "s", job_dir);
        if (r) { rc = (int)PyLong_AsLong(r); Py_DECREF(r); }
        Py_DECREF(m);
    }
    if (PyErr_Occurred()) PyErr_Print();
    PyGILState_Release(g);
    return rc;
}
