from datetime import datetime
from contextlib import contextmanager
from pathlib import Path
import csv
import hashlib
import json
import os
import sqlite3
import subprocess
import threading
import uuid
import zipfile

ROOT=Path(__file__).resolve().parents[1]

@contextmanager
def database(path):
    db=sqlite3.connect(path,timeout=10)
    try:
        with db: yield db
    finally:
        db.close()

def now_iso(): return datetime.now().astimezone().isoformat(timespec='milliseconds')
def canonical(value):
    def unique_object(pairs):
        result={}
        for key,item in pairs:
            if key in result:raise ValueError('JSON key collision: '+key)
            result[key]=item
        return result
    # JSON 会把数字键转成文本；先完成这种转换，再排序和算摘要。
    normalized=json.loads(json.dumps(value,ensure_ascii=False,allow_nan=False),object_pairs_hook=unique_object)
    return json.dumps(normalized,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)

def provenance():
    files={}
    for folder in ('core','ldcell','firmware','web'):
        for p in (ROOT/folder).rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts:
                files[p.relative_to(ROOT).as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
    for name in ('app.py','requirements-hardware.txt'):
        p=ROOT/name
        if p.exists(): files[name]=hashlib.sha256(p.read_bytes()).hexdigest()
    try:
        commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True,stderr=subprocess.DEVNULL).strip()
        dirty=subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True,stderr=subprocess.DEVNULL).strip()
    except (OSError,subprocess.CalledProcessError): commit,dirty=None,'unknown'
    return {'git_commit':commit,'git_dirty':bool(dirty),'source_sha256':files}

class RunLog:
    def __init__(self, data_root, config, mode='simulation'):
        self.root=Path(data_root); self.root.mkdir(parents=True,exist_ok=True)
        self.id=datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'_'+uuid.uuid4().hex[:6]
        self.folder=self.root/'runs'/self.id; self.folder.mkdir(parents=True)
        self.seq=0; self.previous='0'*64; self.finished=False; self.lock=threading.RLock()
        self.meta={'id':self.id,'started_at':now_iso(),'mode':mode,'config':config,**provenance()}
        self._write('meta.json',self.meta)
        with self._db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, started_at TEXT, mode TEXT, status TEXT, summary TEXT)')
            db.execute('INSERT INTO runs VALUES(?,?,?,?,?)',(self.id,self.meta['started_at'],mode,'running','{}'))
        self.event('created',config)

    def _db(self): return database(self.root/'runs.sqlite3')
    def _write(self,name,obj):
        (self.folder/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')

    def event(self,kind,data):
        with self.lock:
            if self.finished: raise RuntimeError('run already sealed')
            sequence=self.seq+1
            payload={'seq':sequence,'recorded_at':now_iso(),'kind':kind,'data':data,'previous':self.previous}
            digest=hashlib.sha256(canonical(payload).encode('utf-8')).hexdigest()
            row={**payload,'sha256':digest}
            with (self.folder/'events.jsonl').open('a',encoding='utf-8',newline='\n') as f:
                f.write(canonical(row)+'\n'); f.flush(); os.fsync(f.fileno())
            self.seq=sequence;self.previous=digest

    def finish(self,summary,rows=(),status='completed'):
        with self.lock:
            if self.finished: return
            self.event('finished',{'status':status,'summary':summary})
            result={**summary,'id':self.id,'status':status,'ended_at':now_iso(),'event_chain_head':self.previous}
            self._write('summary.json',result)
            if rows:
                with (self.folder/'jobs.csv').open('w',encoding='utf-8-sig',newline='') as f:
                    writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
            hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in self.folder.iterdir() if p.is_file()}
            self._write('manifest.json',hashes)
            with self._db() as db:
                db.execute('UPDATE runs SET status=?,summary=? WHERE id=?',(status,canonical(result),self.id))
            self.finished=True

def history(data_root,limit=100):
    path=Path(data_root)/'runs.sqlite3'
    if not path.exists(): return []
    with database(path) as db:
        rows=db.execute('SELECT id,started_at,mode,status,summary FROM runs ORDER BY started_at DESC LIMIT ?',(limit,)).fetchall()
    return [dict(id=r[0],started_at=r[1],mode=r[2],status=r[3],summary=json.loads(r[4])) for r in rows]

def run_folder(data_root,run_id):
    if not isinstance(run_id,str) or len(run_id)>80 or not all(c.isdigit() or c in '_abcdef' for c in run_id):
        raise ValueError('invalid run id')
    folder=Path(data_root)/'runs'/run_id
    if not folder.is_dir(): raise ValueError('run not found')
    return folder

def verify(folder):
    folder=Path(folder); issues=[]; previous='0'*64; count=0
    try:
        for line in (folder/'events.jsonl').read_text(encoding='utf-8').splitlines():
            row=json.loads(line); digest=row.pop('sha256'); count+=1
            if row['seq']!=count or row['previous']!=previous or hashlib.sha256(canonical(row).encode()).hexdigest()!=digest:
                issues.append(f'event {count} mismatch')
            previous=digest
        manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
        for name,digest in manifest.items():
            if Path(name).name!=name or not (folder/name).is_file() or hashlib.sha256((folder/name).read_bytes()).hexdigest()!=digest:
                issues.append(f'file mismatch: {name}')
        summary=json.loads((folder/'summary.json').read_text(encoding='utf-8'))
        if summary['event_chain_head']!=previous: issues.append('chain head mismatch')
    except (OSError,ValueError,KeyError,TypeError) as exc: issues.append(str(exc))
    return {'ok':not issues,'events':count,'issues':issues}

def export_run(folder,output):
    check=verify(folder)
    if not check['ok']: raise ValueError('record is incomplete or changed: '+str(check['issues']))
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
        for p in Path(folder).iterdir():
            if p.is_file(): z.write(p,p.name)

def recover_interrupted(data_root):
    # 只整理未封存会话的状态，不补造正常结束或丢失的传感器事件。
    path=Path(data_root)/'runs.sqlite3'
    if path.exists():
        with database(path) as db:
            db.execute("UPDATE runs SET status='interrupted' WHERE status='running'")
