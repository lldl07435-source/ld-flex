"""Small, inspectable dispatch policies for a single two-route cell."""
from dataclasses import dataclass, asdict
import math
import random

POLICIES = ('FIFO', 'EDD', 'GREEDY', 'BEAM')

@dataclass(frozen=True)
class Job:
    id: int
    route: int
    release: float
    due: float
    weight: int = 1
    processing: float = 1.05

    def __post_init__(self):
        if type(self.id) is not int or self.id < 1 or type(self.route) is not int or self.route not in (0,1):
            raise ValueError('job id / route invalid')
        if not all(math.isfinite(v) for v in (self.release,self.due,self.processing)) or self.release<0 or self.due<self.release or self.processing<=0 or not 1<=self.weight<=10:
            raise ValueError('job timing / weight invalid')

def make_jobs(seed=42, count=24):
    if type(seed) is not int or not 0<=seed<=2147483647 or type(count) is not int or not 1<=count<=200:
        raise ValueError('seed or count out of range')
    rng=random.Random(seed)
    jobs=[]
    for i in range(count):
        release=round(i*.38,3)
        jobs.append(Job(i+1,rng.randrange(2),release,round(release+rng.uniform(4,13),3),rng.choice((1,1,2,4))))
    return jobs

def choose(jobs, now, last_route, policy='BEAM', setup=.65, horizon=4, width=24):
    if policy not in POLICIES: raise ValueError('unknown policy')
    ready=[j for j in jobs if j.release<=now+1e-9]
    if not ready: return None
    if policy=='FIFO': return min(ready,key=lambda j:(j.release,j.id))
    if policy=='EDD': return min(ready,key=lambda j:(j.due,j.id))
    if policy=='GREEDY': horizon=1
    # 限定搜索规模，桌面和普通笔记本都能复算；没到站的任务不偷看。
    ready=sorted(ready,key=lambda j:(j.due,j.id))[:8]
    beam=[(0.0,now,last_route,tuple(),tuple(ready))]
    for _ in range(min(horizon,len(ready))):
        next_beam=[]
        for cost,t,route,sequence,remaining in beam:
            for j in remaining:
                switching=route is not None and route!=j.route
                finish=t+j.processing+(setup if switching else 0)
                penalty=j.weight*max(0,finish-j.due)+.15*(finish-now)+.8*switching
                next_beam.append((cost+penalty,finish,j.route,sequence+(j.id,),tuple(k for k in remaining if k.id!=j.id)))
        def rank(row):
            cost,t,route,sequence,remaining=row
            # 尚未排入窗口的工单也计入乐观下界，避免把高权重逾期单一直留在窗口外。
            lower_bound=sum(j.weight*max(0,t+j.processing-j.due)+.15*(t+j.processing-now) for j in remaining)
            return cost+lower_bound,sequence
        beam=sorted(next_beam,key=rank)[:width]
    selected=beam[0][3][0]
    return next(j for j in ready if j.id==selected)
