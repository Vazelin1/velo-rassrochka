import os,re,json,hmac,hashlib,sqlite3,threading,time,secrets,urllib.request,urllib.error,urllib.parse,datetime as dt
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
TOK=os.environ['BOT_TOKEN'];OWNER=int(os.environ['OWNER_ID'])
MSK=dt.timezone(dt.timedelta(hours=3));L=threading.Lock()
DATA=os.environ.get('DATA_DIR','/data');BK=DATA+'/backups';os.makedirs(BK,exist_ok=True);TGB=os.environ.get('TG_BASE','https://api.telegram.org')
db=sqlite3.connect(DATA+'/app.db',check_same_thread=False)
db.executescript("create table if not exists docs(id text primary key,kind text,data text);create table if not exists log(ts text,act text,id text,old text,new text);create table if not exists inv(tok text primary key,client text,exp real);create table if not exists bind(tg integer primary key,client text);create table if not exists ntf(k text primary key)")
FAIL={};TRY={};BOT=[os.environ.get('BOT_USERNAME','').lstrip('@') or None]
HD={'X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','Strict-Transport-Security':'max-age=31536000',
'Content-Security-Policy':"default-src 'self'; script-src 'self' 'unsafe-inline' https://telegram.org; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'self' https://*.telegram.org"}
KINDS=('client','bike','deal','cfg','admin')
PERMS=('pay','early','pen','clients','deals','bikes','reports')
FINP={'deals','bikes','reports'}  # rights that let an administrator see prices, purchase costs and profit
HID={'deal':('total','tax','acq','cost','disc','mk','extras','down','refund'),'bike':('cost','exp','wo')}
PUBCFG=('id','dd','early','ed','pen','dmin','dbd')
ID=re.compile(r'[a-z0-9]{1,16}')
NO=object()
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
    return json.load(urllib.request.urlopen(urllib.request.Request(f'{TGB}/bot{TOK}/{method}',json.dumps(data).encode(),{'Content-Type':'application/json'}),timeout=20))
def _send(chat,t):
    try:tg('sendMessage',{'chat_id':chat,'text':t})
    except Exception as e:print('send',e)
def push(chat,t):threading.Thread(target=_send,args=(chat,t),daemon=True).start()
# Telegram messages are switched off by default: the owner turns them on in Settings
# ('nown' = messages to the owner, 'ncli' = reminders and confirmations to clients). Call say/tell with the lock held.
def flag(k):return bool((doc('cfg') or {}).get(k))
def say(t):
    if flag('nown'):push(OWNER,t)
def tell(cid,t):
    if flag('ncli'):
        for (g,) in db.execute('select tg from bind where client=?',(cid,)).fetchall():push(g,t)
def rub(n):return f'{round(n):,}'.replace(',',' ')+' ₽'
def dm(d):return d.strftime('%d.%m.%Y')
def botname():
    if not BOT[0]:
        try:BOT[0]=tg('getMe',{})['result']['username']
        except Exception as e:print('getMe',e)
    return BOT[0]
def row(i):
    r=db.execute('select kind,data from docs where id=?',(i,)).fetchone();return r and (r[0],json.loads(r[1]))
def doc(i):
    r=row(i);return r and r[1]
def save(i,k,d):db.execute('insert or replace into docs values(?,?,?)',(i,k,json.dumps(d)))
def digits(p):return re.sub(r'\D','',p or '')[-10:]
def first_unpaid(d):
    for k in range(1,d['n']+1):
        if str(k) not in d['paid']:return k
def due(d,k):return dt.date.fromisoformat(d['start'])+dt.timedelta(days=0 if k==1 else (30 if d['type']=='m' else 7)*(k-1)-1+d.get('shift',0))
def sched(d):
    """Payment schedule as the app shows it: early payments shorten it from the end (mirrors static/calc.js)."""
    n=d['n'];paid=d.get('paid') or {};r=[{'k':k,'amt':d['last'] if k==n else d['pay']} for k in range(1,n+1)]
    e=sum(x.get('paid') or x.get('amt') or 0 for x in d.get('early') or [])
    for x in reversed(r):
        if e<=0 or str(x['k']) in paid:break
        c=min(e,x['amt']);x['amt']-=c;e-=c
    return [x for x in r if x['amt']>0 or str(x['k']) in paid]
def nxt(d):
    p=d.get('paid') or {}
    for x in sched(d):
        if str(x['k']) not in p:return x
def due_today(ds,t):
    c=0
    for d in ds:
        if d.get('status')!='active':continue
        x=nxt(d)
        if x and due(d,x['k'])==t:c+=1
    return c
def notify_deal(old,new,ro,adm):
    """Messages after a deal was saved by the owner or an administrator. Call with the lock held."""
    if not old:return
    cn=(doc(new.get('client')) or {}).get('name','')
    if ro=='admin':
        sc=sched(new);P=new.get('paid') or {};O=old.get('paid') or {}
        for k,p in P.items():
            if k not in O:
                rest=sum(x['amt'] for x in sc if str(x['k']) not in P)
                say(f"Оплата принята ({adm}): {cn}, {rub((p.get('amt') or 0)+(p.get('pen') or 0))}, период {k} из {len(sc)}, {p.get('method','')}. Осталось по графику: {rub(rest)}.")
        g=new.get('debt')
        for k,p in P.items():
            if k not in O and p.get('part') and g and g.get('amt')>0:
                say(f"Остаток по периоду {k} ({cn}): {rub(g['amt'])}, срок без неустойки до {dm(dt.date.fromisoformat(g['due']))}.")
        if len(new.get('dpays') or [])>len(old.get('dpays') or []):
            e=new['dpays'][-1];say(f"Оплата долга принята ({adm}): {cn}, {rub((e.get('amt') or 0)+(e.get('pen') or 0))}, {e.get('method','')}."+(" Долг закрыт." if not (g and g.get('amt')>0) else f" Остаток долга: {rub(g['amt'])}."))
        if len(new.get('early') or [])>len(old.get('early') or []):
            e=new['early'][-1];say(f"Досрочный платёж принят ({adm}): {cn}, {rub(e.get('paid') or e.get('amt') or 0)}.")
    if (new.get('shift') or 0)>(old.get('shift') or 0) and new.get('status')=='active':
        defer_msg(new)
def defer_msg(d):
    x=nxt(d)
    if x:tell(d.get('client'),f"Отсрочка оформлена. Ближайший платёж {rub(x['amt'])} теперь до {dm(due(d,x['k']))}.")
def mine(cid):
    c=doc(cid) or {};out=[]
    for i,d in db.execute("select id,data from docs where kind='deal'").fetchall():
        d=json.loads(d)
        if d['client']==cid:
            out.append({k:d.get(k) for k in('n','start','pay','last','paid','early','shift','defer','pen','status','contract','type','debt','dpays','pw','np')}|{'id':i,'bike':(doc(d['bike']) or {}).get('name','')})
    return {'role':'client','name':c.get('name',''),'deals':out,'dd':(doc('cfg') or {}).get('dd',2)}
def adm_of(u):
    """The administrator whose Telegram ID is u: (id, data) or None."""
    for i,d in db.execute("select id,data from docs where kind='admin'").fetchall():
        d=json.loads(d)
        if d.get('tg')==u:return i,d
def role(u):
    if u==OWNER:return 'owner',None
    a=adm_of(u)
    if a:return ('off',a) if a[1].get('disabled') else ('admin',a)
    b=db.execute('select client from bind where tg=?',(u,)).fetchone()
    return ('client',b[0]) if b else ('new',None)
def hasfin(P):return bool(set(P)&FINP)
def vw(k,d,f):
    """Document as an administrator without financial rights may see it."""
    if f:return d
    if k=='cfg':return {x:y for x,y in d.items() if x in PUBCFG}
    return {x:y for x,y in d.items() if x not in HID.get(k,())}
def okkey(P,k,x,m):
    """May an administrator with rights P change field x of a document of kind k?"""
    if k=='deal':
        n={'paid':'pay','debt':'pay','dpays':'pay','early':'early','shift':'early','defer':'early','pw':'pen','np':'pen'}.get(x)
        if n:return n in P
        if x in('bike','swaps'):return 'bikes' in P
        if x in('status','closed'):return ('bikes' if m.get('status')=='lost' else 'deals') in P
        return 'deals' in P
    if k=='bike':
        if x in('archived','photos'):return bool(P&{'deals','bikes'})
        return 'bikes' in P
    if k=='client':
        if x=='archived':return bool(P&{'clients','deals'})
        return 'clients' in P
    return False
def amerge(P,k,old,new):
    """What an administrator with rights P may write. Returns the document to store or None when refused.
    Fields the administrator cannot see are never taken from the request: they are kept from the stored version."""
    if k not in('client','bike','deal'):return None
    if old is None:return new if {'client':'clients','bike':'bikes','deal':'deals'}[k] in P else None
    hid=() if hasfin(P) else HID.get(k,())
    m={x:y for x,y in new.items() if x not in hid}
    for x in hid:
        if x in old:m[x]=old[x]
    for x in set(m)|set(old):
        if x=='_v' or m.get(x,NO)==old.get(x,NO):continue
        if not okkey(P,k,x,m):return None
    return m
def dump():
    with L:
        return json.dumps({'v':1,'ts':dt.datetime.now(MSK).isoformat(),'docs':[{'id':i,'kind':k,'data':json.loads(x)} for i,k,x in db.execute('select id,kind,data from docs')],
        'bind':[[a,c] for a,c in db.execute('select tg,client from bind')],'log':[list(r) for r in db.execute('select ts,act,id,old,new from log')]},ensure_ascii=False).encode()
DL={};TTL=int(os.environ.get('DL_TTL','120'));BS=DATA+'/last_download.json'
def bget():
    try:return json.load(open(BS))
    except Exception:return None
def bset():
    try:open(BS,'w').write(json.dumps({'ts':dt.datetime.now(MSK).isoformat()}))
    except Exception as e:print('bset',e)
def snap(pre):
    b=sqlite3.connect(f'{BK}/{pre}-{dt.datetime.now(MSK):%Y-%m-%d-%H%M%S}.db');db.backup(b);b.close()
    for f in sorted(x for x in os.listdir(BK) if x.startswith(pre+'-'))[:-(30 if pre=='app' else 5)]:os.remove(f'{BK}/{f}')
def restore(b):
    """returns (code, reply). Replaces docs and bind with the backup content; the audit log is kept."""
    try:
        if not isinstance(b,dict) or b.get('v')!=1:return 400,'Это не файл копии (или файл от другой версии).'
        docs=b['docs'];bind=b.get('bind',[]);lg=b.get('log',[])
        if not isinstance(docs,list) or not isinstance(bind,list) or not isinstance(lg,list) or len(docs)>20000:return 400,'Файл повреждён.'
        seen=set();rows=[]
        for x in docs:
            i,k,d=x['id'],x['kind'],x['data']
            if not isinstance(i,str) or not ID.fullmatch(i) or k not in KINDS or not isinstance(d,dict) or i in seen:return 400,'Файл повреждён: неверная запись.'
            seen.add(i);rows.append((i,k,json.dumps(d)))
        bi=[(int(a),str(c)) for a,c in bind if ID.fullmatch(str(c))]
        lg=[tuple(None if y is None else str(y) for y in r) for r in lg if isinstance(r,list) and len(r)==5][-100000:]
    except Exception:return 400,'Файл повреждён.'
    with L:
        snap('pre-restore')
        try:
            empty=not db.execute('select 1 from log limit 1').fetchone()
            db.execute('delete from docs');db.execute('delete from bind');db.execute('delete from inv')
            db.executemany('insert into docs values(?,?,?)',rows);db.executemany('insert or replace into bind values(?,?)',bi)
            if empty:db.executemany('insert into log values(?,?,?,?,?)',lg)
            db.execute('insert into log values(?,?,?,?,?)',(dt.datetime.now(MSK).isoformat(),'restore','',None,json.dumps({'docs':len(rows),'from':b.get('ts')})));db.commit()
        except Exception as e:
            db.rollback();print('restore',e);return 500,'Не удалось восстановить, данные не изменены.'
    return 200,len(rows)
def clean_admin(i,old,new):
    """Owner edits an administrator: only name, phone, rights and the disabled flag are taken from the request; the Telegram binding stays as stored."""
    nm=str(new.get('name') or '').strip()[:60];ph=str(new.get('phone') or '').strip()[:30]
    if not nm or not digits(ph):return None
    pl=new.get('perms');pl=pl if isinstance(pl,list) else []
    return {'id':i,'name':nm,'phone':ph,'perms':[q for q in PERMS if q in pl],'tg':(old or {}).get('tg'),'disabled':bool(new.get('disabled')),'created':new.get('created'),'_v':new.get('_v',0)}
class H(BaseHTTPRequestHandler):
    def send(s,c,b,t='application/json',x=None):
        s.send_response(c);s.send_header('Content-Type',t);s.send_header('Content-Length',str(len(b)))
        for k,v in {**HD,**(x or {})}.items():s.send_header(k,v)
        s.end_headers();s.wfile.write(b)
    def ip(s):return s.headers.get('X-Forwarded-For','').split(',')[0].strip() or s.client_address[0]
    def user(s):
        ip=s.ip();t=time.time()
        FAIL[ip]=[x for x in FAIL.get(ip,[]) if x>t-600]
        if len(FAIL[ip])>=10:return None
        u=who(s.headers.get('X-Init',''))
        if u is None:FAIL[ip].append(t)
        return u
    def do_GET(s):
        s.path=s.path.split('?')[0].split('#')[0]
        if s.path in('/api/all','/api/me','/api/log'):
            u=s.user()
            if u is None:return s.send(403,b'{}')
            with L:
                ro,x=role(u)
                if s.path=='/api/all':
                    if ro not in('owner','admin'):return s.send(403,b'{}')
                    f=ro=='owner' or hasfin(x[1].get('perms',[]))
                    r=[{'kind':k,'id':i,'data':vw(k,json.loads(d),f)} for i,k,d in db.execute('select id,kind,data from docs') if ro=='owner' or k!='admin']
                elif s.path=='/api/log':
                    if ro!='owner':return s.send(403,b'{}')
                    r=[list(q) for q in db.execute('select ts,act,id,old,new from log order by rowid desc limit 250')]
                elif ro=='owner':r={'role':'owner','backup':bget()}
                elif ro=='admin':r={'role':'admin','name':x[1].get('name',''),'perms':[q for q in x[1].get('perms',[]) if q in PERMS],'fin':hasfin(x[1].get('perms',[]))}
                elif ro=='client':r=mine(x)
                else:r={'role':ro}
            return s.send(200,json.dumps(r).encode())
        if s.path.startswith('/dl/'):
            ip=('dl',s.ip());t=time.time();FAIL[ip]=[x for x in FAIL.get(ip,[]) if x>t-600]
            for a in [a for a,e in DL.items() if e<t]:DL.pop(a,None)
            if len(FAIL[ip])>=10 or DL.get(s.path[4:],0)<t:FAIL[ip].append(t);return s.send(404,b'')
            d=dump();bset()
            return s.send(200,d,'application/octet-stream',{'Content-Disposition':f'attachment; filename="velo-{dt.datetime.now(MSK):%Y-%m-%d-%H%M}.json"','Cache-Control':'no-store'})
        f={'/':'index.html','/calc.js':'calc.js'}.get(s.path)
        if not f:return s.send(404,b'')
        s.send(200,open('static/'+f,'rb').read(),'text/html; charset=utf-8' if f[-1]=='l' else 'application/javascript',{'Cache-Control':'no-cache'})
    def do_POST(s):
        s.path=s.path.split('?')[0]
        u=s.user()
        if u is None:return s.send(403,b'{}')
        n=int(s.headers.get('Content-Length',0))
        if n>(40000000 if s.path=='/api/restore' and u==OWNER else 3000000):return s.send(413,b'{}')
        try:b=json.loads(s.rfile.read(n))
        except Exception:return s.send(400,b'{}')
        if not isinstance(b,dict):return s.send(400,b'{}')
        p=s.path;ts=dt.datetime.now(MSK).isoformat();t=time.time()
        if u==OWNER and p=='/api/dl':
            k=secrets.token_urlsafe(16);DL[k]=t+TTL
            return s.send(200,json.dumps({'url':'/dl/'+k,'name':f'velo-{dt.datetime.now(MSK):%Y-%m-%d-%H%M}.json'}).encode())
        if u==OWNER and p=='/api/restore':
            c,r=restore(b);return s.send(c,json.dumps({'docs':r} if c==200 else {'err':r}).encode())
        with L:
            ro,x=role(u)
            if ro in('owner','admin'):
                P=set(x[1].get('perms',[])) if ro=='admin' else None
                who_=ro=='admin' and '@'+str(x[1].get('name',''))[:40] or ''
                if p in('/api/put','/api/del'):
                    if p=='/api/del' and ro!='owner':return s.send(403,b'{}')
                    i=str(b.get('id',''))
                    if not ID.fullmatch(i):return s.send(400,b'{}')
                    r=db.execute('select kind,data from docs where id=?',(i,)).fetchone();old=r and json.loads(r[1])
                    if p=='/api/put':
                        k=b.get('kind');new=b.get('data')
                        if k not in KINDS or not isinstance(new,dict) or (r and r[0]!=k):return s.send(400,b'{}')
                        if ro=='admin':
                            new=amerge(P,k,old,new)
                            if new is None:return s.send(403,b'{}')
                        elif k=='admin':
                            new=clean_admin(i,old,new)
                            if new is None:return s.send(400,b'{}')
                        if old is not None and new.get('_v',0)!=old.get('_v',0):return s.send(409,b'{"err":"conflict"}')
                        new['_v']=(old or {}).get('_v',0)+1
                        save(i,k,new)
                    else:db.execute('delete from docs where id=?',(i,));new=None
                    db.execute('insert into log values(?,?,?,?,?)',(ts,p[5:]+who_,i,r and strip(r[1]),new and strip(json.dumps(new))));db.commit()
                    if p=='/api/put' and k=='deal':
                        try:notify_deal(old,new,ro,str(x[1].get('name',''))[:40] if ro=='admin' else '')
                        except Exception as e:print('notify',e)
                    return s.send(200,json.dumps({'_v':new.get('_v')} if new else {}).encode())
                if p in('/api/invite','/api/unbind'):
                    c=str(b.get('client',''))
                    if c.startswith('adm:'):
                        a=ID.fullmatch(c[4:]) and row(c[4:])
                        if ro!='owner' or not a or a[0]!='admin':return s.send(403,b'{}')
                    else:
                        a=ID.fullmatch(c) and row(c)
                        if (ro=='admin' and 'clients' not in P) or not a or a[0]!='client':return s.send(403,b'{}')
                    if p=='/api/invite':
                        if not BOT[0]:return s.send(500,b'{}')
                        k=secrets.token_urlsafe(9);db.execute('insert into inv values(?,?,?)',(k,c,t+7*86400))
                        db.execute('insert into log values(?,?,?,?,?)',(ts,'invite'+who_,c,None,None));db.commit()
                        return s.send(200,json.dumps({'tok':k,'bot':BOT[0]}).encode())
                    if c.startswith('adm:'):
                        a[1]['tg']=None;a[1]['_v']=a[1].get('_v',0)+1;save(c[4:],'admin',a[1])
                    else:db.execute('delete from bind where client=?',(c,))
                    db.execute('insert into log values(?,?,?,?,?)',(ts,'unbind'+who_,c,None,None));db.commit();return s.send(200,b'{}')
                return s.send(404,b'{}')
            if ro=='new' and p=='/api/claim':
                TRY[u]=[q for q in TRY.get(u,[]) if q>t-3600]
                if len(TRY[u])>=5:return s.send(429,b'{}')
                TRY[u].append(t)
                i=db.execute('select client from inv where tok=? and exp>?',(str(b.get('tok')),t)).fetchone();ph=digits(b.get('phone'));tgt=i and i[0]
                if tgt and tgt.startswith('adm:'):
                    a=row(tgt[4:]);c=a and a[0]=='admin' and not a[1].get('disabled') and a[1]
                    if c and ph and digits(c.get('phone'))==ph:
                        c['tg']=u;c['_v']=c.get('_v',0)+1;save(tgt[4:],'admin',c);db.execute('delete from inv where tok=?',(str(b.get('tok')),))
                        db.execute('insert into log values(?,?,?,?,?)',(ts,'login@'+c.get('name','')[:40],tgt,None,None));db.commit()
                        say(f"Администратор {c.get('name')} вошёл в приложение.");return s.send(200,b'{}')
                else:
                    c=tgt and doc(tgt)
                    if c and ph and digits(c.get('phone'))==ph:
                        db.execute('insert or replace into bind values(?,?)',(u,tgt));db.execute('delete from inv where tok=?',(str(b.get('tok')),));db.commit()
                        say(f"Клиент {c.get('name')} вошёл в приложение.");return s.send(200,b'{}')
                if len(TRY[u])==3:say(f'Неудачные попытки входа (Telegram ID {u}).')
                return s.send(403,b'{}')
            if ro=='client' and p=='/api/defer' and ID.fullmatch(str(b.get('id',''))):
                d=doc(b['id']);today=dt.datetime.now(MSK).date()
                if not d or d.get('client')!=x or d.get('status')!='active' or any(q.get('by')=='client' for q in d.get('defer',[])):return s.send(409,b'{}')
                k=first_unpaid(d)
                if not k or due(d,k)<today:return s.send(409,b'{}')
                n2=(doc('cfg') or {}).get('dd',2);d['shift']=d.get('shift',0)+n2;d.setdefault('defer',[]).append({'date':str(today),'days':n2,'by':'client'});d['_v']=d.get('_v',0)+1
                save(b['id'],'deal',d)
                db.execute('insert into log values(?,?,?,?,?)',(ts,'defer-client',b['id'],None,None));db.commit()
                say(f"Клиент {(doc(x) or {}).get('name')} взял отсрочку на {n2} дн.");defer_msg(d);return s.send(200,b'{}')
        return s.send(403,b'{}')
def morning(t):
    """10:00 messages for date t: the owner's summary and clients' reminders (the day before and on the day of payment).
    Each message goes out once (ntf keeps what was sent) and only while its switch in Settings is on."""
    out=[]
    with L:
        cf=doc('cfg') or {}
        ds=[(i,json.loads(d)) for i,d in db.execute("select id,data from docs where kind='deal'").fetchall()]
        def once(k):
            if db.execute('select 1 from ntf where k=?',(k,)).fetchone():return False
            db.execute('insert into ntf values(?)',(k,));return True
        if cf.get('nown') and once(f'{t}:daily'):
            c=due_today([d for _,d in ds],t);out.append((OWNER,f'Сегодня платят клиентов: {c}' if c else 'Сегодня платежей нет'))
        if cf.get('ncli'):
            for i,d in ds:
                if d.get('status')!='active':continue
                x=nxt(d)
                if not x:continue
                dd=due(d,x['k']);g=(dd-t).days
                if g in(0,1) and once(f"{t}:rem:{i}:{x['k']}:{dd}:{g}"):
                    N=len(sched(d));txt=(f"Напоминание: завтра, {dm(dd)}, платёж {rub(x['amt'])} (период {x['k']} из {N})." if g else f"Сегодня день оплаты: {rub(x['amt'])} (период {x['k']} из {N}).")
                    for (g2,) in db.execute('select tg from bind where client=?',(d.get('client'),)).fetchall():out.append((g2,txt))
        db.execute('delete from ntf where k<?',(str(t-dt.timedelta(days=60)),));db.commit()
    for c,x in out:push(c,x)
def job():
    last=None
    while 1:
        n=dt.datetime.now(MSK);key=(n.date(),n.hour)
        if key!=last and n.hour in(3,10):
            last=key
            try:
                if n.hour==3:
                    with L:snap('app')
                else:morning(n.date())
            except Exception as e:print(e)
        time.sleep(30)
def migrate():
    """One-time: administrators who could give early payments / deferrals also get the new right «Неустойка»."""
    with L:
        if db.execute("select 1 from ntf where k='mig:pen'").fetchone():return
        for i,d in db.execute("select id,data from docs where kind='admin'").fetchall():
            d=json.loads(d)
            if 'early' in d.get('perms',[]) and 'pen' not in d['perms']:d['perms']=[q for q in PERMS if q in d['perms']+['pen']];save(i,'admin',d)
        db.execute("insert into ntf values('mig:pen')");db.commit()
if __name__=='__main__':
    migrate()
    threading.Thread(target=job,daemon=True).start()
    threading.Thread(target=botname,daemon=True).start()
    ThreadingHTTPServer(('',int(os.environ.get('PORT','8080'))),H).serve_forever()
