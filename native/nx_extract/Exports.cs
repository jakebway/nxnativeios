// nxnativeios: nxnative's nx_extract (LibHac) as a C function inside an iOS framework, for the builder app.
//   int nx_extract_main(int argc, const char **argv, void (*log)(const char *line, void *ctx), void *ctx)
// argv has no program name: argv[0] is nx_extract's first argument. Every line it prints (stdout and stderr) goes to log; returns its exit code.
using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;

static unsafe class NxExports {
    sealed class LineWriter : TextWriter {
        readonly delegate* unmanaged<byte*, void*, void> fn; readonly void* ctx; readonly StringBuilder sb = new();
        public LineWriter(delegate* unmanaged<byte*, void*, void> f, void* c) { fn = f; ctx = c; }
        public override Encoding Encoding => Encoding.UTF8;
        public override void Write(char c) { lock (sb) { if (c == '\n') Emit(); else if (c != '\r') sb.Append(c); } }
        public override void Flush() { lock (sb) if (sb.Length > 0) Emit(); }
        void Emit() {
            var b = Encoding.UTF8.GetBytes(sb.ToString() + "\0"); sb.Clear();
            if (fn != null) fixed (byte* p = b) fn(p, ctx);
        }
    }

    // The embedded resource names, one per line through log (a diagnostic for the --source-sha check)
    [UnmanagedCallersOnly(EntryPoint = "nx_extract_resources")]
    static void Resources(delegate* unmanaged<byte*, void*, void> log, void* ctx) {
        var w = new LineWriter(log, ctx);
        foreach (var n in typeof(P).Assembly.GetManifestResourceNames()) w.WriteLine(n);
        w.WriteLine($"assembly {typeof(P).Assembly.FullName}"); w.Flush();
    }

    [UnmanagedCallersOnly(EntryPoint = "nx_extract_main")]
    static int Main(int argc, byte** argv, delegate* unmanaged<byte*, void*, void> log, void* ctx) {
        var w = new LineWriter(log, ctx);
        Console.SetOut(w); Console.SetError(w);
        try {
            var a = new string[argc];
            for (int i = 0; i < argc; i++) a[i] = Marshal.PtrToStringUTF8((IntPtr)argv[i]);
            return P.Main(a);
        } catch (Exception e) { Console.WriteLine($"[RED] nx_extract: {e}"); return 99; }
        finally { w.Flush(); }
    }
}
