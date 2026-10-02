"""Local serial session. Reconnecting never arms the physical cell."""
import secrets
import threading
import time
from .protocol import frame,response
from .kernel import STATES,FAULTS,RESULTS
from .storage import RunLog

def ports():
    try:
        from serial.tools.list_ports import comports
        return [{'port':p.device,'description':p.description,'bluetooth':'蓝牙' in p.description or 'bluetooth' in p.description.lower(),'usb':p.vid is not None} for p in comports()]
    except ImportError:
        return []

class HardwareSession:
    def __init__(self, port, data_root, transport=None):
        if transport is None:
            import serial
            available={p['port'] for p in ports()}
            if port not in available: raise ValueError('所选串口当前不存在')
            transport=serial.Serial(port,115200,timeout=.08,write_timeout=.2)
        self.serial=transport;self.lock=threading.RLock();self.seq=0;self.session=0;self.job=0
        self.connected=True;self.last=None;self.current=None;self.results=[];self.error='';self.shutdown=threading.Event();self.recovery_required=True
        self.log=RunLog(data_root,{'port':port,'baud':115200},mode='hardware')
        self.serial.reset_input_buffer()
        try: self._exchange(0)
        except Exception:
            self.serial.close();self.connected=False;self.log.finish({'error':'handshake failed'},status='failed');raise
        self.worker=threading.Thread(target=self._poll,daemon=True);self.worker.start()

    def _exchange(self,op,job=0,route=0):
        self.seq=(self.seq+1)&0xffffffff
        packet=frame(self.seq,op,self.session,job,route)
        self.log.event('serial_tx',{'hex':packet.hex(),'seq':self.seq,'op':op})
        self.serial.write(packet)
        deadline=time.monotonic()+.45
        raw_buffer=b''
        while time.monotonic()<deadline:
            raw=self.serial.read_until(b'\n',180)
            if not raw: continue
            raw_buffer+=raw
            if len(raw_buffer)>180: raw_buffer=b'';continue
            if not raw_buffer.endswith(b'\n'): continue
            raw,raw_buffer=raw_buffer,b''
            try: decoded=response(raw)
            except ValueError:
                self.log.event('bad_frame',{'hex':raw.hex()});continue
            self.log.event('serial_rx',decoded)
            if decoded['seq']!=self.seq: continue
            self.last=decoded
            if self.session and op!=1 and decoded['session']!=self.session:
                self._unknown('device session changed');self.session=0
                raise RuntimeError('设备会话变化，请检查物料后重新建立会话')
            self._observe(decoded)
            return decoded
        self._unknown('reply timeout')
        raise TimeoutError('串口应答超时，当前物料记为未知；检查后重新连接')

    def _unknown(self,reason):
        self.recovery_required=True
        if self.current:
            row={**self.current,'outcome':'unknown','reason':reason}
            self.results.append(row);self.log.event('job_result',row);self.current=None

    def _observe(self,s):
        if self.current and s['job']==self.current['command_id']:
            if s['state']==6:
                row={**self.current,'outcome':'completed','uptime_end':s['uptime']}
                self.results.append(row);self.log.event('job_result',row);self.current=None
            elif s['state'] in (0,7): self._unknown(FAULTS[s['fault']])

    def _poll(self):
        while not self.shutdown.wait(.12):
            with self.lock:
                if not self.connected: return
                try: self._exchange(3 if self.session else 0)
                except Exception as exc:
                    self.error=str(exc);self._close('interrupted');return

    def arm(self,confirmed=False):
        with self.lock:
            if not confirmed: raise ValueError('先核对物料并勾选清空确认')
            if self.current: raise ValueError('当前任务未确认，请先停止并核对')
            if not self.connected: raise ValueError('设备未连接')
            old=self.session;self.session=secrets.randbelow(0x7ffffffe)+1
            reply=self._exchange(1)
            if reply['result']!=0:
                self.session=old
                raise ValueError('复位被拒绝：按住本地确认按钮、释放急停、清空传感器后重试')
            self.job=0
            self.recovery_required=False

    def run_one(self,route,order_id):
        with self.lock:
            if type(route) is not int or route not in (0,1): raise ValueError('invalid route')
            if not isinstance(order_id,str) or not 1<=len(order_id.strip())<=40: raise ValueError('请输入1至40字物料编号')
            if not self.connected or not self.session or self.recovery_required: raise ValueError('请先核对物料并建立已确认的设备会话')
            if self.current or not self.last or self.last['state'] not in (1,6): raise ValueError('上一件尚未结束或设备处于故障')
            self.job+=1
            self.current={'order_id':order_id.strip(),'command_id':self.job,'route':route,'uptime_start':self.last['uptime']}
            self.log.event('submitted',self.current)
            reply=self._exchange(2,self.job,route)
            if reply['result'] not in (0,1):
                self.current=None;raise ValueError('启动被拒绝：'+RESULTS[reply['result']])

    def stop(self):
        with self.lock:
            if self.connected:
                try: self._exchange(4)
                finally: self._unknown('operator stop')

    def _close(self,status):
        self._unknown('connection closed');self.connected=False;self.shutdown.set()
        self.serial.close()
        self.log.finish({'mode':'hardware','completed':sum(r['outcome']=='completed' for r in self.results),
                         'unknown':sum(r['outcome']=='unknown' for r in self.results),'error':self.error},status=status)

    def close(self):
        with self.lock:
            if self.connected:
                try: self.stop()
                except Exception as exc: self.error=str(exc)
                self._close('stopped')

    def snapshot(self):
        with self.lock:
            s=dict(self.last) if self.last else {}
            if s: s.update(state_name=STATES[s['state']],fault_name=FAULTS[s['fault']])
            return {'connected':self.connected,'armed':bool(self.session) and not self.recovery_required,'device':s,'current':self.current,'results':self.results[-30:],'error':self.error,'run_id':self.log.id}
