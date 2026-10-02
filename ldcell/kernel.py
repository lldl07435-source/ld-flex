from pathlib import Path
import ctypes as ct
import hashlib
import json
import os

ROOT = Path(__file__).resolve().parents[1]
STATES = ('LOCKED', 'IDLE', 'ALIGN', 'RELEASE', 'TRANSIT', 'SETTLE', 'DONE', 'FAULT')
FAULTS = ('NONE', 'ESTOP', 'LINK_LOST', 'TIMEOUT', 'WRONG_EXIT', 'NO_ENTRY', 'EXTRA_ITEM', 'STOPPED')
RESULTS = ('OK', 'DUPLICATE', 'BUSY', 'BLOCKED', 'SESSION', 'STALE', 'CONFLICT', 'RANGE')

class Config(ct.Structure):
    _fields_ = [(key, ct.c_uint32) for key in ('align_ms', 'release_ms', 'travel_ms', 'settle_ms', 'heartbeat_ms')]

class Cell(ct.Structure):
    _fields_ = [(key, ct.c_uint32) for key in ('state', 'fault', 'job', 'route', 'entered', 'previous_inputs', 'since', 'heartbeat', 'releases', 'completed', 'session', 'clear_since')] + [('cfg', Config)]

class Command(ct.Structure):
    _fields_ = [(key, ct.c_uint32) for key in ('seq', 'op', 'session', 'job', 'route')]

_library = None

def check_library():
    path=ROOT/'build'/('ldcell.dll' if os.name=='nt' else 'libldcell.so')
    try:
        stamp=json.loads((ROOT/'build'/'source_stamp.json').read_text(encoding='utf-8'))
        source={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'core').glob('*')) if p.suffix in ('.c','.h')}
        if source!=stamp['source'] or hashlib.sha256(path.read_bytes()).hexdigest()!=stamp['library_sha256']:
            raise ValueError('stale build')
    except (OSError,ValueError,KeyError) as exc:
        raise RuntimeError('控制库缺失或与源码不一致，请关闭工作台后运行 python tools/build.py') from exc
    return path

def library():
    global _library
    if _library is None:
        path = check_library()
        lib = ct.CDLL(str(path))
        ptr = ct.POINTER(Cell)
        u = ct.c_uint32
        for name, args, result in [
            ('ld_init', [ptr], None), ('ld_reset', [ptr,u,u,u,u], ct.c_int),
            ('ld_start', [ptr,u,u,u,u,u], ct.c_int), ('ld_heartbeat', [ptr,u,u], ct.c_int),
            ('ld_stop', [ptr], None), ('ld_tick', [ptr,u,u,u], None),
            ('ld_gate_open', [ptr], u), ('ld_sizeof_cell', [], u),
            ('ld_crc', [ct.c_char_p,u], ct.c_uint16),
            ('ld_parse', [ct.c_char_p,ct.POINTER(Command)], ct.c_int),
            ('ld_dispatch', [ptr,ct.POINTER(Command),u,u,u], ct.c_int),
        ]:
            fn = getattr(lib, name); fn.argtypes = args; fn.restype = result
        if lib.ld_sizeof_cell() != ct.sizeof(Cell):
            raise RuntimeError('控制库与 Python 结构不一致，请重新构建')
        _library = lib
    return _library

class Core:
    def __init__(self):
        self.lib = library(); self.cell = Cell(); self.lib.ld_init(ct.byref(self.cell))

    def reset(self, session=1, now=0, inputs=0, estop=0):
        return self.lib.ld_reset(ct.byref(self.cell), session, now, inputs, estop)

    def start(self, job, route=0, now=0, inputs=0, session=1):
        return self.lib.ld_start(ct.byref(self.cell), session, job, route, now, inputs)

    def heartbeat(self, now, session=1):
        return self.lib.ld_heartbeat(ct.byref(self.cell), session, now)

    def tick(self, now, inputs=0, estop=0):
        self.lib.ld_tick(ct.byref(self.cell), now, inputs, estop)

    def stop(self): self.lib.ld_stop(ct.byref(self.cell))

    def snapshot(self):
        return {'state': STATES[self.cell.state], 'fault': FAULTS[self.cell.fault],
                'job': self.cell.job, 'route': self.cell.route, 'gate': bool(self.lib.ld_gate_open(ct.byref(self.cell))),
                'releases': self.cell.releases, 'completed': self.cell.completed, 'session': self.cell.session}
