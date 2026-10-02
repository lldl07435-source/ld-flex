import re

def crc16(data):
    crc = 0xffff
    for byte in data:
        crc ^= byte
        for _ in range(8): crc = (crc >> 1) ^ (0xa001 if crc & 1 else 0)
    return crc

def frame(seq, op, session=0, job=0, route=0):
    values = (seq, op, session, job, route)
    if any(type(v) is not int or not 0 <= v <= 0xffffffff for v in values) or op > 4 or route > 1:
        raise ValueError('invalid command fields')
    body = ','.join(map(str, values)).encode('ascii')
    return b'@' + body + f'*{crc16(body):04X}\n'.encode('ascii')

def response(raw):
    if len(raw) > 180: raise ValueError('response too long')
    m = re.fullmatch(rb'@([0-9,]+)\*([0-9A-Fa-f]{4})\r?\n', raw)
    if not m or crc16(m[1]) != int(m[2], 16): raise ValueError('bad response CRC or format')
    fields = [int(x) for x in m[1].split(b',')]
    if len(fields) != 11 or any(x > 0xffffffff for x in fields): raise ValueError('bad response shape')
    # seq, result, session, job, state, fault, route, sensors, releases, completed, uptime
    keys = ('seq','result','session','job','state','fault','route','inputs','releases','completed','uptime')
    result = dict(zip(keys, fields))
    if result['state'] > 7 or result['fault'] > 7 or result['route'] > 1 or result['inputs'] > 7 or result['result'] > 7:
        raise ValueError('response fields out of range')
    return result
