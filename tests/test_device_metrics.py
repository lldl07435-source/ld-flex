import tempfile
import unittest
from pathlib import Path
from ldcell.hardware import HardwareSession
from tests.test_hardware import FakeSerial

class DeviceMetricTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.hw=HardwareSession('TEST',Path(self.temp.name),FakeSerial())
        self.hw.shutdown.set();self.hw.worker.join()

    def tearDown(self):
        self.hw.close();self.temp.cleanup()

    def test_telemetry_metrics_present(self):
        snapshot=self.hw.snapshot()
        self.assertIsNotNone(snapshot['feedback_age_ms'])
        self.assertGreaterEqual(snapshot['round_trip_ms'],0)
        self.assertEqual(snapshot['bad_frames'],0)
        self.assertFalse(snapshot['armed'])

    def test_device_cycle_clock_wrap(self):
        self.hw.current=dict(order_id='1',command_id=1,route=0,uptime_start=0xfffffff0)
        self.hw._observe(dict(job=1,state=6,uptime=0x20,fault=0))
        self.assertAlmostEqual(self.hw.results[0]['cycle_s'],.048)
        self.assertIsNone(self.hw.current)
