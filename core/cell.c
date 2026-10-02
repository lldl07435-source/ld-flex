#include "cell.h"
#include <string.h>

static int active(const LdCell *c) { return c->state >= LD_ALIGN && c->state <= LD_SETTLE; }
static void fail(LdCell *c, uint32_t why) { c->fault = why; c->state = LD_FAULT; }
static void enter(LdCell *c, uint32_t state, uint32_t now) { c->state = state; c->since = now; }

void ld_init(LdCell *c) {
    memset(c, 0, sizeof *c);
    c->cfg = (LdConfig){350, 180, 2500, 120, 700};
}

int ld_reset(LdCell *c, uint32_t session, uint32_t now, uint32_t inputs, uint32_t estop) {
    if (!session) return LD_RANGE;
    if (active(c)) return LD_BUSY;
    if (inputs || estop) return LD_BLOCKED;
    if (session != c->session) { c->job = 0; c->route = 0; }
    c->session = session;
    c->fault = 0; c->entered = 0; c->previous_inputs = 0;
    c->heartbeat = now; c->clear_since = now;
    enter(c, LD_IDLE, now);
    return LD_OK;
}

int ld_start(LdCell *c, uint32_t session, uint32_t job, uint32_t route, uint32_t now, uint32_t inputs) {
    if (!session || session != c->session) return LD_SESSION;
    if (!job || route > 1) return LD_RANGE;
    // 同号重发只确认已有任务，不能再开一次闸。
    if (job == c->job) return route == c->route ? LD_DUPLICATE : LD_CONFLICT;
    if (job < c->job) return LD_STALE;
    if (c->state != LD_IDLE && c->state != LD_DONE) return LD_BUSY;
    if (inputs || (uint32_t)(now - c->heartbeat) > c->cfg.heartbeat_ms) return LD_BLOCKED;
    c->job = job; c->route = route; c->entered = 0; c->previous_inputs = inputs;
    enter(c, LD_ALIGN, now);
    return LD_OK;
}

int ld_heartbeat(LdCell *c, uint32_t session, uint32_t now) {
    if (!session || session != c->session) return LD_SESSION;
    c->heartbeat = now;
    return LD_OK;
}

void ld_stop(LdCell *c) { fail(c, LD_STOPPED); }
uint32_t ld_gate_open(const LdCell *c) { return c->state == LD_RELEASE; }
uint32_t ld_sizeof_cell(void) { return (uint32_t)sizeof(LdCell); }

void ld_tick(LdCell *c, uint32_t now, uint32_t inputs, uint32_t estop) {
    uint32_t rising = inputs & ~c->previous_inputs;
    c->previous_inputs = inputs;
    if (estop) { fail(c, LD_ESTOP); return; }
    if (!active(c)) return;
    if ((uint32_t)(now - c->heartbeat) > c->cfg.heartbeat_ms) { fail(c, LD_LINK_LOST); return; }
    uint32_t expected = c->route ? LD_RIGHT : LD_LEFT;
    uint32_t wrong = c->route ? LD_LEFT : LD_RIGHT;
    if (inputs & wrong) { fail(c, LD_WRONG_EXIT); return; }
    if (c->state == LD_ALIGN) {
        if (inputs) { fail(c, LD_EXTRA_ITEM); return; }
        if ((uint32_t)(now - c->since) >= c->cfg.align_ms) {
            enter(c, LD_RELEASE, now); c->releases++;
        }
        return;
    }
    if (rising & LD_INLET) {
        if (c->entered || c->state == LD_SETTLE) { fail(c, LD_EXTRA_ITEM); return; }
        c->entered = 1;
    }
    if (c->state == LD_SETTLE) {
        if (rising & expected) { fail(c, LD_EXTRA_ITEM); return; }
        if (inputs) c->clear_since = now;
        if ((uint32_t)(now - c->clear_since) >= c->cfg.settle_ms) {
            c->completed++; enter(c, LD_DONE, now);
        } else if ((uint32_t)(now - c->since) > c->cfg.travel_ms) fail(c, LD_TIMEOUT);
        return;
    }
    if (rising & expected) {
        if (!c->entered) { fail(c, LD_NO_ENTRY); return; }
        // 出口刚触发还不算结束，先等光电信号稳定清空。
        enter(c, LD_SETTLE, now); c->clear_since = now;
        return;
    }
    if (c->state == LD_RELEASE && (uint32_t)(now - c->since) >= c->cfg.release_ms)
        enter(c, LD_TRANSIT, now);
    if (c->state == LD_TRANSIT && (uint32_t)(now - c->since) > c->cfg.travel_ms)
        fail(c, LD_TIMEOUT);
}
