import os,re,json,hmac,hashlib,sqlite3,threading,time,urllib.request,urllib.parse,datetime as dt
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
TOK=os.environ['BOT_TOKEN'];OWNER=int(os.environ['OWNER_ID'])
MSK=dt.timezone(dt.timedelta(hours=3));L=threading.Lock()
os.makedirs('/data/backups',exist_ok=True)
db=sqlite3.connect('/data/app.db',check_same_thread=False)
db.executescript("create table if not exists docs(id text primary key,kind text,data text);create table if not exists log(ts text,act text,id text,old text,new text)")
def ok(init):
    try:
        q=dict(urllib.parse.parse_qsl(init));h=q.pop('hash')
        s='\n'.join(f'{k}={q[k]}' for k in sorted(q))
        key=hmac.new(b'WebAppData',TOK.encode(),hashlib.sha256).digest()
        return hmac.compare_digest(hmac.new(key,s.encode(),hashlib.sha256).hexdigest(),h) and json.loads(q['user'])['id']==OWNER and time.time()-int(q['auth_date'])<86400
    except Exception:return False
def due_today(ds,t):
    c=0
    for d in ds:
        if d.get('status')!='active':continue
        P=7 if d['type']=='w' else 30
        for k in range(1,d['n']+1):
            if str(k) in d['paid']:continue
            if dt.date.fromisoformat(d['start'])+dt.timedelta(days=0 if k==1 else P*(k-1)-1)==t:c+=1
            break
    return c
FAIL={}
HD={'X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','Strict-Transport-Security':'max-age=31536000',
'Content-Security-Policy':"default-src 'self'; script-src 'self' 'unsafe-inline' https://telegram.org; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'self' https://*.telegram.org"}
def strip(x):
    try:
        d=json.loads(x);d.pop('photos',None);return json.dumps(d)
    except Exception:return None
class H(BaseHTTPRequestHandler):
    def auth(s):
        ip=(s.headers.get('X-Forwarded-For','').split(',')[0].strip() or s.client_address[0]);t=time.time()
        FAIL[ip]=[x for x in FAIL.get(ip,[]) if x>t-600]
        if len(FAIL[ip])>=10:return False
        if ok(s.headers.get('X-Init','')):return True
        FAIL[ip].append(t);return False
    def send(s,c,b,t='application/json'):
        s.send_response(c);s.send_header('Content-Type',t)
        for k,v in HD.items():s.send_header(k,v)
        s.end_headers();s.wfile.write(b)
    def do_GET(s):
        if s.path=='/api/all':
            if not s.auth():return s.send(403,b'{}')
            with L:r=[{'kind':k,'id':i,'data':json.loads(d)} for i,k,d in db.execute('select id,kind,data from docs')]
            return s.send(200,json.dumps(r).encode())
        f={'/':'index.html','/calc.js':'calc.js'}.get(s.path)
        if not f:return s.send(404,b'')
        s.send(200,open('static/'+f,'rb').read(),'text/html; charset=utf-8' if f[-1]=='l' else 'application/javascript')
    def do_POST(s):
        if not s.auth():return s.send(403,b'{}')
        n=int(s.headers.get('Content-Length',0))
        if n>3000000:return s.send(413,b'{}')
        try:b=json.loads(s.rfile.read(n))
        except Exception:return s.send(400,b'{}')
        if s.path not in('/api/put','/api/del') or not re.fullmatch(r'[a-z0-9]{1,16}',str(b.get('id',''))) or (s.path=='/api/put' and b.get('kind') not in('client','bike','deal','cfg')):return s.send(400,b'{}')
        ts=dt.datetime.now(MSK).isoformat()
        with L:
            o=db.execute('select data from docs where id=?',(b['id'],)).fetchone()
            if s.path=='/api/put':db.execute('insert or replace into docs values(?,?,?)',(b['id'],b['kind'],json.dumps(b['data'])))
            else:db.execute('delete from docs where id=?',(b['id'],))
            db.execute('insert into log values(?,?,?,?,?)',(ts,s.path[5:],b['id'],o and strip(o[0]),strip(json.dumps(b.get('data')))));db.commit()
        s.send(200,b'{}')
def say(t):
    urllib.request.urlopen(urllib.request.Request(f'https://api.telegram.org/bot{TOK}/sendMessage',json.dumps({'chat_id':OWNER,'text':t}).encode(),{'Content-Type':'application/json'}),timeout=20)
def job():
    last=None
    while 1:
        n=dt.datetime.now(MSK);key=(n.date(),n.hour)
        if key!=last and n.hour in(3,10):
            last=key
            try:
                with L:
                    if n.hour==3:
                        b=sqlite3.connect(f'/data/backups/app-{n.date()}.db');db.backup(b);b.close()
                        for f in sorted(os.listdir('/data/backups'))[:-30]:os.remove('/data/backups/'+f)
                    else:ds=[json.loads(d) for (d,) in db.execute("select data from docs where kind='deal'")]
                if n.hour==10:
                    c=due_today(ds,n.date());say(f'Сегодня платят клиентов: {c}' if c else 'Сегодня платежей нет')
            except Exception as e:print(e)
        time.sleep(30)
threading.Thread(target=job,daemon=True).start()
ThreadingHTTPServer(('',8080),H).serve_forever()
