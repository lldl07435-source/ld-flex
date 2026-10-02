from datetime import datetime
from pathlib import Path
import csv
import html
import json
import random
import statistics
from .simulation import Simulation, run_to_end
from .scheduling import POLICIES
from .storage import RunLog, provenance

def paired_interval(differences, seed=9182, resamples=2000):
    if len(differences)<2: raise ValueError('at least two paired cases required')
    rng=random.Random(seed); n=len(differences)
    means=sorted(statistics.fmean(rng.choices(differences,k=n)) for _ in range(resamples))
    return [means[int(.025*resamples)],means[min(resamples-1,int(.975*resamples))]]

def benchmark(data_root,seeds=20,count=24,progress=None,seed_start=20000):
    if type(seeds) is not int or not 2<=seeds<=50: raise ValueError('seeds must be 2..50')
    if type(count) is not int or not 4<=count<=80: raise ValueError('count must be 4..80')
    if type(seed_start) is not int or not 0<=seed_start<=2147483597: raise ValueError('invalid starting seed')
    progress=progress or (lambda *args:None)
    folder=Path(data_root)/'benchmarks'/datetime.now().strftime('%Y%m%d_%H%M%S_%f');folder.mkdir(parents=True)
    rows=[]
    for index,seed in enumerate(range(seed_start,seed_start+seeds)):
        for policy in POLICIES:
            log=RunLog(data_root,{'seed':seed,'count':count,'policy':policy,'scenario':'normal','experiment':'fixed_baselines'})
            sim=Simulation(seed,count,policy,event=log.event)
            try:
                result=run_to_end(sim);log.finish(result,sim.rows)
            except Exception as exc:
                log.finish({'error':str(exc)},status='failed');raise
            rows.append({'seed':seed,'policy':policy,'run_id':log.id,**result})
            progress(len(rows),seeds*len(POLICIES))
    metrics=('weighted_tardiness','makespan_s','on_time_rate','switches')
    averages={p:{k:statistics.fmean(r[k] for r in rows if r['policy']==p) for k in metrics} for p in POLICIES}
    comparisons=[]
    for baseline in ('FIFO','EDD','GREEDY'):
        for metric in metrics:
            differences=[]
            for seed in range(seed_start,seed_start+seeds):
                case={r['policy']:r[metric] for r in rows if r['seed']==seed}
                differences.append(case['BEAM']-case[baseline])
            comparisons.append({'contrast':'BEAM - '+baseline,'metric':metric,'mean_difference':statistics.fmean(differences),
                                'ci95':paired_interval(differences),'n_paired':seeds})
    report={'created_at':datetime.now().astimezone().isoformat(),'mode':'simulation','seeds':list(range(seed_start,seed_start+seeds)),
            'count':count,'policies':list(POLICIES),'beam':{'horizon':4,'width':24,'candidates':8,'setup_s':.65},
            'averages':averages,'paired_comparisons':comparisons,'runs':rows,**provenance(),
            'limitations':'Synthetic tasks and estimated changeover cost. No hardware measurements. CI is across generated cases, not a factory-wide guarantee.'}
    (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    with (folder/'cases.csv').open('w',encoding='utf-8-sig',newline='') as f:
        fields=['seed','policy','run_id',*metrics,'completed','unknown'];w=csv.DictWriter(f,fields,extrasaction='ignore');w.writeheader();w.writerows(rows)
    table=''.join('<tr><td>'+p+'</td>'+''.join(f'<td>{averages[p][m]:.3f}</td>' for m in metrics)+'</tr>' for p in POLICIES)
    intervals=''.join(f"<tr><td>{html.escape(c['contrast'])}</td><td>{c['metric']}</td><td>{c['mean_difference']:.4f}</td><td>[{c['ci95'][0]:.4f}, {c['ci95'][1]:.4f}]</td></tr>" for c in comparisons)
    page=f'''<!doctype html><meta charset="utf-8"><title>LD-Flex 对照实验</title><style>body{{font:16px/1.7 system-ui;max-width:980px;margin:40px auto;color:#172b3a}}table{{border-collapse:collapse;width:100%;margin:20px 0}}td,th{{border:1px solid #ccd5df;padding:8px;text-align:left}}h1{{color:#0d6465}}small{{color:#596a77}}</style>
    <h1>LD-Flex · 调度对照实验</h1><p>记录时间：{report['created_at']} · {seeds} 组相同任务，每组 {count} 件，四种策略。</p>
    <p>数据类型：电脑仿真。控制状态机与固件共用 C 源码。换向准备时间为模型假设，等待实物标定。</p>
    <table><tr><th>策略</th><th>加权迟交 / 秒</th><th>完工时间 / 秒</th><th>准时率</th><th>换向次数</th></tr>{table}</table>
    <h2>配对差异与 95% bootstrap 区间</h2><p>同种子按物料绑定扰动；BEAM 减去基线。迟交、工期、换向越低越好，准时率越高越好。区间跨零时，本实验不足以判定方向稳定。共 12 项探索性比较，未做多重检验修正。GREEDY 使用同一代价和下界，仅搜索下一件，用于检查多步搜索的价值。</p>
    <table><tr><th>对照</th><th>指标</th><th>平均差</th><th>95% 区间</th></tr>{intervals}</table>
    <p>每次运行的参数、状态轨迹、事件链和任务 CSV 保存在 data/runs/，cases.csv 提供映射。没有自动挑选最有利的种子；未证明束搜索全局最优。</p><small>Git: {report['git_commit']} · 仿真结果不可填入实物实测栏。</small>'''
    (folder/'report.html').write_text(page,encoding='utf-8')
    return {'folder':str(folder),'report':report}
