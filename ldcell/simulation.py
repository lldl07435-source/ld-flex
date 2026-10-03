from dataclasses import asdict, replace
import math
import random
from .kernel import Core
from .scheduling import make_jobs, choose, POLICIES

SCENARIOS=('normal','jam','wrong_exit','missing_entry','double_feed','stuck_exit','link_loss','estop','reboot','duplicate')

class Simulation:
    def __init__(self, seed=42, count=24, policy='BEAM', scenario='normal', event=None, setup=.65, task_kind='belt', manual=False):
        if policy not in POLICIES or scenario not in SCENARIOS: raise ValueError('unknown policy / scenario')
        if not math.isfinite(setup) or not 0<=setup<=5: raise ValueError('setup out of range')
        if task_kind not in ('belt','color','size','weight','barcode','rework'): raise ValueError('unknown sorting task')
        self.task_kind=task_kind;self.manual_mode=bool(manual);self.manual_request=None
        self.attributes={}
        for job in make_jobs(seed,count):
            rng=random.Random(seed*811+job.id)
            width=rng.randint(20,80);mass=rng.randint(30,350);colour=rng.choice(('red','blue'));passed=rng.random()>.25
            destination=job.id%4 if task_kind=='barcode' else (int(colour=='blue') if task_kind=='color' else int(width>=50) if task_kind=='size' else int(mass>=180) if task_kind=='weight' else int(not passed) if task_kind=='rework' else job.route)
            self.attributes[job.id]={'color':colour,'size':'large' if width>=50 else 'small','width_mm':width,'mass_g':mass,'inspection_passed':passed,'destination':destination}
        self.jobs=[replace(j,route=(self.attributes[j.id]['destination']//2 if task_kind=='barcode' else self.attributes[j.id]['destination'])) for j in make_jobs(seed,count)]; self.waiting=list(self.jobs); self.policy=policy; self.scenario=scenario; self.setup=setup
        # 每个物料预先分配随机扰动，使不同策略看到同一组服务时间，不受出队次序影响。
        self.travel={j.id:random.Random(seed*1009+j.id).randint(330,600) for j in self.jobs}
        self.core=Core(); self.core.reset(); self.now=0; self.current=None; self.last_route=None
        self.rows=[]; self.seq=0; self.switches=0; self.events=event or (lambda *args:None)
        self.started=0; self.release_at=None; self.ready_at=0; self.last_snapshot=None
        self.status='running'; self.injected=False; self.recovery_started=None; self.recovery_delays=[]
        self.inputs=0; self.trace=[]; self.confirmed_releases=0; self.boot_epoch=1
        self.motion=[]; self.motion_pending=[]; self.motion_signature=None; self.motion_at=-50
        self.motion_progress=0.0; self.motion_route=0
        self.capture_motion(force=True)
        self.events('parameters',{'seed':seed,'scenario':scenario,'policy':policy,'setup_seconds':setup,'jobs':[asdict(j) for j in self.jobs]})

    def _record(self,outcome):
        j=self.current
        self.rows.append({'order_id':j.id,'command_id':self.seq,'route':j.route,'release':j.release,'due':j.due,'weight':j.weight,
                          'started':self.started/1000,'finished':self.now/1000,'outcome':outcome,
                          'tardiness':round(max(0,self.now/1000-j.due),6) if outcome=='completed' else '',
                          'fault':self.core.snapshot()['fault'],**self.attributes[j.id]})
        self.events('job_result',self.rows[-1]); self.current=None; self.release_at=None

    def step(self,dt=10):
        if self.status!='running': return self.snapshot()
        if dt!=10: raise ValueError('simulation step fixed at 10 ms')
        self.now+=dt
        if self.recovery_started is not None:
            self.capture_motion()
            return self.snapshot()
        if self.current is None:
            if not self.waiting:
                self.status='completed'; self.capture_motion(force=True); self.flush_motion()
                return self.snapshot()
            job=choose(self.waiting,self.now/1000,self.last_route,self.policy,self.setup)
            if self.manual_mode:
                if self.manual_request is None: job=None
                else:
                    original=self.waiting[0];destination=self.manual_request;self.manual_request=None
                    self.waiting.remove(original)
                    job=replace(original,route=destination//2 if self.task_kind=='barcode' else destination,release=0)
                    self.waiting.insert(0,job);self.attributes[job.id]['destination']=destination
            if job:
                self.waiting.remove(job);self.current=job;self.seq+=1;self.started=self.now
                switching=self.last_route is not None and self.last_route!=job.route
                self.switches+=int(switching);self.ready_at=self.now+int(self.setup*1000)*int(switching)
                self.last_route=job.route
                self.events('dispatch',{'virtual_ms':self.now,'order':asdict(job),'command_id':self.seq,'setup_until':self.ready_at})
        if self.current is None:
            self.capture_motion()
            return self.snapshot()
        special=self.scenario if self.seq==min(3,len(self.jobs)) and not self.injected else 'normal'
        elapsed=0 if self.release_at is None else self.now-self.release_at
        heartbeat=not (special=='link_loss' and self.release_at is not None and elapsed>=50)
        if heartbeat: self.core.heartbeat(self.now)
        if self.now>=self.ready_at and self.core.cell.job!=self.seq:
            result=self.core.start(self.seq,self.current.route,self.now)
            self.events('command',{'virtual_ms':self.now,'command_id':self.seq,'result':result})
            if result: raise RuntimeError(f'controller rejected dispatch: {result}')
        if special=='duplicate' and self.release_at is not None:
            result=self.core.start(self.seq,self.current.route,self.now)
            if result!=1: raise RuntimeError('duplicate accepted as new motion')
        inputs=0;stop=0
        if self.release_at is not None:
            if 40<=elapsed<110 and special!='missing_entry': inputs|=1
            if special=='double_feed' and 170<=elapsed<220: inputs|=1
            transit=self.travel[self.current.id]
            if special not in ('jam','link_loss','estop','reboot') and transit<=elapsed<transit+70:
                route=1-self.current.route if special=='wrong_exit' else self.current.route
                inputs|=4 if route else 2
            if special=='stuck_exit' and elapsed>=transit: inputs|=4 if self.current.route else 2
            if special=='estop' and elapsed>=80: stop=1
            if special=='reboot' and elapsed>=80:
                self.confirmed_releases+=self.core.cell.releases;self.core=Core();self.boot_epoch+=1
                self.events('device_reboot',{'virtual_ms':self.now,'disposition':'unknown'});self.injected=True
                self.capture_motion(force=True);self._record('unknown');self.recovery_started=self.now
                self.capture_motion(force=True);self.flush_motion();return self.snapshot()
        self.inputs=inputs
        self.core.tick(self.now,inputs,stop)
        snap=self.core.snapshot()
        if snap['state']=='RELEASE' and self.release_at is None: self.release_at=self.now
        if snap!=self.last_snapshot:
            self.events('state',{'virtual_ms':self.now,**snap,'inputs':inputs,'boot_epoch':self.boot_epoch})
            self.trace.append({'virtual_ms':self.now,**snap,'inputs':inputs});self.last_snapshot=snap
        self.capture_motion(special=special)
        if snap['state']=='FAULT':
            self.injected=True;self._record('unknown');self.recovery_started=self.now
        elif snap['state']=='DONE' and snap['job']==self.seq:
            self._record('completed')
        self.capture_motion()
        return self.snapshot()

    def capture_motion(self, force=False, special='normal'):
        snap=self.core.snapshot()
        signature=(snap['state'],self.inputs,self.current.id if self.current else None,self.status,self.recovery_started)
        if not force and signature==self.motion_signature and self.now-self.motion_at<50: return
        self.motion_at=self.now; self.motion_signature=signature
        if self.current and self.release_at is None:
            self.motion_progress=0.0; self.motion_route=self.current.route
        elif self.current and self.recovery_started is None and snap['state']!='FAULT':
            elapsed=max(0,self.now-self.release_at)
            self.motion_progress=min(1.0,elapsed/self.travel[self.current.id])
            if special in ('jam','link_loss','estop','reboot'): self.motion_progress=min(.64,self.motion_progress)
            self.motion_route=1-self.current.route if special=='wrong_exit' else self.current.route
        frame={'time_s':round(self.now/1000,3),'state':snap['state'],'fault':snap['fault'],
               'inputs':self.inputs,'route':snap['route'],'gate':snap['gate'],
               'order_id':self.current.id if self.current else None,'command_id':self.seq,
               'progress':self.motion_progress if self.current else None,'physical_route':self.motion_route,
               'awaiting_recovery':self.recovery_started is not None,'completed':snap['completed'],
               'releases':self.confirmed_releases+snap['releases'],
               'outlet_a':sum(r['outcome']=='completed' and r['route']==0 for r in self.rows),
               'outlet_b':sum(r['outcome']=='completed' and r['route']==1 for r in self.rows),
               'destination':self.attributes.get(self.current.id,{}).get('destination',0) if self.current else 0,
               'physical_destination':(self.attributes.get(self.current.id,{}).get('destination',0)^(2 if self.task_kind=='barcode' else 1)) if self.current and special=='wrong_exit' else (self.attributes.get(self.current.id,{}).get('destination',0) if self.current else 0),
               'color':self.attributes.get(self.current.id,{}).get('color','') if self.current else '',
               'size':self.attributes.get(self.current.id,{}).get('size','') if self.current else '',
               'bin_counts':[sum(r['outcome']=='completed' and r['destination']==i for r in self.rows) for i in range(4)],
               'unknown':sum(r['outcome']=='unknown' for r in self.rows),'boot_epoch':self.boot_epoch}
        # 同时刻的控制完成与物料归档都保留，回放取该时刻最后一帧。
        self.motion.append(frame);self.motion_pending.append(frame)
        if len(self.motion_pending)>=100: self.flush_motion()

    def manual_feed(self, destination):
        if not self.manual_mode: raise ValueError('当前不是手控仿真')
        if type(destination) is not int or not 0<=destination<(4 if self.task_kind=='barcode' else 2): raise ValueError('出口编号无效')
        if self.status!='running' or self.current or self.manual_request is not None or self.recovery_started is not None: raise RuntimeError('先等待本件完成，故障时请核对并恢复')
        if not self.waiting: raise RuntimeError('当前物料已全部完成')
        self.manual_request=destination
        self.events('manual_feed',{'virtual_ms':self.now,'destination':destination})

    def flush_motion(self):
        if self.motion_pending:
            self.events('motion_batch',{'schema':'ld-twin/1','units':'normalized_path','frames':self.motion_pending[:]})
            self.motion_pending.clear()

    def recover(self):
        if self.recovery_started is None: raise ValueError('no fault awaiting confirmation')
        # 仿真中的这一步明确代表操作者清空滑槽，实物端必须亲手核对。
        delay=(self.now-self.recovery_started)/1000;self.recovery_delays.append(delay)
        self.events('operator_clear',{'virtual_ms':self.now,'simulated':True,'wait_seconds':delay})
        if self.core.reset(now=self.now): raise RuntimeError('reset rejected')
        self.recovery_started=None;self.inputs=0
        self.capture_motion(force=True)

    def stop(self):
        if self.status!='running': return
        self.core.stop()
        if self.current: self._record('unknown')
        self.status='stopped';self.events('operator_stop',{'virtual_ms':self.now})
        self.capture_motion(force=True);self.flush_motion()

    def summary(self):
        completed=[r for r in self.rows if r['outcome']=='completed']
        return {'mode':'simulation','control_mode':'manual' if self.manual_mode else 'automatic','task_kind':self.task_kind,'policy':self.policy,'scenario':self.scenario,'total':len(self.jobs),'completed':len(completed),
               'unknown':sum(r['outcome']=='unknown' for r in self.rows),'unstarted':len(self.waiting),
                'makespan_s':round(self.now/1000,3),'weighted_tardiness':round(sum(r['weight']*r['tardiness'] for r in completed),6),
                'on_time_rate':sum(r['tardiness']==0 for r in completed)/len(completed) if completed else 0,
                'switches':self.switches,'releases':self.confirmed_releases+self.core.cell.releases,
                'recovery_wait_s':self.recovery_delays,'status':self.status}

    def snapshot(self):
        return {'virtual_s':round(self.now/1000,2),'status':self.status,'controller':self.core.snapshot(),'inputs':self.inputs,
                'awaiting_recovery':self.recovery_started is not None,'current':asdict(self.current) if self.current else None,
                'waiting':[asdict(j) for j in self.waiting[:24]],'results':self.rows[-30:],'summary':self.summary(),'trace':self.trace[-40:]}

def run_to_end(sim, recovery_ms=2000):
    for _ in range(200000):
        sim.step()
        if sim.recovery_started is not None and sim.now-sim.recovery_started>=recovery_ms: sim.recover()
        if sim.status!='running': return sim.summary()
    raise RuntimeError('simulation did not converge')
