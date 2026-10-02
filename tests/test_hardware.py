import ctypes as ct
from pathlib import Path
import tempfile
import unittest
from ldcell.hardware import HardwareSession
from ldcell.kernel import Core,Command,library
from ldcell.protocol import crc16
from ldcell.storage import verify

class FakeSerial:
    def __init__(self):self.core=Core();self.now=0;self.buffer=b'';self.drop=False;self.writes=0
    def reset_input_buffer(self):self.buffer=b''
    def close(self):pass
    def write(self,packet):
        self.writes+=1;cmd=Command();assert library().ld_parse(packet.strip(),ct.byref(cmd))
        result=library().ld_dispatch(ct.byref(self.core.cell),ct.byref(cmd),self.now,0,0)
        c=self.core.cell
        values=[cmd.seq,result,c.session,c.job,c.state,c.fault,c.route,0,c.releases,c.completed,self.now]
        body=','.join(map(str,values)).encode();self.buffer=b'@'+body+f'*{crc16(body):04X}\n'.encode()
    def read_until(self,*args):
        if self.drop:return b''
        result=self.buffer;self.buffer=b'';return result

class HardwareTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.serial=FakeSerial()
        self.hw=HardwareSession('TEST',Path(self.temp.name),self.serial)
        self.hw.shutdown.set();self.hw.worker.join()
    def tearDown(self):self.hw.close();self.temp.cleanup()

    def test_connect_never_arms(self):
        self.assertFalse(self.hw.snapshot()['armed'])
        self.assertEqual(self.serial.core.snapshot()['state'],'LOCKED')
        with self.assertRaises(ValueError):self.hw.run_one(0,'test')

    def test_requires_operator_confirmation(self):
        with self.assertRaises(ValueError):self.hw.arm(False)
        self.hw.arm(True);self.assertTrue(self.hw.snapshot()['armed'])

    def test_fault_result_is_unknown(self):
        self.hw.arm(True);self.hw.run_one(0,'sample');self.hw.stop()
        self.assertEqual(self.hw.results[0]['outcome'],'unknown')
        self.assertFalse(self.hw.snapshot()['armed'])

    def test_reply_loss_never_retries_motion(self):
        self.hw.arm(True);before=self.serial.writes;self.serial.drop=True
        with self.assertRaises(TimeoutError):self.hw.run_one(0,'sample')
        self.assertEqual(self.serial.writes,before+1)
        self.assertEqual(self.hw.results[0]['outcome'],'unknown')
        with self.assertRaises(ValueError):self.hw.run_one(1,'again')
        self.serial.drop=False

    def test_reboot_requires_reconciliation(self):
        self.hw.arm(True);self.hw.run_one(0,'sample');self.serial.core=Core()
        with self.assertRaises(RuntimeError):self.hw._exchange(3)
        self.assertFalse(self.hw.snapshot()['armed'])

    def test_hardware_record_seals(self):
        self.hw.close();self.assertTrue(verify(self.hw.log.folder)['ok'])

if __name__=='__main__':unittest.main()
