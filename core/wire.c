#include "wire.h"
#include <string.h>

uint16_t ld_crc(const char *data, uint32_t length) {
    uint16_t crc = 0xffff;
    for (uint32_t i = 0; i < length; i++) {
        crc ^= (unsigned char)data[i];
        for (unsigned j = 0; j < 8; j++) crc = (crc >> 1) ^ ((crc & 1) ? 0xa001 : 0);
    }
    return crc;
}
static int digit(char c) { return c >= '0' && c <= '9'; }
static int number(const char **cursor, uint32_t *out) {
    const char *p = *cursor;
    uint32_t n = 0;
    if (!digit(*p)) return 0;
    while (digit(*p)) {
        uint32_t d = (uint32_t)(*p++ - '0');
        if (n > (UINT32_MAX - d) / 10) return 0;
        n = n * 10 + d;
    }
    *out = n; *cursor = p;
    return 1;
}
static int hex(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    return -1;
}
int ld_parse(const char *line, LdCommand *out) {
    size_t len = strlen(line);
    if (len < 15 || len > 100 || line[0] != '@') return 0;
    const char *star = strchr(line, '*');
    if (!star || strlen(star + 1) != 4) return 0;
    unsigned check = 0;
    for (unsigned i = 1; i <= 4; i++) { int d = hex(star[i]); if (d < 0) return 0; check = check * 16 + (unsigned)d; }
    if (ld_crc(line + 1, (uint32_t)(star - line - 1)) != check) return 0;
    uint32_t fields[5]; const char *p = line + 1;
    for (unsigned i = 0; i < 5; i++) {
        if (!number(&p, &fields[i])) return 0;
        if (i < 4 && *p++ != ',') return 0;
    }
    if (p != star || fields[1] > LD_STOP || fields[4] > 1) return 0;
    *out = (LdCommand){fields[0], fields[1], fields[2], fields[3], fields[4]};
    return 1;
}
int ld_dispatch(LdCell *c, const LdCommand *cmd, uint32_t now, uint32_t inputs, uint32_t estop) {
    switch (cmd->op) {
    case LD_HELLO: return LD_OK;
    case LD_ARM: return ld_reset(c, cmd->session, now, inputs, estop);
    case LD_RUN:
        if (estop) return LD_BLOCKED;
        return ld_start(c, cmd->session, cmd->job, cmd->route, now, inputs);
    case LD_HEARTBEAT: return ld_heartbeat(c, cmd->session, now);
    case LD_STOP: ld_stop(c); return LD_OK;
    default: return LD_RANGE;
    }
}
