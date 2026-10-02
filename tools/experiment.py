from pathlib import Path
import argparse
import json
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ldcell.experiments import benchmark
from ldcell.simulation import Simulation,run_to_end,SCENARIOS
from ldcell.storage import RunLog,verify
from ldcell.locking import DataLock

ROOT=Path(__file__).resolve().parents[1]
def main():
    p=argparse.ArgumentParser();p.add_argument('--benchmark',action='store_true');p.add_argument('--seeds',type=int,default=20)
    p.add_argument('--count',type=int,default=24);p.add_argument('--seed',type=int,default=42);p.add_argument('--seed-start',type=int,default=20000);p.add_argument('--scenario',choices=SCENARIOS,default='normal');p.add_argument('--matrix',action='store_true');args=p.parse_args()
    if args.benchmark:
        result=benchmark(ROOT/'data',args.seeds,args.count,lambda n,total:print(f'{n}/{total}',flush=True),seed_start=args.seed_start)
        print(result['folder']);return
    for scenario in SCENARIOS if args.matrix else (args.scenario,):
        cfg={'count':args.count,'seed':args.seed,'policy':'BEAM','scenario':scenario,'recovery':'simulated_operator_after_2s'}
        log=RunLog(ROOT/'data',cfg)
        try:
            sim=Simulation(args.seed,args.count,scenario=scenario,event=log.event)
            result=run_to_end(sim);log.finish(result,sim.rows)
        except Exception as exc:log.finish({'error':str(exc)},status='failed');raise
        print(json.dumps({'run_id':log.id,'result':result,'check':verify(log.folder)},ensure_ascii=False),flush=True)
if __name__=='__main__':
    with DataLock(ROOT/'data'):main()
