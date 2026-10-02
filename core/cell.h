#ifndef LD_CELL_H
#define LD_CELL_H
#include <stdint.h>
#if defined(_WIN32) && defined(LD_SHARED)
#define LD_API __declspec(dllexport)
#else
#define LD_API
#endif

enum { LD_LOCKED, LD_IDLE, LD_ALIGN, LD_RELEASE, LD_TRANSIT, LD_SETTLE, LD_DONE, LD_FAULT };
enum { LD_OK, LD_DUPLICATE, LD_BUSY, LD_BLOCKED, LD_SESSION, LD_STALE, LD_CONFLICT, LD_RANGE };
enum { LD_NO_FAULT, LD_ESTOP, LD_LINK_LOST, LD_TIMEOUT, LD_WRONG_EXIT, LD_NO_ENTRY, LD_EXTRA_ITEM, LD_STOPPED };
enum { LD_INLET = 1, LD_LEFT = 2, LD_RIGHT = 4 };

typedef struct {
    uint32_t align_ms, release_ms, travel_ms, settle_ms, heartbeat_ms;
} LdConfig;

typedef struct {
    uint32_t state, fault, job, route, entered, previous_inputs;
    uint32_t since, heartbeat, releases, completed, session, clear_since;
    LdConfig cfg;
} LdCell;

LD_API void ld_init(LdCell *c);
LD_API int ld_reset(LdCell *c, uint32_t session, uint32_t now, uint32_t inputs, uint32_t estop);
LD_API int ld_start(LdCell *c, uint32_t session, uint32_t job, uint32_t route, uint32_t now, uint32_t inputs);
LD_API int ld_heartbeat(LdCell *c, uint32_t session, uint32_t now);
LD_API void ld_stop(LdCell *c);
LD_API void ld_tick(LdCell *c, uint32_t now, uint32_t inputs, uint32_t estop);
LD_API uint32_t ld_gate_open(const LdCell *c);
LD_API uint32_t ld_sizeof_cell(void);
#endif
