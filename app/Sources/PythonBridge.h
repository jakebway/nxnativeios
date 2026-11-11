// The embedded CPython: start it once, run one build at a time on a background thread.
#pragma once
// Start Python with the app's stdlib (python/lib/python3.x), app_packages and app (nxbuild). Returns 0 on success, else writes the error to err.
int nxb_python_start(const char *bundle, const char *upstream, char *err, int errlen);
// nxbuild.app_entry.run(job_json): the build of one job folder. Blocks; returns its exit code. Progress goes to the job's log file.
int nxb_python_build(const char *job_dir);
