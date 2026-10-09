"""Authenticated durable runner; only a fixed, reviewed paper calculation is allowed."""
import hashlib, hmac, json, os, re, signal, sqlite3, subprocess, sys, threading, time
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
ROOT = Path(os.environ.get('DATA_DIR', '/var/data'))
STOP = threading.Event()
TOKEN = os.environ.get('RUNNER_TOKEN', '')

def db():
    c = sqlite3.connect(ROOT/'jobs.db', timeout=30)
    c.row_factory = sqlite3.Row
    return c

def init():
    ROOT.mkdir(parents=True, exist_ok=True)
    with db() as c:
        c.execute('PRAGMA journal_mode=WAL')
        c.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, digest TEXT, payload TEXT, state TEXT, attempts INTEGER DEFAULT 0, due REAL DEFAULT 0, error TEXT, result TEXT)')
        # Single process / single Render instance. Recover interrupted runs on boot.
        c.execute("UPDATE jobs SET state='queued' WHERE state='running' AND attempts<3")
        c.execute("UPDATE jobs SET state='failed',error='retry budget exhausted during interruption' WHERE state='running'")

def enqueue(p):
    if p.get('kind') != 'paper_20261008': raise ValueError('unsupported calculation; no arbitrary commands')
    jid = p.get('id','')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', jid): raise ValueError('invalid id')
    for k in ('source_csv','daily_csv','table_html'):
        if not isinstance(p.get(k),str) or not p[k]: raise ValueError('missing input')
    if 'id="visible-results"' not in p['table_html']: raise ValueError('unsupported table template')
    raw = json.dumps(p,sort_keys=True,ensure_ascii=False)
    digest = hashlib.sha256(raw.encode()).hexdigest()
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        old = c.execute('SELECT digest,state FROM jobs WHERE id=?',(jid,)).fetchone()
        if old:
            if old['digest'] != digest: raise ValueError('id conflict: changed input requires a new id')
            return {'id':jid,'state':old['state'],'duplicate':True}
        c.execute('INSERT INTO jobs(id,digest,payload,state) VALUES(?,?,?,?)',(jid,digest,raw,'queued'))
    return {'id':jid,'state':'queued','duplicate':False}

def run_once():
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        row = c.execute("SELECT * FROM jobs WHERE state='queued' AND due<=? ORDER BY rowid LIMIT 1",(time.time(),)).fetchone()
        if row is None: return False
        c.execute("UPDATE jobs SET state='running',attempts=attempts+1 WHERE id=?",(row['id'],))
    try:
        p = json.loads(row['payload'])
        work = ROOT / row['id']; work.mkdir(exist_ok=True)
        # Reset each attempt to immutable submitted inputs. Never append twice.
        for key,name in [('source_csv','source.csv'),('daily_csv','daily247.csv'),('table_html','ARK-X_成績表.html')]:
            value = p[key]
            if key == 'table_html':
                value = re.sub(r'<!-- BEGIN CEO-FAL-20261007-20261008 -->.*?<!-- END CEO-FAL-20261007-20261008 -->', '', value, flags=re.S)
            (work/name).write_text(value,encoding='utf-8')
        (work/'calculate.py').write_bytes(Path(__file__).with_name('calculate_20261008.py').read_bytes())
        r = subprocess.run([sys.executable,str(work/'calculate.py')],capture_output=True,timeout=60)
        if r.returncode: raise RuntimeError('calculation validation failed')
        if not (work/'calculation.json').exists():
            # Calculator's same-input fast path: derive the already present embedded result.
            s=(work/'ARK-X_成績表.html').read_text()
            m=re.search(r'<script type="application/json" id="ceofal-results-data">(.*?)</script>',s,re.S)
            if not m: raise RuntimeError('missing calculation result')
            json.loads(m.group(1)); (work/'calculation.json').write_text(m.group(1))
        result=json.loads((work/'calculation.json').read_text())
        if len(result['rows']) != 10: raise RuntimeError('wrong row count')
        with db() as c: c.execute("UPDATE jobs SET state='done',result=?,error=NULL WHERE id=?",(json.dumps(result,ensure_ascii=False),row['id']))
    except Exception as e:
        attempt=row['attempts']+1
        with db() as c: c.execute('UPDATE jobs SET state=?,due=?,error=? WHERE id=?',('queued' if attempt<3 else 'failed',time.time()+5*2**(attempt-1),type(e).__name__,row['id']))
    return True

def loop():
    while not STOP.is_set():
        try: run_once()
        except Exception: print('worker_iteration_failed', flush=True)
        STOP.wait(1)

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass # Do not log data, tokens, or paths.
    def reply(self,code,obj):
        b=json.dumps(obj,ensure_ascii=False).encode(); self.send_response(code)
        self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Content-Length',str(len(b))); self.end_headers(); self.wfile.write(b)
    def auth(self): return hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+TOKEN)
    def do_GET(self):
        if self.path=='/health': return self.reply(200,{'status':'ok','paper_only':True})
        if not self.auth(): return self.reply(401,{'error':'unauthorized'})
        m=re.fullmatch(r'/jobs/([A-Za-z0-9_-]{1,100})(/table)?',self.path)
        if not m: return self.reply(404,{'error':'not found'})
        with db() as c: row=c.execute('SELECT id,state,attempts,error,result FROM jobs WHERE id=?',(m[1],)).fetchone()
        if not row: return self.reply(404,{'error':'not found'})
        d=dict(row)
        if m[2] and d['state']=='done': d['table_html']=(ROOT/m[1]/'ARK-X_成績表.html').read_text()
        if d['result']: d['result']=json.loads(d['result'])
        self.reply(200,d)
    def do_POST(self):
        if not self.auth(): return self.reply(401,{'error':'unauthorized'})
        if self.path!='/jobs': return self.reply(404,{'error':'not found'})
        try:
            n=int(self.headers.get('Content-Length','0'))
            if n<=0 or n>5000000: return self.reply(413,{'error':'payload size'})
            p=json.loads(self.rfile.read(n)); result=enqueue(p)
        except (ValueError,TypeError,AttributeError): return self.reply(400,{'error':'invalid or conflicting job'})
        self.reply(202,result)

if __name__=='__main__':
    if len(TOKEN)<32: raise SystemExit('RUNNER_TOKEN must be at least 32 characters')
    init(); worker=threading.Thread(target=loop,daemon=True); worker.start()
    server=ThreadingHTTPServer(('0.0.0.0',int(os.environ.get('PORT','10000'))),Handler)
    def shutdown(*_):
        STOP.set(); threading.Thread(target=server.shutdown,daemon=True).start()
    signal.signal(signal.SIGTERM,shutdown); signal.signal(signal.SIGINT,shutdown)
    server.serve_forever(); worker.join(timeout=65); server.server_close()
