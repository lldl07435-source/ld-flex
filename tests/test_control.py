import ctypes as ct
import random
import unittest
from ldcell.kernel import Core, Command, library
from ldcell.protocol import frame, crc16, response

class ControlTests(unittest.TestCase):
    def setUp(self):
        self.c = Core()
        self.assertEqual(self.c.reset(), 0)

    def tick(self, ms, inputs=0, heartbeat=True, estop=0):
        if heartbeat: self.c.heartbeat(ms)
        self.c.tick(ms, inputs, estop)

    def complete(self, route=0):
        self.assertEqual(self.c.start(1, route), 0)
        self.tick(350); self.tick(380, 1); self.tick(420)
        self.tick(530); self.tick(750, 4 if route else 2)
        self.tick(790); self.tick(920)

    def test_boot_requires_reset(self):
        fresh = Core()
        self.assertEqual(fresh.snapshot()['state'], 'LOCKED')
        self.assertEqual(fresh.start(1), 4)

    def test_both_routes_complete(self):
        for route in (0, 1):
            with self.subTest(route=route):
                self.setUp(); self.complete(route)
                self.assertEqual(self.c.snapshot()['state'], 'DONE')
                self.assertEqual(self.c.cell.completed, 1)

    def test_duplicate_does_not_open_again(self):
        self.complete()
        for _ in range(100): self.assertEqual(self.c.start(1, now=950), 1)
        self.assertEqual(self.c.cell.releases, 1)

    def test_duplicate_route_conflict(self):
        self.c.start(1)
        self.assertEqual(self.c.start(1, 1), 6)

    def test_stale_task_rejected(self):
        self.c.start(7)
        self.assertEqual(self.c.start(6), 5)

    def test_unknown_session_rejected(self):
        self.assertEqual(self.c.start(1, session=2), 4)
        self.assertEqual(self.c.heartbeat(1000, 2), 4)

    def test_reset_preserves_same_session_dedup(self):
        self.complete(); self.assertEqual(self.c.reset(now=950), 0)
        self.assertEqual(self.c.start(1, now=950), 1)

    def test_new_session_rejects_old_packets(self):
        self.c.reset(session=37)
        self.assertEqual(self.c.start(1), 4)
        self.assertEqual(self.c.start(1, session=37), 0)

    def test_no_reset_during_motion(self):
        self.c.start(1)
        self.assertEqual(self.c.reset(), 2)

    def test_blocked_sensors_and_stop(self):
        for inputs in range(1, 8):
            self.assertEqual(self.c.reset(inputs=inputs), 3)
            self.assertEqual(self.c.start(1, inputs=inputs), 3)
        self.assertEqual(self.c.reset(estop=1), 3)

    def test_range_checks(self):
        self.assertEqual(self.c.reset(session=0), 7)
        self.assertEqual(self.c.start(0), 7)
        self.assertEqual(self.c.start(1, 2), 7)

    def test_wrong_exit_latched(self):
        self.c.start(1); self.tick(350); self.tick(380,1); self.tick(450,4)
        self.assertEqual(self.c.snapshot()['fault'], 'WRONG_EXIT')
        self.tick(900)
        self.assertFalse(self.c.snapshot()['gate'])
        self.assertEqual(self.c.start(2, now=900), 2)

    def test_exit_without_entry(self):
        self.c.start(1); self.tick(350); self.tick(420,2)
        self.assertEqual(self.c.snapshot()['fault'], 'NO_ENTRY')

    def test_double_feed(self):
        self.c.start(1); self.tick(350); self.tick(380,1); self.tick(420); self.tick(450,1)
        self.assertEqual(self.c.snapshot()['fault'], 'EXTRA_ITEM')

    def test_early_item(self):
        self.c.start(1); self.tick(100,1)
        self.assertEqual(self.c.snapshot()['fault'], 'EXTRA_ITEM')

    def test_timeout_without_exit(self):
        self.c.start(1); self.tick(350); self.tick(380,1); self.tick(550); self.tick(3060)
        self.assertEqual(self.c.snapshot()['fault'], 'TIMEOUT')

    def test_stuck_exit_not_counted(self):
        self.c.start(1); self.tick(350); self.tick(380,1); self.tick(550,2); self.tick(3200,2)
        self.assertEqual(self.c.snapshot()['fault'], 'TIMEOUT')
        self.assertEqual(self.c.cell.completed, 0)

    def test_heartbeat_loss_and_stale_start(self):
        self.assertEqual(self.c.start(1, now=701), 3)
        self.c.start(1); self.tick(350); self.tick(1051, heartbeat=False)
        self.assertEqual(self.c.snapshot()['fault'], 'LINK_LOST')

    def test_stop_at_every_active_phase(self):
        for phase in range(2, 6):
            self.c.cell.state = phase
            self.c.tick(20, estop=1)
            self.assertEqual(self.c.snapshot()['fault'], 'ESTOP')
            self.assertFalse(self.c.snapshot()['gate'])

    def test_software_stop(self):
        self.c.start(1); self.tick(350); self.c.stop()
        self.assertEqual(self.c.snapshot()['fault'], 'STOPPED')
        self.assertFalse(self.c.snapshot()['gate'])

    def test_clock_wrap(self):
        start = 0xffffff00
        self.c.reset(now=start); self.c.start(1, now=start)
        self.c.heartbeat((start+350) & 0xffffffff)
        self.c.tick((start+350) & 0xffffffff)
        self.assertEqual(self.c.snapshot()['state'], 'RELEASE')

    def test_random_fault_traces_invariants(self):
        rng = random.Random(10929)
        for _ in range(200):
            self.c = Core(); self.c.reset(); self.c.start(1)
            for t in range(0, 4000, 10):
                self.tick(t, rng.randrange(8), estop=int(rng.random()<.01))
                s = self.c.snapshot()
                self.assertLessEqual(s['completed'], s['releases'])
                self.assertLessEqual(s['releases'], 1)
                if s['state'] in ('FAULT','LOCKED','DONE'): self.assertFalse(s['gate'])

class ProtocolTests(unittest.TestCase):
    def parse(self, packet):
        out = Command()
        return library().ld_parse(packet.rstrip(b'\r\n'), ct.byref(out)), out

    def test_known_crc(self):
        self.assertEqual(crc16(b'123456789'), 0x4b37)
        self.assertEqual(library().ld_crc(b'123456789',9), 0x4b37)

    def test_python_c_roundtrip(self):
        for seq in (0,1,65536,0xffffffff):
            ok, out = self.parse(frame(seq,2,37,101,1))
            self.assertEqual(ok,1); self.assertEqual(out.seq,seq); self.assertEqual(out.job,101)

    def test_corrupt_each_byte(self):
        original = frame(7,2,11,19,0).strip()
        for i in range(len(original)):
            changed = bytearray(original); changed[i] ^= 1
            self.assertEqual(self.parse(bytes(changed))[0], 0)

    def test_valid_crc_invalid_fields(self):
        for body in (b'1,9,1,1,0',b'1,2,1,4294967296,0',b'1,2,1,-1,0',b'1,2,1,1,2',b'1,2,1,1,0,0'):
            packet = b'@'+body+f'*{crc16(body):04X}'.encode()
            self.assertEqual(self.parse(packet)[0],0)

    def test_dispatch_respects_stop(self):
        c = Core(); c.reset()
        ok, cmd = self.parse(frame(1,2,1,1,0))
        result = library().ld_dispatch(ct.byref(c.cell),ct.byref(cmd),0,0,1)
        self.assertEqual(result,3)

    def test_response_range_and_crc(self):
        body = b'2,0,1,9,6,0,1,0,1,1,4500'
        decoded = response(b'@'+body+f'*{crc16(body):04X}\n'.encode())
        self.assertEqual(decoded['completed'],1)
        with self.assertRaises(ValueError): response(b'@1,2*FFFF\n')

if __name__ == '__main__': unittest.main()
