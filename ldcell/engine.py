import threading
import time
import json
from pathlib import Path
from .simulation import Simulation
from .storage import RunLog,history,recover_interrupted
from .experiments import benchmark
from .hardware import HardwareSession
from .scheduling import POLICIES

class Engine:
    def __init__(self,data_root):
        self.data_root=data_root;recover_interrupted(data_root)
        self.lock=threading.RLock();self.sim=None;self.log=None;self.worker=None;self.hardware=None
        self.batch={'running':False};self.error=''
        for report_path in sorted((Path(data_root)/'benchmarks').glob('*/report.json'),reverse=True):
            try:
                report=json.loads(report_path.read_text(encoding='utf-8'))
                if not all(k in report for k in ('averages','paired_comparisons','runs','policies')):continue
                n=len(report['runs'])
                self.batch={'running':False,'done':n,'total':n,'loaded':True,'result':{'folder':str(report_path.parent),'report':report}}
                break
            except (OSError,ValueError):continue

    def start(self,seed=42,count=24,policy='BEAM',scenario='normal',speed=2):
        if speed not in (1,2,5,10): raise ValueError('invalid speed')
        with self.lock:
            if self.sim and self.sim.status=='running': raise ValueError('请先停止当前仿真')
            if self.hardware and self.hardware.connected: raise ValueError('先断开实物会话再启动仿真')
            sim=Simulation(seed,count,policy,scenario)
            log=RunLog(self.data_root,{'seed':seed,'count':count,'policy':policy,'scenario':scenario,'speed':speed})
            sim.events=log.event
            log.event('task_set',{'jobs':[j.__dict__ for j in sim.jobs],'service_ms':sim.travel})
            self.sim=sim;self.log=log;self.error=''
            self.worker=threading.Thread(target=self._run,args=(sim,log,speed),daemon=True);self.worker.start()

    def _run(self,sim,log,speed):
        try:
            while sim.status=='running':
                with self.lock:
                    for _ in range(speed): sim.step()
                time.sleep(.01)
            with self.lock: log.finish(sim.summary(),sim.rows,status=sim.status)
        except Exception as exc:
            with self.lock:
                self.error=str(exc);sim.stop();log.finish({'error':str(exc)},sim.rows,status='failed')

    def stop(self):
        with self.lock:
            if self.sim: self.sim.stop()

    def recover(self,confirmed):
        if not confirmed: raise ValueError('需要先确认已清空通道')
        with self.lock:
            if not self.sim: raise ValueError('尚无仿真')
            self.sim.recover()

    def start_batch(self,seeds=20,count=24):
        with self.lock:
            if self.batch.get('running'): raise ValueError('对照实验正在运行')
            if type(seeds) is not int or not 2<=seeds<=50 or type(count) is not int or not 4<=count<=80: raise ValueError('实验规模不合法')
            self.batch={'running':True,'done':0,'total':seeds*len(POLICIES)}
        def work():
            try:
                def progress(n,total):
                    with self.lock: self.batch.update(done=n,total=total)
                result=benchmark(self.data_root,seeds,count,progress)
                with self.lock: self.batch={'running':False,'done':seeds*len(POLICIES),'total':seeds*len(POLICIES),'result':result}
            except Exception as exc:
                with self.lock: self.batch={'running':False,'error':str(exc)}
        threading.Thread(target=work,daemon=True).start()

    def connect(self,port):
        with self.lock:
            if self.sim and self.sim.status=='running': raise ValueError('先停止仿真')
            if self.hardware and self.hardware.connected: raise ValueError('已经连接设备')
            self.hardware=HardwareSession(port,self.data_root)

    def snapshot(self):
        with self.lock:
            return {'simulation':self.sim.snapshot() if self.sim else None,'run_id':self.log.id if self.log else None,
                    'batch':self.batch,'hardware':self.hardware.snapshot() if self.hardware else None,'error':self.error}

    def close(self):
        self.stop()
        if self.worker: self.worker.join(timeout=5)
        if self.hardware: self.hardware.close()
