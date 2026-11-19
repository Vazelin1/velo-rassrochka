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
KINDS=('client','bike','deal','cfg','admin','qr','unk','bill','tch','reschedule')
SRV=('qr','unk','bill','tch','reschedule')  # written only by the server's own actions, never through /api/put
PERMS=('pay','early','pen','clients','deals','bikes','reports')
FINP={'deals','bikes','reports'}  # rights that let an administrator see prices, purchase costs and profit
HID={'deal':('total','tax','acq','cost','disc','mk','extras','down','refund'),'bike':('cost','exp','wo')}
PUBCFG=('id','dd','pen','dmin','dbd','multi_discount')
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
    x=nxt(d)
    return x and x['k']
def due(d,k):return D(next(x['due'] for x in sched(d) if x['k']==k))
def sched(d):
    """Payment schedule exactly as the app computes it (static/calc.js): due dates, and early payments shorten it from the end."""
    n=d['n'];paid=d.get('paid') or {};P=30 if d['type']=='m' else 7
    if isinstance(d.get('schedule'),list):
        return [{**x,'due':(paid.get(str(x['k'])) or {}).get('due') or add(x['due'],0 if str(x['k']) in paid else (d.get('shift') or 0))} for x in d['schedule'] if x['amt']>0 or str(x['k']) in paid]
    r=[{'k':k,'due':(paid.get(str(k)) or {}).get('due') or (d['start'] if k==1 else (D(d['start'])+dt.timedelta(days=P*(k-1)-1+(0 if str(k) in paid else (d.get('shift') or 0)))).isoformat()),'amt':d['last'] if k==n else d['pay']} for k in range(1,n+1)]
    e=sum((x.get('amt') or 0) for x in d.get('early') or [])
    consumed=sum(max(0,x['amt']-paid[str(x['k'])]['amt']) for x in r if str(x['k']) in paid and not paid[str(x['k'])].get('part'))
    e=max(0,e-consumed)
    for x in reversed(r):
        if e<=0:break
        if str(x['k']) in paid:continue
        c=min(e,x['amt']);x['amt']-=c;e-=c
    for x in r:
        payment=paid.get(str(x['k']))
        if payment and not payment.get('part'):x['amt']=payment['amt']
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
            out.append({k:d.get(k) for k in('n','start','pay','last','paid','early','shift','defer','pen','status','contract','type','debt','dpays','pw','np','schedule','bonuses','completed_at','closed','signed_at','_v')}|{'id':i,'bike':(doc(d['bike']) or {}).get('name','')})
    ids={o['id'] for o in out};bills=[{'id':i,'deal':z['deal'],'amt':z['amt'],'kind':z['kind'],'ts':z.get('ts')} for i,z in docs_of('bill') if z.get('status')=='open' and z.get('deal') in ids]
    cf=doc('cfg') or {}
    requests=[{**z,'id':i} for i,z in docs_of('reschedule') if z.get('deal') in ids]
    return {'role':'client','name':c.get('name',''),'deals':out,'requests':requests,'dd':cf.get('dd',2),'dmin':max(50,cf.get('dmin',50)),'dbd':cf.get('dbd',3),'multi_discount':cf.get('multi_discount',1.5),'qr':bool(tq()),'bills':bills,'ct':{'tg':safe_link(cf.get('ctg')),'mx':safe_link(cf.get('cmx'))}}
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
def minpart(x):return math.ceil(x['amt']*max(50,cfgv('dmin',50))/100)

def whole(value,label='сумму'):
    try:
        number=float(value)
    except (ValueError,TypeError):
        raise Bad(f'Введите {label}.')
    if isinstance(value,bool) or not math.isfinite(number) or number!=int(number) or abs(number)>10000000:
        raise Bad(f'Введите {label} в целых рублях.')
    return int(number)

def valid_date(value):
    try:
        if not isinstance(value,str) or D(value).isoformat()!=value:raise ValueError()
        return value
    except (ValueError,TypeError):
        raise Bad('Проверьте дату.')

def payment_quote(d,options,t,settings=None):
    if not isinstance(options,dict):raise Bad('Выберите способ оплаты.')
    settings=settings if settings is not None else (doc('cfg') or {})
    unpaid=[x for x in sched(d) if str(x['k']) not in (d.get('paid') or {})]
    if d.get('status')!='active' or not unpaid:raise Bad('Сейчас нечего оплачивать.')
    minimum=max(50,min(100,settings.get('dmin',50)))
    mode=options.get('mode','periods')
    if mode=='part':
        if dstat(d,t):raise Bad('Сначала погасите остаток предыдущего платежа.')
        x=unpaid[0];amount=whole(options.get('amount'));mn=math.ceil(x['amt']*minimum/100)
        if not mn<=amount<x['amt']:raise Bad(f"Часть платежа должна быть от {mn} до {x['amt']-1} ₽.")
        pe=penalty(x['amt'],pdays(x['due'],t,d),d.get('pen'))
        return {'mode':mode,'date':t,'count':1,'items':[{**x,'amt':amount,'pen':pe}],
                'principal':amount,'pen':pe,'total':amount+pe,'bonus':0,'rate':0,'reductions':[],
                'rest':x['amt']-amount,'debtDue':add(t,settings.get('dbd',3))}
    if mode!='periods':raise Bad('Выберите способ оплаты.')
    count=whole(options.get('count',1),'количество платежей')
    if not 1<=count<=len(unpaid):raise Bad('Выберите количество платежей.')
    selected=unpaid[:count];selected_sum=sum(x['amt'] for x in selected);future=sum(x['amt'] for x in unpaid[count:])
    rate=float(settings.get('multi_discount',1.5)) if count>=2 else 0
    if not math.isfinite(rate) or not 0<=rate<=100:raise Bad('Проверьте ставку скидки.')
    lo,hi=0,selected_sum
    while lo<hi:
        cash=(lo+hi)//2
        if cash+max(0,penalty(cash,1,rate)-future)>=selected_sum:hi=cash
        else:lo=cash+1
    principal=lo;bonus=min(penalty(principal,1,rate),selected_sum+future-principal)
    reductions=[];left=bonus
    for x in reversed(unpaid):
        if left<=0:break
        amount=min(left,x['amt']);reductions.append({'k':x['k'],'amt':amount});left-=amount
    by_key={x['k']:x['amt'] for x in reductions}
    items=[{**x,'amt':x['amt']-by_key.get(x['k'],0),'pen':penalty(x['amt'],pdays(x['due'],t,d),d.get('pen'))} for x in selected]
    pe=sum(x['pen'] for x in items)
    return {'mode':mode,'date':t,'count':count,'items':items,'principal':principal,'pen':pe,
            'total':principal+pe,'bonus':bonus,'rate':rate,'reductions':reductions,'rest':0}

def materialize_schedule(d):
    """Freeze effective amounts, including historic early credits, before editing a schedule."""
    effective={x['k']:x for x in sched(d)}
    if d.get('down') and 'down_method' not in d:
        d['down_method']=((d.get('paid') or {}).get('1') or {}).get('method','наличные')
    if isinstance(d.get('schedule'),list):
        rows=[copy.deepcopy(effective.get(x['k'],{**x,'due':add(x['due'],d.get('shift') or 0)})) for x in d['schedule']]
    else:rows=list(effective.values())
    for x in rows:
        p=(d.get('paid') or {}).get(str(x['k']))
        if p:p.setdefault('due',x['due'])
    d['schedule']=rows;d['shift']=0

def reduce_tail(d,amount):
    """Apply credit to unpaid periods, starting with the last. Return the actual credit."""
    left=amount
    for x in reversed(d['schedule']):
        if str(x['k']) in (d.get('paid') or {}):continue
        used=min(left,x['amt']);x['amt']-=used;left-=used
        if left<=0:break
    return amount-left

def restore_tail(d,amount):
    if amount<=0:return
    unpaid=[x for x in d['schedule'] if str(x['k']) not in d.get('paid',{})]
    if not unpaid:raise Bad('Для восстановления скидки сначала отмените последний платёж.')
    unpaid[-1]['amt']+=amount

def apply_payment(d,quote,method,qr=None):
    materialize_schedule(d)
    group=nid();reductions={x['k']:x['amt'] for x in quote['reductions']}
    for row_ in d['schedule']:row_['amt']-=reductions.get(row_['k'],0)
    for x in quote['items']:
        put_paid(d,x['k'],quote['date'],x['amt'],x['pen'],method,qr,quote['mode']=='part')
        d['paid'][str(x['k'])].update(group=group,due=x['due'],batch_count=quote['count'])
    if quote['rest']:
        d['debt']={'k':quote['items'][0]['k'],'amt':quote['rest'],'due':quote['debtDue']}
    if quote['bonus']:
        d.setdefault('bonuses',[]).append({'group':group,'date':quote['date'],'amt':quote['bonus'],
                                         'base':quote['principal'],'rate':quote['rate'],'ks':[x['k'] for x in quote['items']]})
    return group

def replan(d,first_due,weekly,t):
    first_due=valid_date(first_due);weekly=whole(weekly,'сумму платежа')
    if first_due<t:raise Bad('Выберите дату следующего платежа начиная с сегодняшнего дня.')
    if weekly<1:raise Bad('Введите сумму платежа в целых рублях.')
    current=sched(d);paid=d.get('paid') or {}
    future=[x for x in current if str(x['k']) not in paid and x['due']>=t]
    kept=[x for x in current if str(x['k']) in paid or x['due']<t]
    balance=sum(x['amt'] for x in future)
    if not balance:raise Bad('В графике нет будущих платежей для перерасчёта.')
    count=math.ceil(balance/weekly);step=30 if d['type']=='m' else 7
    if count>5200:raise Bad('Получается слишком длинный график. Увеличьте сумму платежа.')
    max_key=max([d.get('n',0)]+[x['k'] for x in current]);left=balance;changed=[]
    try:
        for index in range(count):
            if index<len(future):key=future[index]['k']
            else:max_key+=1;key=max_key
            amount=min(weekly,left);changed.append({'k':key,'due':add(first_due,step*index),'amt':amount});left-=amount
    except (ValueError,OverflowError):raise Bad('Конец графика выходит за допустимую дату.')
    schedule=sorted(kept+changed,key=lambda x:(x['due'],x['k']))
    return {'schedule':schedule,'balance':balance,'count':count,'pay':weekly,'first':first_due,
            'last':changed[-1]['due'],'lastAmount':changed[-1]['amt'],
            'keptOverdue':sum(x['amt'] for x in kept if str(x['k']) not in paid),'debt':(dstat(d,t) or {}).get('total',0)}

def fingerprint(d):
    fields=('status','schedule','n','start','type','pay','last','paid','early','shift','pen','pw','np','debt','dpays','bonuses')
    return hashlib.sha256(json.dumps({k:d.get(k) for k in fields},sort_keys=True).encode()).hexdigest()

def completion_notice(old,new):
    if new.get('status')!='active':return
    if not info(new)['done']:
        new.pop('completed_at',None)
        return
    if not new.get('completed_at'):
        new['completed_at']=tod()
        tell(new.get('client'),'Все платежи по выкупу внесены. Приезжайте для подписания документов и получения второго комплекта ключей. Перед приездом согласуйте время с нами.')

# ---------- what can be paid, and how a payment is applied to the deal ----------
def q_now(d,t):
    """«К оплате сейчас» as the client sees it: every overdue period with its penalty, or the next period when nothing is overdue."""
    I=info(d,t)
    if d.get('status')!='active' or not I['x']:return None
    quote=payment_quote(d,{'count':len(I['od']) or 1},t)
    return {**quote,'amt':quote['total'],'ks':[x['k'] for x in quote['items']]}
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
    due_=next((x['due'] for x in sched(d) if x['k']==k),None)
    p={'date':t,'amt':amt,'pen':pen,'method':method}
    if due_:p['due']=due_
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
    if k=='deal':completion_notice(old,d)
    if k in ('deal','bike','client'):d['_v']=d.get('_v',0)+1
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
def qr_amount(d,kind_,t,bill=None,options=None,settings=None):
    """(amount, penalty inside it, periods) of a QR of this kind right now; raises Bad when there is nothing to pay."""
    if kind_=='now':
        z=q_now(d,t)
        if not z:raise Bad('Нечего оплачивать.')
        return z['amt'],z['pen'],z['ks'],z
    if kind_=='selection':
        z=payment_quote(d,options or {},t,settings)
        return z['total'],z['pen'],[x['k'] for x in z['items']],z
    if kind_=='debt':
        z=q_debt(d,t)
        if not z:raise Bad('Долга нет.')
        return z['amt'],z['pen'],None,None
    if kind_=='bill':
        if not bill or bill.get('status')!='open':raise Bad('Платёж уже закрыт.')
        if bill['kind']=='period':
            p=plan_period(d,bill['amt'],t)
            if isinstance(p,str):raise Bad(p)
        elif not q_debt(d,t):raise Bad('Долга нет.')
        return bill['amt'],0,None,None
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
        options=b.get('options') or {}
        if not isinstance(options,dict):raise Bad('Выберите способ оплаты.')
        settings={key:cfgv(key,default) for key,default in (('multi_discount',1.5),('dmin',50),('dbd',3))}
        before=fingerprint(d)
        amt,pe,ks,quote=qr_amount(d,k,t,bill,options,settings)
        for j,q in docs_of('qr'):
            if q.get('deal')==i and q.get('status')=='open' and q.get('date')==t and q.get('kind')==k and q.get('amt')==amt and q.get('bill')==(bid if bill else None) and q.get('fingerprint')==before and q.get('quote')==quote:return {'qr':j}
        purpose=f"Выкуп электровелосипеда, договор {d.get('contract') or '—'}, {(doc(d.get('client')) or {}).get('name','')}"
    m=qr_make(tc,amt,purpose)
    with L:
        d=doc(i);bill=doc(bid) if bill else None
        if not d or fingerprint(d)!=before or qr_amount(d,k,t,bill,options,settings)[0]!=amt or tod()!=t:raise Bad('Данные изменились, откройте экран заново.')
        qid=nid();put_srv(qid,'qr',{'deal':i,'kind':k,'amt':amt,'pen':pe,'ks':ks,'quote':quote,'options':options,'settings':settings,'fingerprint':before,'bill':bid if bill else None,'date':t,'status':'open','tid':m['id'],'payload':m['payload'],'img':m['img'],'ts':dt.datetime.now(MSK).isoformat(timespec='seconds')},'qr','' if cl else str((x[1].get('name') if ro=='admin' else 'owner'))[:40])
        db.commit();return {'qr':qid}
def on_paid(qid,q):
    """The bank confirmed a QR payment. It is credited automatically when nothing changed since the QR was made (same day, same amount);
    otherwise it goes to «Не распознано». Call with the lock held."""
    if q.get('status')!='open':return
    old=dict(q);q['status']='paid';put_srv(qid,'qr',q,'qr-paid','',old)
    d=doc(q['deal']);t=tod();left=q['amt'];why='Оплата пришла после изменений в выкупе или не в тот день.';ok=False
    if d and d.get('status')=='active' and t==q['date'] and (not q.get('fingerprint') or q['fingerprint']==fingerprint(d)):
        d2=copy.deepcopy(d)
        try:
            if q.get('quote') and q['kind'] in ('now','selection'):
                quote=q['quote']
                if quote['total']==q['amt']:
                    apply_payment(d2,quote,'СБП',qid);left=0;ok=True
            elif q['kind']=='now':
                current=info(d2,t)
                items=current['ods'] if current['od'] else ([{**current['x'],'pen':0}] if current['x'] else [])
                if items and sum(y['amt']+y['pen'] for y in items)==q['amt'] and [y['k'] for y in items]==q.get('ks'):
                    for y in items:put_paid(d2,y['k'],t,y['amt'],y['pen'],'СБП',qid)
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

def action_deal(b,ro,x,permission='pay',allow_client=False):
    key=str(b.get('deal') or '')
    record=ID.fullmatch(key) and row(key)
    if not record or record[0]!='deal':raise Bad('Выкуп не найден.')
    d=record[1]
    allowed=ro=='owner' or (ro=='admin' and permission in x[1].get('perms',[]))
    if allow_client and ro=='client' and d.get('client')==x:allowed=True
    if not allowed:raise Bad('Нет доступа.')
    return key,d

def check_version(d,b):
    if b.get('version')!=d.get('_v',0):raise Bad('Данные изменились. Обновите экран и проверьте расчёт ещё раз.')

def move_payment(d,source,target,t):
    source=str(whole(source,'номер периода'));target=whole(target,'номер периода')
    payment=copy.deepcopy((d.get('paid') or {}).get(source))
    if not payment:raise Bad('Исходная оплата не найдена.')
    if str(target) in d['paid'] or target==int(source):raise Bad('Выберите неоплаченный период.')
    supplements=[copy.deepcopy(z) for z in d.get('dpays') or [] if z['k']==int(source)]
    materialize_schedule(d)
    row_=next((z for z in d['schedule'] if z['k']==target and z['amt']>0),None)
    if not row_:raise Bad('Целевой период не найден.')
    group=payment.get('group') or nid()
    bonus=next((z for z in d.get('bonuses',[]) if z['group']==group),None)
    old_bonus=bonus['amt'] if bonus else 0
    del d['paid'][source]
    original_debt=copy.deepcopy(d.pop('debt',None))
    other_debt=original_debt if original_debt and original_debt['k']!=int(source) else None
    d['dpays']=[z for z in d.get('dpays',[]) if z['k']!=int(source)]
    restore_tail(d,old_bonus)
    if bonus:d['bonuses'].remove(bonus)
    pen=penalty(row_['amt'],pdays(row_['due'],payment['date'],d),d.get('pen'))
    cash=payment['amt']+payment.get('pen',0)
    if cash<=pen:raise Bad('Суммы первой оплаты недостаточно для неустойки целевого периода на дату получения денег.')
    principal=min(row_['amt'],cash-pen);remainder=row_['amt']-principal;excess=cash-pen-principal
    put_paid(d,target,payment['date'],principal,pen,payment['method'],payment.get('qr'),remainder>0)
    d['paid'][str(target)].update(group=group,due=row_['due'],batch_count=payment.get('batch_count',1),moved_from=int(source))
    if remainder:
        original_terms=original_debt if original_debt and original_debt['k']==int(source) else (supplements[0].get('pv') if supplements else None)
        debt_due=original_terms['due'] if original_terms else add(payment['date'],int(cfgv('dbd',3)))
        d['debt']={'k':target,'amt':remainder,'due':debt_due}
    if excess:
        used=reduce_tail(d,excess)
        if used!=excess:raise Bad('Переплата превышает остаток выкупа. Выберите другой период.')
        d.setdefault('early',[]).append({'date':payment['date'],'paid':excess,'amt':excess,'method':payment['method'],'group':group,'kind':'move-credit'})
    for supplement in supplements:
        received=supplement['amt']+supplement.get('pen',0);cash+=received
        remaining_cash=received
        if dstat(d,supplement['date']):
            remaining_cash=apply_debt(d,received,supplement['date'],supplement['method'],supplement.get('qr'))
            applied=d['dpays'][-1];applied['group']=group
            principal+=applied['amt'];pen+=applied['pen']
        if remaining_cash:
            if reduce_tail(d,remaining_cash)!=remaining_cash:raise Bad('Переплата превышает остаток выкупа. Выберите другой период.')
            d.setdefault('early',[]).append({'date':supplement['date'],'paid':remaining_cash,'amt':remaining_cash,'method':supplement['method'],'group':group,'kind':'move-credit'})
            excess+=remaining_cash
    remainder=(d.get('debt') or {}).get('amt',0)
    if other_debt:
        if remainder:raise Bad('Перенос создаст второй долг. Сначала закройте текущий долг или выберите период с подходящей суммой.')
        d['debt']=other_debt
    new_bonus=0
    if bonus:
        grouped=[p for p in d['paid'].values() if p.get('group')==group]
        base=sum(p['amt'] for p in grouped)+sum(p['paid'] for p in d.get('early',[]) if p.get('group')==group)+sum(p['amt'] for p in d.get('dpays',[]) if p.get('group')==group)
        new_bonus=reduce_tail(d,penalty(base,1,bonus['rate']))
        d.setdefault('bonuses',[]).append({**bonus,'amt':new_bonus,'base':base,'ks':[int(k) for k,p in d['paid'].items() if p.get('group')==group]})
    return {'source':int(source),'target':target,'cash':cash,'principal':principal,'pen':pen,'debt':remainder,'excess':excess,'oldBonus':old_bonus,'bonus':new_bonus}

def cancel_payment(d,key):
    key=str(whole(key,'номер периода'));payment=d.get('paid',{}).get(key)
    if not payment:raise Bad('Оплата уже отменена.')
    group=payment.get('group')
    keys=[k for k,p in d['paid'].items() if group and p.get('group')==group] if group else [key]
    if any(str(z['k']) in keys for z in d.get('dpays') or []):
        raise Bad('По этому платежу есть доплаты долга. Сначала отмените их.')
    materialize_schedule(d)
    for k in keys:del d['paid'][k]
    if d.get('debt') and str(d['debt']['k']) in keys:d.pop('debt')
    bonuses=[z for z in d.get('bonuses',[]) if group and z['group']==group]
    credits=[z for z in d.get('early',[]) if group and z.get('group')==group]
    restore_tail(d,sum(z['amt'] for z in bonuses+credits))
    d['bonuses']=[z for z in d.get('bonuses',[]) if z not in bonuses]
    d['early']=[z for z in d.get('early',[]) if z not in credits]
    return len(keys)

def workflow_action(p,b,ro,x):
    """Authorised business actions run in one database transaction under L."""
    t=tod();by=str(x[1].get('name',''))[:40] if ro=='admin' else ''
    if p in ('/api/payquote','/api/pay','/api/move-payment','/api/cancel-payment'):
        key,d=action_deal(b,ro,x,allow_client=p=='/api/payquote')
        if d.get('status')!='active':raise Bad('Выкуп закрыт.')
        if p=='/api/payquote':
            date=valid_date(b.get('date',t)) if ro in ('owner','admin') else t
            return {**payment_quote(d,b.get('options') or {},date),'version':d.get('_v',0)}
        check_version(d,b);old=copy.deepcopy(d)
        if p=='/api/pay':
            date=valid_date(b.get('date',t));method=b.get('method')
            if method not in ('наличные','СБП','перевод'):raise Bad('Выберите способ оплаты.')
            quote=payment_quote(d,b.get('options') or {},date)
            if 'expected_quote' in b:
                expected=b['expected_quote']
                if not isinstance(expected,dict) or {k:v for k,v in expected.items() if k!='version'}!=quote:
                    raise Bad('Условия оплаты изменились. Проверьте новый расчёт.')
            if b.get('expected_total',quote['total'])!=quote['total'] or b.get('expected_bonus',quote['bonus'])!=quote['bonus']:
                raise Bad('Условия оплаты изменились. Проверьте новый расчёт.')
            apply_payment(d,quote,method)
            put_srv(key,'deal',d,'pay-periods',by,old)
            return quote
        if p=='/api/move-payment':
            preview=move_payment(d,b.get('source'),b.get('target'),t)
            if b.get('preview'):return preview
            put_srv(key,'deal',d,'move-payment',by,old)
            return preview
        count=cancel_payment(d,b.get('period'))
        put_srv(key,'deal',d,'cancel-payment',by,old)
        return {'count':count}
    if p=='/api/reschedule-request':
        key,d=action_deal(b,ro,x,permission='deals',allow_client=True)
        if ro!='client' or d.get('status')!='active':raise Bad('Заявка недоступна.')
        plan=replan(d,b.get('first'),b.get('pay'),t)
        if b.get('preview'):return plan
        check_version(d,b)
        if any(z.get('deal')==key and z.get('status')=='pending' for _,z in docs_of('reschedule')):raise Bad('Заявка уже ожидает решения.')
        request_id=nid()
        request={'deal':key,'client':x,'first':plan['first'],'pay':plan['pay'],'reason':str(b.get('reason') or '')[:1000],
                 'status':'pending','created':dt.datetime.now(MSK).isoformat(),'balance':plan['balance']}
        put_srv(request_id,'reschedule',request,'reschedule-request')
        say(f"Заявка на изменение графика: {(doc(x) or {}).get('name','')}, {rub(plan['pay'])}, следующий платёж {dm(D(plan['first']))}.")
        return {'id':request_id}
    if p=='/api/reschedule':
        request_id=str(b.get('id') or '');record=ID.fullmatch(request_id) and row(request_id)
        if not record or record[0]!='reschedule' or record[1].get('status')!='pending':raise Bad('Заявка уже рассмотрена.')
        request=record[1];key,d=action_deal({'deal':request['deal']},ro,x,permission='deals')
        if d.get('status')!='active':raise Bad('Выкуп закрыт.')
        action=b.get('do');old_request=copy.deepcopy(request)
        if action=='reject':
            request.update(status='rejected',decided=t,note=str(b.get('note') or '')[:1000])
            put_srv(request_id,'reschedule',request,'reschedule-reject',by,old_request)
            tell(d['client'],'Заявка на изменение графика отклонена.'+(' '+request['note'] if request['note'] else ' Свяжитесь с нами для уточнения условий.'))
            return {}
        plan=replan(d,b.get('first',request['first']),b.get('pay',request['pay']),t)
        if action=='preview':return {**plan,'version':d.get('_v',0)}
        if action!='approve':raise Bad('Выберите действие.')
        check_version(d,b);old=copy.deepcopy(d)
        materialize_schedule(d)
        d.setdefault('schedule_history',[]).append({'date':t,'request':request_id,'schedule':copy.deepcopy(d['schedule']),'pay':d['pay'],'n':d['n']})
        d.setdefault('original_n',d['n']);d['schedule']=plan['schedule'];d['shift']=0
        d['pay']=plan['pay'];d['last']=plan['lastAmount'];d['n']=max(row_['k'] for row_ in plan['schedule'])
        put_srv(key,'deal',d,'reschedule-approve',by,old)
        request.update(status='approved',decided=t,first=plan['first'],pay=plan['pay'],balance=plan['balance'],last=plan['last'])
        put_srv(request_id,'reschedule',request,'reschedule-approve',by,old_request)
        tell(d['client'],f"График изменён. Платёж {rub(plan['pay'])}, ближайшая дата {dm(D(plan['first']))}, последний платёж {rub(plan['lastAmount'])} до {dm(D(plan['last']))}. Подробности — в приложении.")
        return plan
    if p=='/api/close-deal':
        key,d=action_deal(b,ro,x,permission='deals');check_version(d,b)
        if d.get('status')!='active' or not info(d,t)['done']:raise Bad('Сначала закройте все платежи и долги.')
        old=copy.deepcopy(d);d.update(status='archived',closed=t,signed_at=dt.datetime.now(MSK).isoformat())
        put_srv(key,'deal',d,'close-deal',by,old)
        for field,kind in (('bike','bike'),('client','client')):
            item=doc(d[field])
            if item and not any(z.get(field)==d[field] and z.get('status')=='active' for _,z in docs_of('deal')):
                previous=copy.deepcopy(item);item['archived']=True;put_srv(d[field],kind,item,'archive-'+kind,by,previous)
        for request_id,request in docs_of('reschedule'):
            if request.get('deal')==key and request.get('status')=='pending':
                previous=copy.deepcopy(request);request.update(status='closed',decided=t);put_srv(request_id,'reschedule',request,'reschedule-close',by,previous)
        return {}
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
                    r=[{'kind':k,'id':i,'data':vw(k,json.loads(d),f)} for i,k,d in db.execute('select id,kind,data from docs') if (ro=='owner' or k!='admin') and k not in('qr','tch') and (pay or k not in('unk','bill')) and (ro=='owner' or k!='reschedule' or 'deals' in x[1].get('perms',[]))]
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
            if p in ('/api/payquote','/api/pay','/api/move-payment','/api/cancel-payment','/api/reschedule-request','/api/reschedule','/api/close-deal'):
                try:
                    result=workflow_action(p,b,ro,x);db.commit()
                    return s.send(200,json.dumps(result).encode())
                except Bad as e:
                    db.rollback();return s.send(400,json.dumps({'err':str(e)}).encode())
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
                        if k=='cfg':
                            try:
                                for field in ('multi_discount','receipt'):
                                    if field in new:
                                        value=float(new[field])
                                        if not math.isfinite(value) or not 0<=value<=100:raise Bad('Проценты должны быть от 0 до 100.')
                                        new[field]=value
                                if 'dmin' in new:
                                    value=whole(new['dmin'],'минимальный процент')
                                    if not 50<=value<=100:raise Bad('Минимальная частичная оплата — от 50 до 100%.')
                                    new['dmin']=value
                            except (Bad,ValueError,TypeError) as e:return s.send(400,json.dumps({'err':str(e)}).encode())
                        if k=='deal':completion_notice(old,new)
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
                        quick=bool(b.get('qr')) and not c.startswith('adm:')
                        k=('q_' if quick else '')+secrets.token_urlsafe(12);ttl=600 if quick else 7*86400
                        db.execute('delete from inv where exp<?',(t,));db.execute('insert into inv values(?,?,?)',(k,c,t+ttl))
                        db.execute('insert into log values(?,?,?,?,?)',(ts,'invite'+who_,c,None,None));db.commit()
                        return s.send(200,json.dumps({'tok':k,'bot':BOT[0],'qr':quick,'ttl':ttl}).encode())
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
                    quick=str(b.get('tok','')).startswith('q_')
                    if c and (quick or (ph and digits(c.get('phone'))==ph)):
                        db.execute('insert or replace into bind values(?,?)',(u,tgt));db.execute('delete from inv where tok=?',(str(b.get('tok')),));db.commit()
                        say(f"Клиент {c.get('name')} вошёл в приложение.");return s.send(200,b'{}')
                if len(TRY[u])==3:say(f'Неудачные попытки входа (Telegram ID {u}).')
                return s.send(403,b'{}')
            if ro=='client' and p=='/api/defer' and ID.fullmatch(str(b.get('id',''))):
                d=doc(b['id']);today=dt.datetime.now(MSK).date()
                if not d or d.get('client')!=x or d.get('status')!='active' or any(q.get('by')=='client' for q in d.get('defer',[])):return s.send(409,b'{}')
                k=first_unpaid(d)
                if not k or due(d,k)<today or (dstat(d,str(today)) or {}).get('over'):return s.send(409,b'{}')
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
