// nxnativeios: SPIRV-Cross's command line (main.cpp, compiled with -Dmain=spirv_cross_cli_main -Dexit=nx_spvc_exit) as a C function in an iOS framework.
//   int spirv_cross_main(int argc, const char **argv)   argv[0] is the program name, as for main()
// main.cpp ends the process with exit() on bad input; here that throws and becomes the return value, so a bad shader cannot end the builder app.
#include <exception>
#include <cstdio>
struct NxSpvcExit { int code; };
extern "C" [[noreturn]] void nx_spvc_exit(int code) { throw NxSpvcExit{code}; }
int spirv_cross_cli_main(int argc, char *argv[]);
extern "C" __attribute__((visibility("default"))) int spirv_cross_main(int argc, const char **argv) {
    try { return spirv_cross_cli_main(argc, const_cast<char **>(argv)); }
    catch (const NxSpvcExit &e) { return e.code; }
    catch (const std::exception &e) { fprintf(stderr, "[RED] spirv-cross: %s\n", e.what()); return 1; }
    catch (...) { fprintf(stderr, "[RED] spirv-cross: unknown exception\n"); return 1; }
}
