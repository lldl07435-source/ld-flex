import io
import json
import threading
from pathlib import Path
from django.conf import settings
from django.http import HttpResponse
from django.middleware.csrf import get_token
from ldcell.engine import Engine
from ldcell.storage import history, run_folder, verify, export_run, database
from ldcell.hardware import ports

ROOT = Path(__file__).resolve().parent
DEFAULT_DATA_ROOT = ROOT / 'data'
WEB_ROOT = ROOT / 'web'
VERSION = '1.3.0'
DEFAULT_PORT = 8876
COOKIE_NAME = 'ldflex_session'
TITLE = 'LD-Flex 可恢复分拣实验平台'
STATIC_FILES = {'studio.html', 'studio.css', 'studio.js', 'lucide.js', 'lab.html', 'lab.css', 'lab.js', 'index.html', 'app.js', 'style.css'}
LEGACY_NAMES = ('runs.sqlite3', 'runs', 'benchmarks', '运行日志.log')
_hardware_lock = threading.RLock()
_hardware_owner = None
_hardware_device = None
_dispatch_lock = threading.RLock()

def health():
    from ldcell.kernel import check_library
    check_library()

def has_business_data(ctx):
    return bool(list((ctx.root / 'runs').glob('*')) or list((ctx.root / 'benchmarks').glob('*')))

class Context:
    def __init__(self, root):
        self.root = root
        self.engine = Engine(root)
    def close(self):
        self.engine.close()
    def busy(self):
        s = self.engine.snapshot()
        return bool((self.engine.worker and self.engine.worker.is_alive()) or s['batch'].get('running') or (s['hardware'] and s['hardware']['connected']))
    def record_count(self):
        if not (self.root / 'runs.sqlite3').exists():
            return 0
        with database(self.root / 'runs.sqlite3') as db:
            return db.execute('SELECT COUNT(*) FROM runs').fetchone()[0]
    def overview(self, request):
        rows = history(self.root, limit=max(self.record_count(), 1))
        query = request.GET.get('q', '').strip().lower()[:80]
        if query:
            rows = [r for r in rows if query in (r['id'] + r['started_at'] + r['status'] + str(r['summary'].get('scenario', ''))).lower()]
        return {'total_records': self.record_count(), 'matching': len(rows), 'records': [
            {'id': r['id'], 'name': r['summary'].get('scenario', r['mode']), 'time': r['started_at'],
             'status': r['status'], 'download': '/api/export?id=' + r['id']} for r in rows[:100]],
            'collections': [{'name': '运行记录', 'count': self.record_count()}]}

def release_user(user):
    global _hardware_owner
    from portal import data
    with _hardware_lock:
        if _hardware_owner == user.pk:
            ctx = data.context(user)
            if ctx.engine.hardware:
                ctx.engine.hardware.close()
            _hardware_owner = None

def handle(request, route, raw):
    global _hardware_owner, _hardware_device
    from portal import data
    ctx = data.context(request.user)
    if route.startswith('studio/'):
        from portal.studio_api import handle as studio_handle
        return studio_handle(request, ctx, 'ld', route, raw)
    if route.startswith('lab/'):
        from portal.lab_api import handle as lab_handle
        return lab_handle(request, ctx, 'ld', route, raw)
    engine = ctx.engine
    if request.method == 'GET':
        if route == 'config':
            return {'token': get_token(request), 'version': VERSION, 'mode': settings.DEPLOYMENT_MODE,
                    'hardware_allowed': settings.DEPLOYMENT_MODE == 'local' and request.user.is_staff}
        if route == 'state':
            snapshot = engine.snapshot()
            if snapshot['batch'].get('result'):
                result = dict(snapshot['batch']['result'])
                result['folder'] = 'benchmarks/' + Path(result['folder']).name
                snapshot['batch'] = {**snapshot['batch'], 'result': result}
            return snapshot
        if route == 'history':
            return history(ctx.root)
        if route == 'ports':
            if settings.DEPLOYMENT_MODE != 'local' or not request.user.is_staff:
                return []
            return ports()
        if route in ('run', 'export'):
            try:
                folder = run_folder(ctx.root, request.GET.get('id', ''))
            except ValueError as exc:
                if str(exc) == 'run not found':
                    raise FileNotFoundError() from exc
                raise
            if not folder.exists():
                raise FileNotFoundError()
            if route == 'run':
                return {'verification': verify(folder),
                        'events': [json.loads(line) for line in (folder / 'events.jsonl').read_text(encoding='utf-8').splitlines()],
                        'meta': json.loads((folder / 'meta.json').read_text(encoding='utf-8'))}
            buf = io.BytesIO()
            export_run(folder, buf)
            response = HttpResponse(buf.getvalue(), content_type='application/zip')
            response['Content-Disposition'] = 'attachment; filename="' + folder.name + '.zip"'
            return response
        raise FileNotFoundError()
    if route in ('start', 'benchmark'):
        with _dispatch_lock:
            with data._lock:
                active = sum(bool((c.engine.worker and c.engine.worker.is_alive()) or c.engine.batch.get('running')) for c, _ in data._contexts.values())
            if active >= 2 or ctx.busy():
                raise RuntimeError('已有运行进行中，请等待完成或停止后重试')
            if route == 'start':
                data.check_quota(ctx)
                engine.start(**raw)
            else:
                seeds, count = raw.get('seeds', 20), raw.get('count', 24)
                if settings.DEPLOYMENT_MODE == 'cloud' and (type(seeds) is not int or seeds > 10 or type(count) is not int or count > 40):
                    raise ValueError('在线对照实验最多10组、每组40件')
                data.check_quota(ctx, seeds * 4 if type(seeds) is int else 1)
                engine.start_batch(**raw)
        return {'ok': True}
    if route == 'stop':
        engine.stop()
    elif route == 'recover':
        engine.recover(raw.get('confirmed') is True)
    elif route in ('connect', 'arm', 'run_one', 'hw_stop', 'disconnect'):
        if settings.DEPLOYMENT_MODE != 'local':
            raise PermissionError('实物连接仅在设备所在电脑的本地工作台使用')
        if not request.user.is_staff:
            raise PermissionError('实物操作需要本机管理员授予操作权限')
        with _hardware_lock:
            if route == 'connect':
                if _hardware_device and not _hardware_device.connected:
                    _hardware_owner = None
                if _hardware_owner not in (None, request.user.pk):
                    raise RuntimeError('设备已由其他操作员连接')
                data.check_quota(ctx)
                engine.connect(raw.get('port', ''))
                _hardware_owner = request.user.pk
                _hardware_device = engine.hardware
            else:
                hw = engine.hardware
                if _hardware_owner != request.user.pk or not hw or not hw.connected:
                    if _hardware_owner == request.user.pk:
                        _hardware_owner = None
                    raise RuntimeError('设备尚未连接，请先选择 USB 串口并点击连接')
                if route == 'arm':
                    hw.arm(raw.get('confirmed') is True)
                elif route == 'run_one':
                    hw.run_one(raw.get('route'), raw.get('order_id'))
                elif route == 'hw_stop':
                    hw.stop()
                else:
                    hw.close()
                    _hardware_owner = None
    else:
        raise FileNotFoundError()
    return {'ok': True}
