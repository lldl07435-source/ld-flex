from pathlib import Path
from datetime import datetime
import argparse
import hashlib
import json
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

def run(arm=False):
    folder = ROOT / 'evidence' / (datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '_verification')
    folder.mkdir(parents=True)
    commands = [[sys.executable, 'tools/build.py'], [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'], [sys.executable, 'manage.py', 'test', 'portal']]
    if arm: commands.append([sys.executable, 'tools/build.py', '--arm'])
    results = []
    for index, command in enumerate(commands, 1):
        process = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace', env={**os.environ, 'PYTHONIOENCODING':'utf-8'})
        output = process.stdout + process.stderr
        (folder / f'{index:02d}.log').write_text(output, encoding='utf-8')
        print(output)
        results.append({'command':command[1:], 'returncode':process.returncode})
    hashes = {str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest()
              for part in ('core','ldcell','portal','tests','firmware','tools','web') for p in (ROOT/part).rglob('*')
              if p.is_file() and '__pycache__' not in p.parts}
    for name in ('app.py','workspace_adapter.py','manage.py','requirements.txt','requirements-hardware.txt'):
        p=ROOT/name
        if p.exists():hashes[name]=hashlib.sha256(p.read_bytes()).hexdigest()
    binaries={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'build').glob('*') if p.suffix in ('.dll','.so','.bin','.elf')}
    try:
        rev = subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
        dirty = subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip()
    except (OSError, subprocess.CalledProcessError): rev,dirty = None,'unavailable'
    info = {'recorded_at':datetime.now().astimezone().isoformat(),'git_commit':rev,'git_status':dirty,
            'results':results, 'all_passed':all(x['returncode']==0 for x in results), 'source_sha256':hashes, 'binary_sha256':binaries}
    (folder/'result.json').write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Verification saved:',folder)
    return 0 if info['all_passed'] else 1

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--arm',action='store_true')
    sys.exit(run(parser.parse_args().arm))
