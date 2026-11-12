#import <Foundation/Foundation.h>
#include <Python/Python.h>
#include "PythonBridge.h"
#include <signal.h>
#include <execinfo.h>
#include <fcntl.h>
#include <unistd.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <pthread.h>
#include <mach/mach.h>
#include <time.h>

// ---- the app's process outlives anything a build does ----
// python3 on a Mac ignores SIGPIPE and SIGXFSZ (CPython's own signal setup); embedded with install_signal_handlers = 0 it does not, and either one ends the app at once with no crash report.
// Every other way out of the process is written to the build's log (async-signal-safe writes only), so a build that vanishes says how.
static volatile int g_logfd = -1;

static void say(const char *s) { int fd = g_logfd; if (fd >= 0) write(fd, s, strlen(s)); }
static void trace(void) { void *f[64]; int n = backtrace(f, 64); int fd = g_logfd; if (fd >= 0) backtrace_symbols_fd(f, n, fd); }

// Who sends it: the signal's sender (si_pid; 0 = the kernel or the system) is written to the log.
static void on_signal(int sig, siginfo_t *info, void *ctx) {
    char b[160]; snprintf(b, sizeof b, "\n[fatal] the app received signal %d (%s) from pid %d, code %d\n", sig, sig < NSIG ? sys_signame[sig] : "?", info ? info->si_pid : -1, info ? info->si_code : -1);
    say(b); trace();
    // A polite request to end (SIGTERM and friends) is not what ends a build on a phone: iOS ends apps with SIGKILL, which cannot be caught. Something sent this one in the middle of a build: ignored.
    if (sig == SIGTERM || sig == SIGHUP || sig == SIGINT || sig == SIGQUIT || sig == SIGUSR1 || sig == SIGUSR2 || sig == SIGALRM) { say("[fatal] ignored: the build goes on\n"); return; }
    signal(sig, SIG_DFL); raise(sig);
}

static void on_exit_called(void) { say("\n[fatal] exit() was called: the app is ending\n"); trace(); }

// A heartbeat that does not depend on Python or its lock: when the build's Python lines stop, these lines say whether the whole app is gone (they stop too)
// or Python is stuck (they go on), and what the app's memory footprint (the number iOS closes an app by) was.
static void *heartbeat(void *arg) {
    for (;;) {
        sleep(2);
        task_vm_info_data_t vi; mach_msg_type_number_t cnt = TASK_VM_INFO_COUNT; mach_port_t self = mach_task_self();
        thread_act_array_t th; mach_msg_type_number_t nth = 0; task_threads(self, &th, &nth);
        for (mach_msg_type_number_t i = 0; i < nth; i++) mach_port_deallocate(self, th[i]);
        if (nth) vm_deallocate(self, (vm_address_t)th, nth * sizeof(thread_act_t));
        long mb = task_info(self, TASK_VM_INFO, (task_info_t)&vi, &cnt) == KERN_SUCCESS ? (long)(vi.phys_footprint >> 20) : -1;
        char b[120]; time_t t = time(NULL); struct tm tm; localtime_r(&t, &tm);
        snprintf(b, sizeof b, "[native %02d:%02d:%02d] footprint %ld MB, %u threads\n", tm.tm_hour, tm.tm_min, tm.tm_sec, mb, nth);
        say(b);
    }
    return NULL;
}

static void guard_process(void) {
    static int done; if (done) return; done = 1;
    signal(SIGPIPE, SIG_IGN); signal(SIGXFSZ, SIG_IGN);
    int sigs[] = {SIGTERM, SIGHUP, SIGINT, SIGQUIT, SIGUSR1, SIGUSR2, SIGALRM, SIGVTALRM, SIGPROF, SIGXCPU, SIGSYS, SIGABRT, SIGTRAP, SIGEMT, SIGSEGV, SIGBUS, SIGILL, SIGFPE};
    for (size_t i = 0; i < sizeof sigs / sizeof *sigs; i++) {
        struct sigaction sa = {0}; sa.sa_sigaction = on_signal; sa.sa_flags = SA_SIGINFO; sigemptyset(&sa.sa_mask); sigaction(sigs[i], &sa, NULL);
    }
    atexit(on_exit_called);
    pthread_t th; pthread_create(&th, NULL, heartbeat, NULL); pthread_detach(th);
}

static int g_started;

static PyStatus configure(PyConfig *config, NSString *b) {
    NSString *home = [b stringByAppendingPathComponent:@"python"];
    PyStatus st = PyConfig_SetBytesString(config, &config->home, home.fileSystemRepresentation);
    if (PyStatus_Exception(st)) return st;
    // sys.executable = this app's executable: CPython's iOS importer finds the binary modules (.fwork) relative to it, and the NSP script runs "sys.executable script.py"
    st = PyConfig_SetBytesString(config, &config->executable, NSBundle.mainBundle.executablePath.fileSystemRepresentation);
    if (PyStatus_Exception(st)) return st;
    // the search path: the stdlib from home, then app_packages (capstone, lz4) and app (nxbuild)
    NSString *lib = [[home stringByAppendingPathComponent:@"lib"] stringByAppendingPathComponent:[NSString stringWithFormat:@"python%d.%d", PY_MAJOR_VERSION, PY_MINOR_VERSION]];
    NSArray<NSString *> *paths = @[lib, [lib stringByAppendingPathComponent:@"lib-dynload"],
                                   [b stringByAppendingPathComponent:@"app_packages"], [b stringByAppendingPathComponent:@"app"]];
    config->module_search_paths_set = 1;
    for (NSString *p in paths) {
        wchar_t *w = Py_DecodeLocale(p.fileSystemRepresentation, NULL);
        st = PyWideStringList_Append(&config->module_search_paths, w); PyMem_RawFree(w);
        if (PyStatus_Exception(st)) return st;
    }
    return PyStatus_Ok();
}

int nxb_python_start(const char *bundle, const char *upstream, char *err, int errlen) {
    if (g_started) return 0;
    NSString *b = @(bundle);
    PyConfig config; PyConfig_InitIsolatedConfig(&config);
    config.install_signal_handlers = 0; config.write_bytecode = 0; config.buffered_stdio = 0;
    PyStatus st = configure(&config, b);
    if (!PyStatus_Exception(st)) st = Py_InitializeFromConfig(&config);
    PyConfig_Clear(&config);
    if (PyStatus_Exception(st)) { snprintf(err, errlen, "%s: %s", st.func ? st.func : "Python", st.err_msg ? st.err_msg : "start failed"); return 1; }
    setenv("NXB_UPSTREAM", upstream, 1);
    setenv("NXB_FRAMEWORKS", [b stringByAppendingPathComponent:@"Frameworks"].fileSystemRepresentation, 1);
    setenv("LIBCAPSTONE_PATH", [b stringByAppendingPathComponent:@"Frameworks/capstone.framework"].fileSystemRepresentation, 1);
    PyEval_SaveThread();   // release the GIL: builds take it on their own thread
    g_started = 1; return 0;
}

int nxb_python_build(const char *job_dir) {
    guard_process();
    char path[2048]; snprintf(path, sizeof path, "%s/log.txt", job_dir);
    int fd = open(path, O_WRONLY | O_APPEND | O_CREAT, 0644);
    if (fd >= 0) {
        struct rlimit r; char b[200];
        getrlimit(RLIMIT_FSIZE, &r); snprintf(b, sizeof b, "[limits] file size %llu, ", (unsigned long long)r.rlim_cur); write(fd, b, strlen(b));
        getrlimit(RLIMIT_NOFILE, &r); snprintf(b, sizeof b, "open files %llu, ", (unsigned long long)r.rlim_cur); write(fd, b, strlen(b));
        getrlimit(RLIMIT_STACK, &r); snprintf(b, sizeof b, "stack %llu\n", (unsigned long long)r.rlim_cur); write(fd, b, strlen(b));
        int old = g_logfd; g_logfd = fd; if (old >= 0) close(old);
    }
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

char *nxb_python_selftest(void) {
    PyGILState_STATE g = PyGILState_Ensure();
    char *out = NULL;
    PyObject *m = PyImport_ImportModule("nxbuild.selftest");
    if (m) {
        PyObject *r = PyObject_CallMethod(m, "run", "s", "");
        if (r) { const char *s = PyUnicode_AsUTF8(r); if (s) out = strdup(s); Py_DECREF(r); }
        Py_DECREF(m);
    }
    if (!out && PyErr_Occurred()) {
        PyObject *t, *v, *tb; PyErr_Fetch(&t, &v, &tb);
        PyObject *sv = v ? PyObject_Str(v) : NULL; const char *msg = sv ? PyUnicode_AsUTF8(sv) : "unknown error";
        size_t n = strlen(msg) + 40; out = malloc(n); snprintf(out, n, "Python error: %s", msg ? msg : "?");
        Py_XDECREF(sv); Py_XDECREF(t); Py_XDECREF(v); Py_XDECREF(tb);
    }
    PyGILState_Release(g);
    return out;
}
