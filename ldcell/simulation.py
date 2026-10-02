from dataclasses import asdict
import math
import random
from .kernel import Core
from .scheduling import make_jobs, choose, POLICIES

SCENARIOS=('normal','jam','wrong_exit','missing_entry','double_feed','stuck_exit','link_loss','estop','reboot','duplicate')

class Simulation:
    def __init__(self, seed=42, count=24, policy='BEAM', scenario='normal', event=None, setup=.65):
        if policy not in POLICIES or scenario not in SCENARIOS: raise ValueError('unknown policy / scenario')
        if not math.isfinite(setup) or not 0<=setup<=5: raise ValueError('setup out of range')
        self.jobs=make_jobs(seed,count); self.waiting=list(self.jobs); self.policy=policy; self.scenario=scenario; self.setup=setup
        # 每个物料预先分配随机扰动，使不同策略看到同一组服务时间，不受出队次序影响。
        self.travel={j.id:random.Random(seed*1009+j.id).randint(330,600) for j in self.jobs}
        self.core=Core(); self.core.reset(); self.now=0; self.current=None; self.last_route=None
        self.rows=[]; self.seq=0; self.switches=0; self.events=event or (lambda *args:None)
        self.started=0; self.release_at=None; self.ready_at=0; self.last_snapshot=None
        self.status='running'; self.injected=False; self.recovery_started=None; self.recovery_delays=[]
        self.inputs=0; self.trace=[]; self.confirmed_releases=0; self.boot_epoch=1
        self.events('parameters',{'seed':seed,'scenario':scenario,'policy':policy,'setup_seconds':setup,'jobs':[asdict(j) for j in self.jobs]})

    def _record(self,outcome):
        j=self.current
        self.rows.append({'order_id':j.id,'command_id':self.seq,'route':j.route,'release':j.release,'due':j.due,'weight':j.weight,
                          'started':self.started/1000,'finished':self.now/1000,'outcome':outcome,
                          'tardiness':round(max(0,self.now/1000-j.due),6) if outcome=='completed' else '',
                          'fault':self.core.snapshot()['fault']})
        self.events('job_result',self.rows[-1]); self.current=None; self.release_at=None

    def step(self,dt=10):
        if self.status!='running': return self.snapshot()
        if dt!=10: raise ValueError('simulation step fixed at 10 ms')
        self.now+=dt
        if self.recovery_started is not None: return self.snapshot()
        if self.current is None:
            if not self.waiting: self.status='completed'; return self.snapshot()
            job=choose(self.waiting,self.now/1000,self.last_route,self.policy,self.setup)
            if job:
                self.waiting.remove(job);self.current=job;self.seq+=1;self.started=self.now
                switching=self.last_route is not None and self.last_route!=job.route
                self.switches+=int(switching);self.ready_at=self.now+int(self.setup*1000)*int(switching)
                self.last_route=job.route
                self.events('dispatch',{'virtual_ms':self.now,'order':asdict(job),'command_id':self.seq,'setup_until':self.ready_at})
        if self.current is None: return self.snapshot()
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
                self._record('unknown');self.recovery_started=self.now;return self.snapshot()
        self.inputs=inputs
        self.core.tick(self.now,inputs,stop)
        snap=self.core.snapshot()
        if snap['state']=='RELEASE' and self.release_at is None: self.release_at=self.now
        if snap!=self.last_snapshot:
            self.events('state',{'virtual_ms':self.now,**snap,'inputs':inputs,'boot_epoch':self.boot_epoch})
            self.trace.append({'virtual_ms':self.now,**snap,'inputs':inputs});self.last_snapshot=snap
        if snap['state']=='FAULT':
            self.injected=True;self._record('unknown');self.recovery_started=self.now
        elif snap['state']=='DONE' and snap['job']==self.seq:
            self._record('completed')
        return self.snapshot()

    def recover(self):
        if self.recovery_started is None: raise ValueError('no fault awaiting confirmation')
        # 仿真中的这一步明确代表操作者清空滑槽，实物端必须亲手核对。
        delay=(self.now-self.recovery_started)/1000;self.recovery_delays.append(delay)
        self.events('operator_clear',{'virtual_ms':self.now,'simulated':True,'wait_seconds':delay})
        if self.core.reset(now=self.now): raise RuntimeError('reset rejected')
        self.recovery_started=None;self.inputs=0

    def stop(self):
        if self.status!='running': return
        self.core.stop()
        if self.current: self._record('unknown')
        self.status='stopped';self.events('operator_stop',{'virtual_ms':self.now})

    def summary(self):
        completed=[r for r in self.rows if r['outcome']=='completed']
        return {'mode':'simulation','policy':self.policy,'scenario':self.scenario,'total':len(self.jobs),'completed':len(completed),
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
