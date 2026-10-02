"""Run acceptance checks, commit reviewed local changes, and retain a checkpoint."""
from pathlib import Path
from datetime import datetime
import json
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
def main():
    if len(sys.argv)!=2 or not sys.argv[1].strip():raise SystemExit('用法：python tools/checkpoint.py "本阶段实际完成的工作"')
    subprocess.run([sys.executable,'tools/verify.py'],cwd=ROOT,check=True)
    status=subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True)
    if not status.strip():print('源码没有变化，本次验收记录已保存，无需创建空提交。');return
    subprocess.run(['git','add','--all'],cwd=ROOT,check=True)
    subprocess.run(['git','commit','-m',sys.argv[1]],cwd=ROOT,check=True)
    rev=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    folder=ROOT/'evidence'/'stages';folder.mkdir(parents=True,exist_ok=True)
    record={'recorded_at':datetime.now().astimezone().isoformat(),'commit':rev,'message':sys.argv[1],'verification':'see latest evidence/*_verification/result.json'}
    (folder/(datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'_checkpoint.json')).write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    print('已提交：'+rev)
if __name__=='__main__':main()
