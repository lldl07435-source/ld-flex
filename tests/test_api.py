import http.cookiejar
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.request import Request, build_opener, HTTPCookieProcessor
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parents[1]

class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
        self.url = 'http://127.0.0.1:' + str(port)
        self.output = (self.root / 'server.log').open('wb')
        self.process = subprocess.Popen([sys.executable, 'app.py', '--no-browser', '--port', str(port), '--data-root', str(self.root / 'data')], cwd=ROOT, stdout=self.output, stderr=self.output, env={**os.environ, 'PYTHONUTF8':'1'})
        self.http = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                self.get('/api/account'); break
            except (URLError, OSError):
                time.sleep(.1)
        else:
            self.tearDown(); self.fail('服务未启动')
        self.post('/api/account/register', {'username':'apitester', 'password':'Ld-API-Actual-Run-92!'})
    def tearDown(self):
        if self.process.poll() is None:
            self.process.terminate(); self.process.wait(8)
        self.output.close()
        # Windows 偶尔延迟释放已退出进程的 SQLite 文件句柄。
        for attempt in range(20):
            try:
                self.temp.cleanup(); break
            except PermissionError:
                if attempt == 19: raise
                time.sleep(.1)
    def get(self, path):
        with self.http.open(self.url + path, timeout=8) as response:
            return json.load(response)
    def post(self, path, payload, token=None):
        csrf = self.get('/api/account')['csrf'] if token is None else token
        req = Request(self.url + path, json.dumps(payload).encode(), {'Content-Type':'application/json','X-CSRFToken':csrf})
        with self.http.open(req, timeout=10) as response:
            return json.load(response)
    def test_start_finish_history_replay(self):
        self.post('/api/start', {'count':12, 'speed':10})
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            state = self.get('/api/state')
            records = self.get('/api/history')
            if records and records[0]['status'] == 'completed':
                break
            time.sleep(.05)
        self.assertEqual(state['simulation']['summary']['completed'], 12)
        self.assertEqual(len(records), 1)
        self.assertTrue(self.get('/api/run?id=' + records[0]['id'])['verification']['ok'])
    def test_csrf_and_invalid_input(self):
        with self.assertRaises(HTTPError) as error:
            self.post('/api/start', {}, token='bad')
        self.assertEqual(error.exception.code, 403); error.exception.close()
        with self.assertRaises(HTTPError) as error:
            self.post('/api/start', {'count':-1})
        self.assertEqual(error.exception.code, 400); error.exception.close()
    def test_host_check_and_path_escape(self):
        with self.assertRaises(HTTPError) as error:
            self.http.open(Request(self.url + '/api/config', headers={'Host':'evil.example'}))
        self.assertEqual(error.exception.code, 403); error.exception.close()
        with self.assertRaises(HTTPError) as error:
            self.get('/api/run?id=../README.md')
        error.exception.close()
    def test_same_data_directory_cannot_start_twice(self):
        result = subprocess.run([sys.executable, 'app.py', '--no-browser', '--port', '18879', '--data-root', str(self.root / 'data')], cwd=ROOT, capture_output=True, timeout=10, env={**os.environ, 'PYTHONUTF8':'1'})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('已经在使用', result.stderr.decode('utf-8'))

if __name__ == '__main__':
    unittest.main()
