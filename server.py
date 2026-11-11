import os,re,json,hmac,hashlib,sqlite3,threading,time,secrets,urllib.request,urllib.parse,datetime as dt
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
TOK=os.environ['BOT_TOKEN'];OWNER=int(os.environ['OWNER_ID'])
MSK=dt.timezone(dt.timedelta(hours=3));L=threading.Lock()
os.makedirs('/data/backups',exist_ok=True)
db=sqlite3.connect('/data/app.db',check_same_thread=False)
db.executescript("create table if not exists docs(id text primary key,kind text,data text);create table if not exists log(ts text,act text,id text,old text,new text);create table if not exists inv(tok text primary key,client text,exp real);create table if not exists bind(tg integer primary key,client text)")
FAIL={};TRY={};BOT=[os.environ.get('BOT_USERNAME','').lstrip('@') or None]
HD={'X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','Strict-Transport-Security':'max-age=31536000',
'Content-Security-Policy':"default-src 'self'; script-src 'self' 'unsafe-inline' https://telegram.org; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'self' https://*.telegram.org"}
def strip(x):
    try:
        d=json.loads(x);d.pop('photos',None);return json.dumps(d)
    except Exception:return None
def who(init):
    try:
        q=dict(urllib.parse.parse_qsl(init));h=q.pop('hash')
        s='\n'.join(f'{k}={q[k]}' for k in sorted(q))
        key=hmac.new(b'WebAppData',TOK.encode(),hashlib.sha256).digest()
        if hmac.compare_digest(hmac.new(key,s.encode(),hashlib.sha256).hexdigest(),h) and time.time()-int(q['auth_date'])<86400:return json.loads(q['user'])['id']
    except Exception:pass
def tg(method,data):
    return json.load(urllib.request.urlopen(urllib.request.Request(f'https://api.telegram.org/bot{TOK}/{method}',json.dumps(data).encode(),{'Content-Type':'application/json'}),timeout=20))
def _say(t):
    try:tg('sendMessage',{'chat_id':OWNER,'text':t})
    except Exception as e:print('say',e)
def say(t):threading.Thread(target=_say,args=(t,),daemon=True).start()
def botname():
    if not BOT[0]:
        try:BOT[0]=tg('getMe',{})['result']['username']
        except Exception as e:print('getMe',e)
    return BOT[0]
def doc(i):
    r=db.execute('select data from docs where id=?',(i,)).fetchone();return r and json.loads(r[0])
def digits(p):return re.sub(r'\D','',p or '')[-10:]
def first_unpaid(d):
    for k in range(1,d['n']+1):
        if str(k) not in d['paid']:return k
def due(d,k):return dt.date.fromisoformat(d['start'])+dt.timedelta(days=0 if k==1 else (30 if d['type']=='m' else 7)*(k-1)-1+d.get('shift',0))
def due_today(ds,t):
    c=0
    for d in ds:
        if d.get('status')!='active':continue
        k=first_unpaid(d)
        if k and due(d,k)==t:c+=1
    return c
def mine(cid):
    c=doc(cid) or {};out=[]
    for i,d in db.execute("select id,data from docs where kind='deal'").fetchall():
        d=json.loads(d)
        if d['client']==cid:
            out.append({k:d.get(k) for k in('n','start','pay','last','paid','early','shift','defer','pen','status','contract','type')}|{'id':i,'bike':(doc(d['bike']) or {}).get('name','')})
    return {'role':'client','name':c.get('name',''),'deals':out,'dd':(doc('cfg') or {}).get('dd',2)}
class H(BaseHTTPRequestHandler):
    def send(s,c,b,t='application/json'):
        s.send_response(c);s.send_header('Content-Type',t)
        for k,v in HD.items():s.send_header(k,v)
        s.end_headers();s.wfile.write(b)
    def user(s):
        ip=(s.headers.get('X-Forwarded-For','').split(',')[0].strip() or s.client_address[0]);t=time.time()
        FAIL[ip]=[x for x in FAIL.get(ip,[]) if x>t-600]
        if len(FAIL[ip])>=10:return None
        u=who(s.headers.get('X-Init',''))
        if u is None:FAIL[ip].append(t)
        return u
    def do_GET(s):
        if s.path in('/api/all','/api/me'):
            u=s.user()
            if u is None:return s.send(403,b'{}')
            with L:
                if s.path=='/api/all':
                    if u!=OWNER:return s.send(403,b'{}')
                    r=[{'kind':k,'id':i,'data':json.loads(d)} for i,k,d in db.execute('select id,kind,data from docs')]
                else:
                    b=db.execute('select client from bind where tg=?',(u,)).fetchone()
                    r={'role':'owner'} if u==OWNER else mine(b[0]) if b else {'role':'new'}
            return s.send(200,json.dumps(r).encode())
        f={'/':'index.html','/calc.js':'calc.js'}.get(s.path)
        if not f:return s.send(404,b'')
        s.send(200,open('static/'+f,'rb').read(),'text/html; charset=utf-8' if f[-1]=='l' else 'application/javascript')
    def do_POST(s):
        u=s.user()
        if u is None:return s.send(403,b'{}')
        n=int(s.headers.get('Content-Length',0))
        if n>3000000:return s.send(413,b'{}')
        try:b=json.loads(s.rfile.read(n))
        except Exception:return s.send(400,b'{}')
        p=s.path;ts=dt.datetime.now(MSK).isoformat();t=time.time()
        with L:
            if u==OWNER:
                if p in('/api/put','/api/del'):
                    if not re.fullmatch(r'[a-z0-9]{1,16}',str(b.get('id',''))) or (p=='/api/put' and b.get('kind') not in('client','bike','deal','cfg')):return s.send(400,b'{}')
                    o=db.execute('select data from docs where id=?',(b['id'],)).fetchone()
                    if p=='/api/put':db.execute('insert or replace into docs values(?,?,?)',(b['id'],b['kind'],json.dumps(b['data'])))
                    else:db.execute('delete from docs where id=?',(b['id'],))
                    db.execute('insert into log values(?,?,?,?,?)',(ts,p[5:],b['id'],o and strip(o[0]),strip(json.dumps(b.get('data')))));db.commit()
                    return s.send(200,b'{}')
                if p=='/api/invite':
                    k=secrets.token_urlsafe(9);db.execute('insert into inv values(?,?,?)',(k,str(b.get('client')),t+7*86400));db.commit()
                    if not BOT[0]:return s.send(500,b'{}')
                    return s.send(200,json.dumps({'tok':k,'bot':BOT[0]}).encode())
                if p=='/api/unbind':
                    db.execute('delete from bind where client=?',(str(b.get('client')),));db.commit();return s.send(200,b'{}')
                return s.send(404,b'{}')
            r=db.execute('select client from bind where tg=?',(u,)).fetchone()
            if p=='/api/claim' and not r:
                TRY[u]=[x for x in TRY.get(u,[]) if x>t-3600]
                if len(TRY[u])>=5:return s.send(429,b'{}')
                TRY[u].append(t)
                i=db.execute('select client from inv where tok=? and exp>?',(str(b.get('tok')),t)).fetchone();c=i and doc(i[0]);ph=digits(b.get('phone'))
                if not c or not ph or digits(c.get('phone'))!=ph:
                    if len(TRY[u])==3:say(f'Неудачные попытки входа клиента (Telegram ID {u}).')
                    return s.send(403,b'{}')
                db.execute('insert or replace into bind values(?,?)',(u,i[0]));db.execute('delete from inv where tok=?',(str(b.get('tok')),));db.commit()
                say(f"Клиент {c.get('name')} вошёл в приложение.");return s.send(200,b'{}')
            if p=='/api/defer' and r and re.fullmatch(r'[a-z0-9]{1,16}',str(b.get('id',''))):
                d=doc(b['id']);today=dt.datetime.now(MSK).date()
                if not d or d.get('client')!=r[0] or d.get('status')!='active' or any(x.get('by')=='client' for x in d.get('defer',[])):return s.send(409,b'{}')
                k=first_unpaid(d)
                if not k or due(d,k)<today:return s.send(409,b'{}')
                n2=(doc('cfg') or {}).get('dd',2);d['shift']=d.get('shift',0)+n2;d.setdefault('defer',[]).append({'date':str(today),'days':n2,'by':'client'})
                db.execute('insert or replace into docs values(?,?,?)',(b['id'],'deal',json.dumps(d)))
                db.execute('insert into log values(?,?,?,?,?)',(ts,'defer-client',b['id'],None,None));db.commit()
                say(f"Клиент {(doc(r[0]) or {}).get('name')} взял отсрочку на {n2} дн.");return s.send(200,b'{}')
        return s.send(403,b'{}')
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
threading.Thread(target=botname,daemon=True).start()
ThreadingHTTPServer(('',8080),H).serve_forever()
