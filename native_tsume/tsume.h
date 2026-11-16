#pragma once
#include <stddef.h>
#ifdef _WIN32
#define TSUME_API extern "C" __declspec(dllexport)
#define TSUME_CALL __cdecl
#else
#define TSUME_API extern "C"
#define TSUME_CALL
#endif
// Each context owns its caches and error string. Do not share one context concurrently.
TSUME_API void* TSUME_CALL tsume_create();
TSUME_API void TSUME_CALL tsume_destroy(void* context);
// Cancel (on=1) / re-arm (on=0): makes every running operation stop at its next time check, as if it timed out.
TSUME_API void TSUME_CALL tsume_cancel(int on);
// Thread-safe cancellation for this context only; reset while idle before reuse.
TSUME_API void TSUME_CALL tsume_cancel_context(void* context, int on);
// Register only while this context is idle. Called on its search thread.
// nodes count all df-pn visits across attempts; seconds exclude PV construction.
// phase: 1=search, 2=PV construction, 0=finished. Do not reenter the context.
TSUME_API void TSUME_CALL tsume_set_progress(void* context,
    void (TSUME_CALL *callback)(unsigned long long nodes, double seconds, int phase));
// All searches: per-operation recursive visits (strict attacker/defender + df-pn).
// phase=1 intermediate, 0 final; zero-visit operations may emit no event.
// Register while idle, callback on search thread, no context reentry.
TSUME_API void TSUME_CALL tsume_set_search_progress(void* context,
    void (TSUME_CALL *callback)(unsigned long long nodes, double seconds, int phase));
// Optional: callback that answers whether a position (attacker to move) is mate under normal rules.
TSUME_API void TSUME_CALL tsume_set_oracle(void* context, int (TSUME_CALL *fn)(const char* sfen));
TSUME_API const char* TSUME_CALL tsume_error(void* context);
TSUME_API int TSUME_CALL tsume_copy_result(void* context, char* output, size_t capacity);
// Returns bytes required INCLUDING NUL, or -1 on error. A short buffer is untouched.
// Operations: checks, evasions, moves, can_mate, defenders, exact, solve, line,
// verify, unmove, dead, node, random, generate, clear. See README.md for arguments.
TSUME_API int TSUME_CALL tsume_run(void* context, const char* operation,
    const char* sfen, int n, int color, unsigned long long seed,
    int budget, double seconds, char* output, size_t capacity);
