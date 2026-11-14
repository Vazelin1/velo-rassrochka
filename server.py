import os,re,json,hmac,hashlib,sqlite3,threading,time,secrets,math,copy,urllib.request,urllib.error,urllib.parse,datetime as dt
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
TOK=os.environ['BOT_TOKEN'];OWNER=int(os.environ['OWNER_ID'])
MSK=dt.timezone(dt.timedelta(hours=3));L=threading.Lock()
TQB=os.environ.get('TOCHKA_BASE','https://enter.tochka.com/uapi');MOCK=os.environ.get('TOCHKA_MOCK')=='1'
IMG={}
DATA=os.environ.get('DATA_DIR','/data');BK=DATA+'/backups';os.makedirs(BK,exist_ok=True);TGB=os.environ.get('TG_BASE','https://api.telegram.org')
db=sqlite3.connect(DATA+'/app.db',check_same_thread=False)
db.executescript("create table if not exists docs(id text primary key,kind text,data text);create table if not exists log(ts text,act text,id text,old text,new text);create table if not exists inv(tok text primary key,client text,exp real);create table if not exists bind(tg integer primary key,client text);create table if not exists ntf(k text primary key)")
FAIL={};TRY={};BOT=[os.environ.get('BOT_USERNAME','').lstrip('@') or None]
HD={'X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','Strict-Transport-Security':'max-age=31536000',
'Content-Security-Policy':"default-src 'self'; script-src 'self' 'unsafe-inline' https://telegram.org; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'self' https://*.telegram.org"}
KINDS=('client','bike','deal','cfg','admin','qr','unk','bill','tch')
SRV=('qr','unk','bill','tch')  # written only by the server's own actions, never through /api/put
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
def D(s):return dt.date.fromisoformat(s)
def digits(p):return re.sub(r'\D','',p or '')[-10:]
def first_unpaid(d):
    for k in range(1,d['n']+1):
        if str(k) not in d['paid']:return k
def due(d,k):return dt.date.fromisoformat(d['start'])+dt.timedelta(days=0 if k==1 else (30 if d['type']=='m' else 7)*(k-1)-1+d.get('shift',0))
def sched(d):
    """Payment schedule exactly as the app computes it (static/calc.js): due dates, and early payments shorten it from the end."""
    n=d['n'];paid=d.get('paid') or {};P=30 if d['type']=='m' else 7
    r=[{'k':k,'due':d['start'] if k==1 else (D(d['start'])+dt.timedelta(days=P*(k-1)-1+(0 if str(k) in paid else (d.get('shift') or 0)))).isoformat(),'amt':d['last'] if k==n else d['pay']} for k in range(1,n+1)]
    e=sum((x.get('amt') or 0) for x in d.get('early') or [])
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
def safe_link(v):
    """A link to the owner's Telegram / Max account for the client screen: only plain https links are passed on."""
    v=str(v or '').strip()
    return v if re.fullmatch(r'https://[^\s<>"\'\\]{3,300}',v) else ''
def mine(cid):
    c=doc(cid) or {};out=[]
    for i,d in db.execute("select id,data from docs where kind='deal'").fetchall():
        d=json.loads(d)
        if d['client']==cid:
            out.append({k:d.get(k) for k in('n','start','pay','last','paid','early','shift','defer','pen','status','contract','type','debt','dpays','pw','np')}|{'id':i,'bike':(doc(d['bike']) or {}).get('name','')})
    ids={o['id'] for o in out};bills=[{'id':i,'deal':z['deal'],'amt':z['amt'],'kind':z['kind'],'ts':z.get('ts')} for i,z in docs_of('bill') if z.get('status')=='open' and z.get('deal') in ids]
    cf=doc('cfg') or {}
    return {'role':'client','name':c.get('name',''),'deals':out,'dd':cf.get('dd',2),'qr':bool(tq()),'bills':bills,'ct':{'tg':safe_link(cf.get('ctg')),'mx':safe_link(cf.get('cmx'))}}
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
        return json.dumps({'v':1,'ts':dt.datetime.now(MSK).isoformat(),'docs':[{'id':i,'kind':k,'data':json.loads(x)} for i,k,x in db.execute("select id,kind,data from docs where kind!='tch'")],
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
            if k=='tch':continue
            if not isinstance(i,str) or not ID.fullmatch(i) or k not in KINDS or not isinstance(d,dict) or i in seen:return 400,'Файл повреждён: неверная запись.'
            seen.add(i);rows.append((i,k,json.dumps(d)))
        bi=[(int(a),str(c)) for a,c in bind if ID.fullmatch(str(c))]
        lg=[tuple(None if y is None else str(y) for y in r) for r in lg if isinstance(r,list) and len(r)==5][-100000:]
    except Exception:return 400,'Файл повреждён.'
    with L:
        snap('pre-restore')
        try:
            empty=not db.execute('select 1 from log limit 1').fetchone();keep=db.execute("select id,kind,data from docs where kind='tch'").fetchall()
            db.execute('delete from docs');db.execute('delete from bind');db.execute('delete from inv')
            db.executemany('insert into docs values(?,?,?)',rows+[tuple(z) for z in keep]);db.executemany('insert or replace into bind values(?,?)',bi)
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
# ---------- calculation on the server: mirrors static/calc.js and info() of the app (tests/calc_parity.py compares them) ----------
class Bad(Exception):pass
def add(s,n):return (D(s)+dt.timedelta(days=n)).isoformat()
def diff(a,b):return (D(a)-D(b)).days
def tod():return dt.datetime.now(MSK).date().isoformat()
def nid():return secrets.token_hex(6)
def cfgv(k,dflt):
    v=(doc('cfg') or {}).get(k);return dflt if v is None else v
def penalty(a,days,r):return int(math.floor(a*(0.9 if r is None else r)/100*days+0.5))
def pdays(b,T,d):
    """Days of penalty from the last day without penalty b up to T (pw: written off on that date, np: periods when accrual is off)."""
    if d.get('pw') and d['pw']>b:b=d['pw']
    n=diff(T,b)
    if n<=0:return 0
    for f in d.get('np') or []:
        lo=max(add(b,1),f[0]);e=add(f[1],-1) if f[1] else T;hi=min(e,T);o=diff(hi,lo)+1
        if o>0:n-=o
    return max(0,n)
def dstat(d,T):
    g=d.get('debt')
    if not g or not g.get('amt',0)>0:return None
    b=g['pb'] if g.get('pb') and g['pb']>g['due'] else g['due'];n=pdays(b,T,d);pe=penalty(g['amt'],n,d.get('pen'))
    return {'amt':g['amt'],'due':g['due'],'k':g['k'],'days':n,'pen':pe,'total':g['amt']+pe,'late':max(0,diff(T,g['due'])),'over':T>g['due'],'base':b}
def info(d,t=None):
    t=t or tod();sc=sched(d);P=d.get('paid') or {};un=[x for x in sc if str(x['k']) not in P];od=[x for x in un if x['due']<t];ods=[]
    for y in od:
        n=pdays(y['due'],t,d);ods.append({**y,'days':n,'pen':penalty(y['amt'],n,d.get('pen'))})
    pe=sum(y['pen'] for y in ods);g=dstat(d,t)
    return {'sc':sc,'un':un,'x':un[0] if un else None,'od':od,'ods':ods,'pen':pe,'g':g,'owe':sum(y['amt'] for y in od)+pe,'done':not un and not g}
def minpart(x):return math.ceil(x['amt']*cfgv('dmin',50)/100)
# ---------- what can be paid, and how a payment is applied to the deal ----------
def q_now(d,t):
    """«К оплате сейчас» as the client sees it: every overdue period with its penalty, or the next period when nothing is overdue."""
    I=info(d,t)
    if d.get('status')!='active' or not I['x']:return None
    if I['od']:return {'amt':I['owe'],'pen':I['pen'],'ks':[y['k'] for y in I['ods']],'items':I['ods']}
    x=I['x'];return {'amt':x['amt'],'pen':0,'ks':[x['k']],'items':[{**x,'days':0,'pen':0}]}
def q_debt(d,t):
    g=dstat(d,t) if d.get('status')=='active' else None
    return g and {'amt':g['total'],'pen':g['pen'],'g':g}
def plan_period(d,A,t):
    """A rubles paid on date t for the first unpaid period: the whole period with its penalty, or a part of it (not below dmin %,
    not while a debt is open). Returns a plan or an error text."""
    I=info(d,t);x=I['x']
    if d.get('status')!='active' or not x:return 'Нечего оплачивать.'
    pen=penalty(x['amt'],pdays(x['due'],t,d),d.get('pen'))
    if A>=x['amt']+pen:return {'k':x['k'],'pen':pen,'pay':x['amt'],'rest':0,'left':A-x['amt']-pen}
    if I['g']:return 'Пока не закрыт долг, период можно оплатить только целиком.'
    mn=minpart(x);pa=A-pen
    if pa<mn:return f'Сумма за период должна быть не меньше {rub(mn+pen)}.'
    return {'k':x['k'],'pen':pen,'pay':pa,'rest':x['amt']-pa,'left':0}
def put_paid(d,k,t,amt,pen,method,qr=None,part=False):
    p={'date':t,'amt':amt,'pen':pen,'method':method}
    if part:p['part']=1
    if qr:p['qr']=qr
    d.setdefault('paid',{})[str(k)]=p
def apply_plan(d,p,t,method,qr=None):
    put_paid(d,p['k'],t,p['pay'],p['pen'],method,qr,p['rest']>0)
    if p['rest']>0:d['debt']={'k':p['k'],'amt':p['rest'],'due':add(t,int(cfgv('dbd',3)))}
    return p['left']
def apply_debt(d,A,t,method,qr=None):
    """Money for the open debt: the penalty first, then the remainder. Returns what is left over."""
    g=dstat(d,t)
    if not g:raise Bad('Долга нет.')
    if A<=g['pen']:raise Bad(f"Сумма должна быть больше неустойки {rub(g['pen'])}.")
    pr,left=(g['amt'],A-g['total']) if A>=g['total'] else (A-g['pen'],0);rest=g['amt']-pr
    z={'date':t,'amt':pr,'pen':g['pen'],'method':method,'k':g['k'],'pv':dict(d['debt'])}
    if qr:z['qr']=qr
    d.setdefault('dpays',[]).append(z)
    if rest>0:
        d['debt']={**d['debt'],'amt':rest}
        if t>d['debt']['due']:d['debt']['pb']=t
    else:d.pop('debt',None)
    return left
def apply_money(d,kind_,A,t,method,qr=None):
    """Bills and unrecognised payments: kind_ is 'period' or 'debt'. Returns what is left over (an overpayment); raises Bad when it cannot be applied."""
    if kind_=='debt':return apply_debt(d,A,t,method,qr)
    p=plan_period(d,A,t)
    if isinstance(p,str):raise Bad(p)
    left=apply_plan(d,p,t,method,qr)
    if left>0 and dstat(d,t):
        try:left=apply_debt(d,left,t,method,qr)
        except Bad:pass
    return left
def lg(d):return {k:v for k,v in d.items() if k not in('img','jwt')}
def put_srv(i,k,d,act,by='',old=None):
    """Write a document from a server-side action (a QR payment, a bill): bumps _v for deals so that stale screens get a conflict."""
    if k=='deal':d['_v']=d.get('_v',0)+1
    save(i,k,d);db.execute('insert into log values(?,?,?,?,?)',(dt.datetime.now(MSK).isoformat(),act+(('@'+by) if by else ''),i,old and strip(json.dumps(lg(old))),strip(json.dumps(lg(d)))))
def docs_of(k):
    return [(i,json.loads(x)) for i,x in db.execute('select id,data from docs where kind=?',(k,)).fetchall()]
# ---------- Tochka (SBP QR) ----------
# The owner types the JWT token, the merchant id (merchantId) and the account id (accountId, «счёт/БИК») in Settings.
def tq():
    t=doc('tch') or {}
    if MOCK:return {'mock':1,**t}
    return t if t.get('jwt') and t.get('merchant') and t.get('account') else None
def tochka(t,method,path,body=None):
    rq=urllib.request.Request(TQB+path,json.dumps(body).encode() if body is not None else None,{'Authorization':'Bearer '+t['jwt'],'Content-Type':'application/json'},method=method)
    return json.load(urllib.request.urlopen(rq,timeout=25))
def qr_make(t,amt,purpose):
    """Registers a dynamic QR for amt rubles that is valid until the end of the day (the amount goes to the bank in kopecks, the lifetime in minutes)."""
    if t.get('mock'):return {'id':'mock'+nid(),'payload':'https://qr.nspk.ru/MOCK'+nid(),'img':None}
    n=dt.datetime.now(MSK);ttl=max(5,int((dt.datetime.combine(n.date()+dt.timedelta(days=1),dt.time(),MSK)-n).total_seconds()//60))
    try:
        r=tochka(t,'POST',f"/sbp/v1.0/qr-code/merchant/{urllib.parse.quote(t['merchant'],safe='')}/{t['account']}",{'Data':{'amount':int(round(amt*100)),'currency':'RUB','paymentPurpose':purpose[:140],
            'qrcType':'02','ttl':ttl,'imageParams':{'width':400,'height':400,'mediaType':'image/png'}}})['Data']
        return {'id':r['qrcId'],'payload':r['payload'],'img':(r.get('image') or {}).get('content')}
    except urllib.error.HTTPError as e:
        print('tochka qr',e.code,e.read()[:300])
        raise Bad('Точка не приняла токен. Проверьте его в Настройках.' if e.code in(401,403) else 'Точка не нашла торговую точку или счёт. Проверьте их ID в Настройках.' if e.code in(400,404) else 'Точка не ответила, попробуйте ещё раз.')
    except Exception as e:
        print('tochka qr',e);raise Bad('Точка не ответила, попробуйте ещё раз.')
def qr_paid(t,ids):
    """Which of the QR codes are paid (the bank's answer)."""
    if t.get('mock') or not ids:return set()
    r=tochka(t,'GET','/sbp/v1.0/qr-codes/'+','.join(ids)+'/payment-status')['Data']
    return {x.get('qrcId') for x in r.get('paymentList',[]) if x.get('status')=='Accepted'}
def qr_amount(d,kind_,t,bill=None):
    """(amount, penalty inside it, periods) of a QR of this kind right now; raises Bad when there is nothing to pay."""
    if kind_=='now':
        z=q_now(d,t)
        if not z:raise Bad('Нечего оплачивать.')
        return z['amt'],z['pen'],z['ks']
    if kind_=='debt':
        z=q_debt(d,t)
        if not z:raise Bad('Долга нет.')
        return z['amt'],z['pen'],None
    if kind_=='bill':
        if not bill or bill.get('status')!='open':raise Bad('Платёж уже закрыт.')
        if bill['kind']=='period':
            p=plan_period(d,bill['amt'],t)
            if isinstance(p,str):raise Bad(p)
        elif not q_debt(d,t):raise Bad('Долга нет.')
        return bill['amt'],0,None
    raise Bad('Неверный запрос.')
def qr_request(u,cl,b):
    """A QR for a deal, asked by the client (cl) or by the owner / an administrator with the right «pay». The bank is called without the lock."""
    with L:
        ro,x=role(u);t=tod()
        if cl:
            if ro!='client':raise Bad('Нет доступа.')
        elif not(ro=='owner' or (ro=='admin' and 'pay' in x[1].get('perms',[]))):raise Bad('Нет доступа.')
        tc=tq()
        if not tc:raise Bad('Оплата по QR не подключена.')
        i=str(b.get('deal',''));d=ID.fullmatch(i) and doc(i)
        if not d or d.get('status')!='active' or (cl and d.get('client')!=x):raise Bad('Выкуп не найден.')
        k=b.get('kind');bid=str(b.get('bill') or '');bill=(doc(bid) if ID.fullmatch(bid) else None) if k=='bill' else None
        if bill and bill.get('deal')!=i:bill=None
        amt,pe,ks=qr_amount(d,k,t,bill)
        for j,q in docs_of('qr'):
            if q.get('deal')==i and q.get('status')=='open' and q.get('date')==t and q.get('kind')==k and q.get('amt')==amt and q.get('bill')==(bid if bill else None):return {'qr':j}
        purpose=f"Выкуп электровелосипеда, договор {d.get('contract') or '—'}, {(doc(d.get('client')) or {}).get('name','')}"
    m=qr_make(tc,amt,purpose)
    with L:
        d=doc(i);bill=doc(bid) if bill else None
        if not d or qr_amount(d,k,t,bill)[0]!=amt or tod()!=t:raise Bad('Данные изменились, откройте экран заново.')
        qid=nid();put_srv(qid,'qr',{'deal':i,'kind':k,'amt':amt,'pen':pe,'ks':ks,'bill':bid if bill else None,'date':t,'status':'open','tid':m['id'],'payload':m['payload'],'img':m['img'],'ts':dt.datetime.now(MSK).isoformat(timespec='seconds')},'qr','' if cl else str((x[1].get('name') if ro=='admin' else 'owner'))[:40])
        db.commit();return {'qr':qid}
def on_paid(qid,q):
    """The bank confirmed a QR payment. It is credited automatically when nothing changed since the QR was made (same day, same amount);
    otherwise it goes to «Не распознано». Call with the lock held."""
    if q.get('status')!='open':return
    old=dict(q);q['status']='paid';put_srv(qid,'qr',q,'qr-paid','',old)
    d=doc(q['deal']);t=tod();left=q['amt'];why='Оплата пришла после изменений в выкупе или не в тот день.';ok=False
    if d and d.get('status')=='active' and t==q['date']:
        d2=copy.deepcopy(d)
        try:
            if q['kind']=='now':
                z=q_now(d2,t)
                if z and z['amt']==q['amt'] and z['ks']==q.get('ks'):
                    for y in z['items']:put_paid(d2,y['k'],t,y['amt'],y['pen'],'СБП',qid)
                    left=0;ok=True
            elif q['kind']=='debt':
                z=q_debt(d2,t)
                if z and z['amt']==q['amt']:left=apply_debt(d2,q['amt'],t,'СБП',qid);ok=True
            elif q['kind']=='bill':
                b=doc(q.get('bill') or '')
                if b and b.get('status')=='open' and b.get('amt')==q['amt']:
                    left=apply_money(d2,b['kind'],q['amt'],t,'СБП',qid);ok=True
                    ob=dict(b);b['status']='paid';b['paid']=dt.datetime.now(MSK).isoformat(timespec='seconds');put_srv(q['bill'],'bill',b,'bill-paid','',ob)
        except Bad as e:ok=False;why=str(e)
        if ok:put_srv(q['deal'],'deal',d2,'pay-qr','',d)
    c=(doc((d or {}).get('client','')) or {}).get('name','')
    if ok and left<=0:say(f"Оплата по QR: {c}, {rub(q['amt'])}.")
    else:
        put_srv(nid(),'unk',{'ts':dt.datetime.now(MSK).isoformat(timespec='seconds'),'amt':left if ok else q['amt'],'qr':qid,'deal':q['deal'],'status':'open','why':'Переплата сверх суммы к оплате.' if ok else why},'unk')
        say(f"Платёж по QR не распознан: {c}, {rub(left if ok else q['amt'])}. Разберите в приложении.")
PL_LAST=[0]
def poll():
    with L:
        t=tq()
        if not t:return
        lo=add(tod(),-2);op={q['tid']:i for i,q in docs_of('qr') if q.get('status')=='open' and q.get('date','')>=lo}
    if not op:return
    try:paid=qr_paid(t,list(op))
    except Exception as e:print('poll',e);return
    with L:
        for tid in paid:
            i=op.get(tid);q=i and doc(i)
            if q:on_paid(i,q)
        db.commit()
def poll_soon():
    """Called while a client looks at a QR: asks the bank at most once in 10 seconds, so the payment shows within seconds, not minutes."""
    if time.time()-PL_LAST[0]>10:PL_LAST[0]=time.time();threading.Thread(target=poll,daemon=True).start()
# ---------- bills, unrecognised payments, Tochka settings (the owner and administrators with the right «pay») ----------
def owner_act(p,b,ro,x,P):
    """Returns the reply. Called with the lock held; raises Bad."""
    t=tod();by=(str(x[1].get('name',''))[:40] if ro=='admin' else '')
    if p=='/api/tochka':
        if ro!='owner':raise Bad('Нет доступа.')
        old=doc('tch') or {};n=dict(old)
        if b.get('clear'):n={}
        else:
            mr=str(b.get('merchant') or '').strip();ac=str(b.get('account') or '').strip().replace(' ','')
            if not re.fullmatch(r'[\w-]{1,60}',mr,re.A) or not re.fullmatch(r'[\w/-]{1,80}',ac,re.A):raise Bad('Проверьте ID торговой точки и счёта: только буквы, цифры, дефис и косая черта.')
            n.update(merchant=mr,account=ac)
            if b.get('jwt'):n['jwt']=str(b['jwt']).strip()[:5000]
            n.setdefault('hook',secrets.token_urlsafe(18))
        db.execute('insert or replace into docs values(?,?,?)',('tch','tch',json.dumps(n)))
        db.execute('insert into log values(?,?,?,?,?)',(dt.datetime.now(MSK).isoformat(),'tochka','tch',json.dumps({k:('***' if k=='jwt' else v) for k,v in old.items()}),json.dumps({k:('***' if k=='jwt' else v) for k,v in n.items()})));db.commit();return {}
    if p=='/api/mockpay':
        if not MOCK or ro!='owner':raise Bad('Нет доступа.')
        q=doc(str(b.get('qr','')))
        if not q:raise Bad('QR не найден.')
        on_paid(b['qr'],q);db.commit();return {}
    if ro=='admin' and 'pay' not in P:raise Bad('Нет доступа.')
    if p=='/api/bill':
        if b.get('do'):
            i=str(b.get('id',''));z=ID.fullmatch(i) and doc(i)
            if not z or z.get('status')!='open':raise Bad('Платёж уже закрыт.')
            old=dict(z)
            if b['do']=='void':z['status']='void';put_srv(i,'bill',z,'bill-void',by,old);db.commit();return {}
            if b['do']=='paid':
                m=b.get('method');d=doc(z['deal'])
                if m not in('наличные','СБП','перевод') or not d:raise Bad('Выберите способ оплаты.')
                d2=copy.deepcopy(d);left=apply_money(d2,z['kind'],z['amt'],t,m)
                put_srv(z['deal'],'deal',d2,'bill-paid',by,d);z['status']='paid';z['paid']=dt.datetime.now(MSK).isoformat(timespec='seconds');z['method']=m;put_srv(i,'bill',z,'bill-paid',by,old)
                if left>0:put_srv(nid(),'unk',{'ts':z['paid'],'amt':left,'deal':z['deal'],'status':'open','why':'Переплата сверх суммы к оплате.'},'unk',by)
                db.commit();return {}
            raise Bad('Неверный запрос.')
        i=str(b.get('deal',''));d=ID.fullmatch(i) and doc(i);k=b.get('kind')
        if not d or d.get('status')!='active':raise Bad('Выкуп не найден.')
        try:A=int(round(float(b.get('amt'))))
        except Exception:raise Bad('Введите сумму.')
        if A<1 or A>10000000:raise Bad('Введите сумму.')
        if any(z.get('deal')==i and z.get('status')=='open' for _,z in docs_of('bill')):raise Bad('У клиента уже есть выставленный платёж. Сначала отмените его или дождитесь оплаты.')
        if k=='period':
            pl=plan_period(d,A,t)
            if isinstance(pl,str):raise Bad(pl)
            if pl['left']>0:raise Bad(f"Сумма больше, чем нужно за период: не больше {rub(A-pl['left'])}.")
        elif k=='debt':
            g=dstat(d,t)
            if not g:raise Bad('Долга нет.')
            if A<=g['pen']:raise Bad(f"Сумма должна быть больше неустойки {rub(g['pen'])}.")
            if A>g['total']:raise Bad(f"Сумма больше долга: не больше {rub(g['total'])}.")
        else:raise Bad('Неверный запрос.')
        bid=nid();put_srv(bid,'bill',{'deal':i,'kind':k,'amt':A,'status':'open','ts':dt.datetime.now(MSK).isoformat(timespec='seconds'),'by':by or 'owner'},'bill',by);db.commit();return {'id':bid}
    if p=='/api/unk':
        i=str(b.get('id',''));z=ID.fullmatch(i) and doc(i)
        if not z or z.get('status')!='open':raise Bad('Платёж уже разобран.')
        old=dict(z)
        if b.get('do')=='done':z['status']='done';z['note']=str(b.get('note') or '')[:200];put_srv(i,'unk',z,'unk-done',by,old);db.commit();return {}
        if b.get('do')=='apply':
            d=doc(z.get('deal',''))
            if not d or b.get('kind') not in('period','debt'):raise Bad('Выберите, куда засчитать платёж.')
            d2=copy.deepcopy(d);left=apply_money(d2,b['kind'],z['amt'],t,'СБП',z.get('qr'))
            put_srv(z['deal'],'deal',d2,'unk-apply',by,d);z['status']='applied';put_srv(i,'unk',z,'unk-apply',by,old)
            if left>0:put_srv(nid(),'unk',{'ts':dt.datetime.now(MSK).isoformat(timespec='seconds'),'amt':left,'deal':z['deal'],'status':'open','why':'Переплата сверх суммы к оплате.'},'unk',by)
            db.commit();return {}
    raise Bad('Неверный запрос.')
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
                    pay=ro=='owner' or 'pay' in x[1].get('perms',[])
                    r=[{'kind':k,'id':i,'data':vw(k,json.loads(d),f)} for i,k,d in db.execute('select id,kind,data from docs') if (ro=='owner' or k!='admin') and k not in('qr','tch') and (pay or k not in('unk','bill'))]
                    tc=doc('tch') or {};r.append({'kind':'tch','id':'tch','data':{'on':bool(tq()),'merchant':tc.get('merchant',''),'account':tc.get('account',''),'jwt':bool(tc.get('jwt')),'hook':tc.get('hook','')} if ro=='owner' else {'on':bool(tq())}})
                elif s.path=='/api/log':
                    if ro!='owner':return s.send(403,b'{}')
                    r=[list(q) for q in db.execute('select ts,act,id,old,new from log order by rowid desc limit 250')]
                elif ro=='owner':r={'role':'owner','backup':bget()}
                elif ro=='admin':r={'role':'admin','name':x[1].get('name',''),'perms':[q for q in x[1].get('perms',[]) if q in PERMS],'fin':hasfin(x[1].get('perms',[]))}
                elif ro=='client':r=mine(x)
                else:r={'role':ro}
            return s.send(200,json.dumps(r).encode())
        if s.path.startswith('/api/qr/'):
            u=s.user()
            if u is None:return s.send(403,b'{}')
            with L:
                ro,x=role(u);rw=ID.fullmatch(s.path[8:]) and row(s.path[8:]);q=rw and rw[0]=='qr' and rw[1]
                if not q:return s.send(404,b'{}')
                dd=doc(q['deal']) or {}
                if not(ro in('owner','admin') or (ro=='client' and dd.get('client')==x)):return s.send(403,b'{}')
                if q.get('status')=='open':poll_soon()
                return s.send(200,json.dumps({k:q.get(k) for k in('amt','kind','pen','payload','img','status','date')}).encode())
        if s.path.startswith('/img/'):
            t=time.time()
            for a in [a for a,(e,_) in IMG.items() if e<t]:IMG.pop(a,None)
            z=IMG.get(s.path[5:])
            if not z:return s.send(404,b'')
            return s.send(200,z[1],'image/png',{'Content-Disposition':'attachment; filename="qr-oplata.png"','Cache-Control':'no-store'})
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
        if s.path.startswith('/hook/tochka/'):
            # the bank says a payment arrived: the body is not trusted, the paid QR codes are asked from the bank
            with L:tc=(doc('tch') or {}).get('hook')
            if not tc or not hmac.compare_digest(s.path[13:],tc):return s.send(404,b'')
            s.rfile.read(min(int(s.headers.get('Content-Length',0)),100000));threading.Thread(target=poll,daemon=True).start();return s.send(200,b'{}')
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
        if s.path in('/api/qr','/api/cqr'):
            try:return s.send(200,json.dumps(qr_request(u,s.path=='/api/cqr',b)).encode())
            except Bad as e:return s.send(400,json.dumps({'err':str(e)}).encode())
        if s.path=='/api/qrimg':
            # the picture of a QR drawn in the app: kept for 10 minutes so that Telegram can download it
            import base64
            with L:ro_,_=role(u)
            if ro_ not in('owner','admin','client'):return s.send(403,b'{}')
            try:png=base64.b64decode(str(b.get('png','')).split(',')[-1],validate=True)
            except Exception:return s.send(400,b'{}')
            if not png.startswith(b'\x89PNG') or len(png)>400000:return s.send(400,b'{}')
            if len(IMG)>200:IMG.clear()
            k=secrets.token_urlsafe(16);IMG[k]=(t+600,png);return s.send(200,json.dumps({'url':'/img/'+k}).encode())
        with L:
            ro,x=role(u)
            if ro in('owner','admin'):
                P=set(x[1].get('perms',[])) if ro=='admin' else None
                if p in('/api/bill','/api/unk','/api/tochka','/api/mockpay'):
                    try:return s.send(200,json.dumps(owner_act(p,b,ro,x,P)).encode())
                    except Bad as e:return s.send(400,json.dumps({'err':str(e)}).encode())
                who_=ro=='admin' and '@'+str(x[1].get('name',''))[:40] or ''
                if p in('/api/put','/api/del'):
                    if p=='/api/del' and ro!='owner':return s.send(403,b'{}')
                    i=str(b.get('id',''))
                    if not ID.fullmatch(i):return s.send(400,b'{}')
                    r=db.execute('select kind,data from docs where id=?',(i,)).fetchone();old=r and json.loads(r[1])
                    if p=='/api/put':
                        k=b.get('kind');new=b.get('data')
                        if k not in KINDS or k in SRV or not isinstance(new,dict) or (r and r[0]!=k):return s.send(400,b'{}')
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
        if time.time()-PL_LAST[0]>170:
            PL_LAST[0]=time.time()
            try:poll()
            except Exception as e:print('poll',e)
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
