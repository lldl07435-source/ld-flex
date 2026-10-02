#ifndef LD_WIRE_H
#define LD_WIRE_H
#include "cell.h"
/* Frame: @sequence,OP,session,job,route*CRC16\n; all fields are unsigned decimals. */
typedef struct { uint32_t seq, op, session, job, route; } LdCommand;
enum { LD_HELLO, LD_ARM, LD_RUN, LD_HEARTBEAT, LD_STOP };
LD_API uint16_t ld_crc(const char *data, uint32_t length);
LD_API int ld_parse(const char *line, LdCommand *out);
LD_API int ld_dispatch(LdCell *cell, const LdCommand *cmd, uint32_t now, uint32_t inputs, uint32_t estop);
#endif
