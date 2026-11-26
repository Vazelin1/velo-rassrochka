import os,re,json,hmac,hashlib,sqlite3,threading,time,secrets,math,copy,base64,binascii,csv,io,zipfile,tempfile,urllib.request,urllib.error,urllib.parse,datetime as dt
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from http.client import HTTPException
from html import escape
from pathlib import Path
from string import Template
from xml.etree import ElementTree as ET
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
TOK=os.environ['BOT_TOKEN'];OWNER=int(os.environ['OWNER_ID'])
MSK=dt.timezone(dt.timedelta(hours=3));L=threading.Lock()
QR_LOCKS=tuple(threading.Lock() for _ in range(64))
TQB=os.environ.get('TOCHKA_BASE','https://enter.tochka.com/uapi');MOCK=os.environ.get('TOCHKA_MOCK')=='1'
IMG={}
FILE_DL={}
DATA=os.environ.get('DATA_DIR','/data');BK=DATA+'/backups';os.makedirs(BK,mode=0o700,exist_ok=True);TGB=os.environ.get('TG_BASE','https://api.telegram.org')
BANK_SETTINGS=DATA+'/bank.json';MAX_BACKUP_BYTES=128*1024*1024
db=sqlite3.connect(DATA+'/app.db',check_same_thread=False)
db.executescript("create table if not exists docs(id text primary key,kind text,data text);create table if not exists log(ts text,act text,id text,old text,new text);create table if not exists inv(tok text primary key,client text,exp real);create table if not exists bind(tg integer primary key,client text);create table if not exists ntf(k text primary key)")
db.execute('create table if not exists notice_queue(k text primary key,day text,chat integer,body text,attempts integer,next real)')
FAIL={};TRY={};BOT=[os.environ.get('BOT_USERNAME','').lstrip('@') or None]
HD={'X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','Strict-Transport-Security':'max-age=31536000',
'Content-Security-Policy':"default-src 'self'; script-src 'self' 'unsafe-inline' https://telegram.org; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; frame-ancestors 'self' https://*.telegram.org"}
KINDS=('client','bike','deal','cfg','admin','qr','unk','bill','tch','reschedule','paymentreport','statementlink','expense')
SRV=('qr','unk','bill','tch','reschedule','paymentreport','statementlink')
PERMS=('pay','early','pen','clients','deals','bikes','reports')
FINP={'deals','bikes','reports'}  # rights that let an administrator see prices, purchase costs and profit
HID={'deal':('total','tax','acq','receipt','cost','disc','mk','extras','down','down_fees','tariff','gift','payoff_terms'),'bike':('cost','exp','wo')}
PUBCFG=('id','pen','dmin','catalogArchivedModels')
RENTAL_CATALOG_FIELDS=('rentalBrands','rentalModels','catalogArchivedModels')
LEGACY_MODEL_NAMES={'monster':'Монстр','u2':'U2','u2pro':'U2 Pro'}
BIKE_MODELS=tuple(LEGACY_MODEL_NAMES)
BATTERY_COUNTS=(1,2)

def tariff_key(model,batteries):
    return f'{model}-2-akb' if batteries==2 else model

BIKE_TARIFF_KEYS={tariff_key(model,count) for model in BIKE_MODELS for count in BATTERY_COUNTS}
WEEKLY_TERMS=(8,12,16,20,26)
RENTAL_WEEKS=(20,26)
RENTAL_BUYOUT_REDUCTION_RATE=2
LATE_FEE_AMOUNT=350
LATE_FEE_DAY=3
UNPAID_PENALTY_DAY=4
PARTIAL_GRACE_DAYS=4
CHARGE_RULES_VERSION=2
ADVANCES=(10000,20000,30000,40000,50000)
LEGACY_WEEKLY_TERMS={str(weeks) for weeks in range(8,27)}
WEEKLY_TERM_LIST=', '.join(map(str,WEEKLY_TERMS))
CLIENT_PAYOFF_MIN_PERIODS=4
CLIENT_PAYMENT_MAX_PERIODS=4
HANDOVER_CHECKS=('documents_signed','tracker_removed','spare_keys_given','bike_documents_given')
PAYMENT_METHODS=('наличные','СБП','перевод')
RENTAL_CONFIGURATIONS=('1','2','11','12','22')
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
def minor(n):return int((Decimal(str(n))*100).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
def money(cents):return cents//100 if cents%100==0 else cents/100
def rub(n):
    cents=minor(n)
    return f'{money(cents):,.{2 if cents%100 else 0}f}'.replace(',',' ').replace('.',',')+' ₽'
def dm(d):return d.strftime('%d.%m.%Y')
def botname():
    if not BOT[0]:
        try:BOT[0]=tg('getMe',{})['result']['username']
        except Exception as e:print('getMe',e)
    return BOT[0]
def row(i):
    r=db.execute('select kind,data from docs where id=?',(i,)).fetchone();return r and (r[0],json.loads(r[1]))
def doc(i):
    if i=='tch':
        try:
            with open(BANK_SETTINGS) as source:return json.load(source)
        except FileNotFoundError:pass
    r=row(i);return r and r[1]
def save(i,k,d):db.execute('insert or replace into docs values(?,?,?)',(i,k,json.dumps(d)))
def D(s):return dt.date.fromisoformat(s)
def digits(p):return re.sub(r'\D','',p or '')[-10:]
def payment_deadline(d, installment):
    """Keep deadlines already granted before the deferral feature was removed."""
    return max([installment['due']] + [
        grant['until'] for grant in d.get('defer') or []
        if grant.get('k') == installment['k'] and grant.get('due') == installment['due'] and grant.get('until')
    ])

def partial_payment_deadline(d, installment):
    return add(payment_deadline(d,installment),PARTIAL_GRACE_DAYS)

def unpaid_installments(d, schedule=None):
    if d.get('payoff'):return []
    paid = d.get('paid') or {}
    return sorted((x for x in (sched(d) if schedule is None else schedule) if str(x['k']) not in paid),
                  key=lambda x: x['k'] if d.get('lease') else payment_deadline(d, x))
def sched(d):
    """Payment schedule exactly as the app computes it (static/calc.js): due dates, and early payments shorten it from the end."""
    n=d['n'];paid=d.get('paid') or {};P=30 if d['type']=='m' else 7
    if d.get('lease'):
        return [{'k':k,'due':add(d['start'],7*(k-1)),'amt':d['lease']['weekly']} for k in range(1,n+1)]
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
def due_today(ds,t):
    c=0
    for d in ds:
        if d.get('status')!='active':continue
        if any(payment_deadline(d,x)==str(t) for x in unpaid_installments(d)):c+=1
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
def safe_link(v):
    """A link to the owner's Telegram / Max account for the client screen: only plain https links are passed on."""
    v=str(v or '').strip()
    return v if re.fullmatch(r'https://[^\s<>"\'\\]{3,300}',v) else ''

def safe_phone(value):
    number = re.sub(r'[^+0-9]', '', str(value or ''))
    return number if re.fullmatch(r'\+?[0-9]{7,15}', number) else ''

def payment_public(deal):
    """Fees, reconciliation references and internal notes stay in the staff view."""
    def public(p):
        return {k: v for k, v in p.items() if k not in ('fees', 'source')}
    return {k: deal.get(k) for k in (
        'n','start','pay','last','shift','defer','pen','status','contract','type','debt','pw','np',
        'schedule','bonuses','completed_at','closed','signed_at','client_rescheduled','_v',
    )} | {
        'paid': {k: public(p) for k,p in (deal.get('paid') or {}).items()},
        'early': [public(p) for p in deal.get('early') or []],
        'dpays': [public(p) for p in deal.get('dpays') or []],
        'payoff': public(deal['payoff']) if deal.get('payoff') else None,
    } | ({k:deal[k] for k in ('lease','deposit','deposit_refund','refund','refund_date','late_fee') if k in deal} if deal.get('lease') else {})

def mine(cid):
    c=doc(cid) or {};out=[];date=tod()
    for i,d in db.execute("select id,data from docs where kind='deal'").fetchall():
        d=json.loads(d)
        if d['client']==cid:
            quote=early_buyout_quote(d,date,client=True)
            out.append(payment_public(d)|{'id':i,'bike':(doc(d['bike']) or {}).get('name',''),
                                         'payoff_quote':quote})
    ids={o['id'] for o in out};bills=[{'id':i,'deal':z['deal'],'amt':z['amt'],'kind':z['kind'],'ts':z.get('ts')} for i,z in docs_of('bill') if z.get('status')=='open' and z.get('deal') in ids]
    cf=doc('cfg') or {}
    requests=[{**z,'id':i} for i,z in docs_of('reschedule') if z.get('deal') in ids]
    reports = [{**payment_report_summary(z), 'id': i} for i,z in docs_of('paymentreport') if z.get('deal') in ids and z.get('client')==cid]
    return {
        'role':'client','name':c.get('name',''),'deals':out,'requests':requests,'paymentreports':reports,
        'dmin':max(50,cf.get('dmin',50)),'qr':bool(tq()),'bills':bills,
        'ct':{'tg':safe_link(cf.get('ctg')),'mx':safe_link(cf.get('cmx')),'phone':safe_phone(cf.get('cphone'))},
        'city':PUBLIC_CITY,
        'operator':{'name':PUBLIC_OPERATOR_SHORT,'inn':PUBLIC_INN,'ogrnip':PUBLIC_OGRNIP}
    }
def adm_of(u):
    """The administrator whose Telegram ID is u: (id, data) or None."""
    for i,d in db.execute("select id,data from docs where kind='admin'").fetchall():
        d=json.loads(d)
        if d.get('tg')==u:return i,d
def role(u):
    if u==OWNER:return 'owner',None
    a=adm_of(u)
    if a:return ('off',a) if a[1].get('disabled') else ('admin',a)
    b=db.execute("select bind.client,docs.data from bind join docs on docs.id=bind.client and docs.kind='client' where bind.tg=?",(u,)).fetchone()
    return ('client',b[0]) if b and not json.loads(b[1]).get('erased') else ('new',None)
def hasfin(P):return bool(set(P)&FINP)
def vw(k,d,f,owner=False):
    """Document fields visible to the current role."""
    if k=='cfg':
        models=rental_models(d)
        if not f:
            return {x:y for x,y in d.items() if x in PUBCFG or x=='rentalBrands'} | {'rentalModels':{
                model:{'name':entry['name'],'brand':entry['brand']} for model,entry in models.items()}}
        if owner:return {**d,'rentalModels':models}
        result={x:y for x,y in d.items() if x!='purchaseCosts'}
        result['rentalModels']={model:{'name':entry['name'],'brand':entry['brand'],'plans':entry['plans'],
            'batteries':{identifier:rental_battery(battery,with_cost=False)
                         for identifier,battery in entry['batteries'].items()}} for model,entry in models.items()}
        return result
    if f:
        return d
    out = {x:y for x,y in d.items() if x not in HID.get(k,())}
    if k == 'deal':
        if not d.get('lease'):out.pop('refund',None)
        if d.get('payoff_terms'):out['payoff_enabled']=True
        for field in ('paid','early','dpays','payoff'):
            if field in d:
                out[field] = payment_public(d)[field]
    return out
def okkey(P,k,x,m):
    """May an administrator with rights P change field x of a document of kind k?"""
    if k=='deal':
        n={'paid':'pay','debt':'pay','dpays':'pay','early':'early','shift':'early','pw':'pen','np':'pen'}.get(x)
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
    hid=() if hasfin(P) else HID.get(k,()) + (('refund',) if k=='deal' and not old.get('lease') else ())
    m={x:y for x,y in new.items() if x not in hid}
    if k=='deal':m.pop('payoff_enabled',None)
    for x in hid:
        if x in old:m[x]=old[x]
    if k=='deal' and hid:
        if old.get('payoff') and m.get('payoff')==payment_public(old)['payoff']:
            m['payoff']=old['payoff']
        for kind,key,payment in receipt_parts(m):
            previous=receipt_part(old,kind,key)
            if previous and receipt_cash(previous,kind)==receipt_cash(payment,kind):
                for field in ('fees','source'):
                    if field in previous:payment[field]=previous[field]
    for x in set(m)|set(old):
        if x=='_v' or m.get(x,NO)==old.get(x,NO):continue
        if not okkey(P,k,x,m):return None
    return m
def dump():
    with L:
        return json.dumps({'v':1,'ts':dt.datetime.now(MSK).isoformat(),'docs':[{'id':i,'kind':k,'data':json.loads(x)} for i,k,x in db.execute("select id,kind,data from docs where kind!='tch'")],
        'bind':[[a,c] for a,c in db.execute('select tg,client from bind')],'log':[list(r) for r in db.execute("select ts,act,id,old,new from log where id!='tch'")]},ensure_ascii=False).encode()
DL={};TTL=int(os.environ.get('DL_TTL','120'));BS=DATA+'/last_download.json'
def bget():
    try:return json.load(open(BS))
    except Exception:return None
def bset():
    try:open(BS,'w').write(json.dumps({'ts':dt.datetime.now(MSK).isoformat()}))
    except Exception as e:print('bset',e)
def snap(pre):
    os.chmod(BK,0o700)
    fd,name=tempfile.mkstemp(dir=BK,prefix='.snapshot-');os.close(fd)
    try:
        backup=sqlite3.connect(name)
        try:
            db.backup(backup)
            backup.execute('pragma secure_delete=on')
            with backup:
                backup.execute("delete from docs where kind='tch'")
                backup.execute("delete from log where id='tch'")
            backup.execute('vacuum')
        finally:backup.close()
        os.replace(name,f'{BK}/{pre}-{dt.datetime.now(MSK):%Y-%m-%d-%H%M%S-%f}.db')
    finally:
        if os.path.exists(name):os.remove(name)
    for f in sorted(x for x in os.listdir(BK) if x.startswith(pre+'-') and x.endswith('.db'))[:-(30 if pre=='app' else 5)]:os.remove(f'{BK}/{f}')

def save_bank_settings(settings):
    fd,name=tempfile.mkstemp(dir=DATA,prefix='.bank-')
    try:
        with os.fdopen(fd,'w') as target:
            json.dump(settings,target)
            target.flush();os.fsync(target.fileno())
        os.replace(name,BANK_SETTINGS)
    finally:
        if os.path.exists(name):os.remove(name)

def validate_backup(records,bindings):
    def require(identifier,kind):
        if not isinstance(identifier,str) or identifier not in records or records[identifier][0]!=kind:
            raise Bad(f'В копии отсутствует связанная запись {kind} ({identifier}).')
    def amount(value):
        if not isinstance(value,(int,float)) or isinstance(value,bool) or not math.isfinite(value):
            raise Bad('В копии есть некорректная сумма.')
    def objects(data,field):
        value=data.get(field)
        if value is None:return []
        if not isinstance(value,list) or not all(isinstance(x,dict) for x in value):
            raise Bad(f'В копии повреждён раздел {field}.')
        return value
    for identifier,(kind,data) in records.items():
        if kind=='deal':
            require(data.get('client'),'client');require(data.get('bike'),'bike')
            if data.get('status')=='active' and any(records[data[field]][1].get('erased') for field in ('client','bike')):
                raise Bad('Активный выкуп связан с удалённой карточкой.')
            valid_date(data.get('start'))
            if data.get('type') not in ('w','m') or type(data.get('n')) is not int or not 1<=data['n']<=5200 or data.get('status') not in ('active','archived','seized','lost'):
                raise Bad(f'В копии повреждён график выкупа {identifier}.')
            for field in ('pay','last'):amount(data.get(field))
            if not isinstance(data.get('paid'),dict):raise Bad(f'В копии повреждены оплаты выкупа {identifier}.')
            for field in ('dpays','early','bonuses','extras'):objects(data,field)
            if 'gift' in data:data['gift']=validate_gift(data['gift'])
            if 'lease' in data:validate_rental_record(data)
            if 'payoff_terms' in data:validate_payoff_terms(data)
            if 'payoff' in data:validate_payoff_record(data)
            if 'handover' in data and (data['status']!='archived' or not handover_confirmed(data['handover'])):
                raise Bad('В копии повреждено подтверждение передачи велосипеда.')
            for swap in objects(data,'swaps'):
                require(swap.get('from'),'bike');valid_date(swap.get('date'))
                if swap.get('to'):require(swap['to'],'bike')
            for grant in objects(data,'defer'):
                valid_date(grant.get('due'));valid_date(grant.get('until'))
            keys=set()
            for x in objects(data,'schedule'):
                if type(x.get('k')) is not int or x['k']<=0 or x['k'] in keys:raise Bad('В копии неверные номера взносов.')
                keys.add(x['k']);valid_date(x.get('due'));amount(x.get('amt'))
                if x['amt']<0:raise Bad('В копии отрицательная сумма взноса.')
            for _,key,payment in receipt_parts(data):
                if not isinstance(payment,dict):raise Bad('Повреждена запись об оплате.')
                valid_date(payment.get('date'));amount(payment.get('amt'));amount(payment.get('pen',0) or 0)
                if 'fine' in payment and not 0<=whole(payment['fine'],'сумму штрафа')<=(payment.get('pen') or 0):
                    raise Bad('В копии не сходятся начисления по оплате.')
                if payment.get('due'):valid_date(payment['due'])
            if data.get('debt'):
                valid_date(data['debt'].get('due'));amount(data['debt'].get('amt'))
                if data['debt'].get('pb'):valid_date(data['debt']['pb'])
            if data.get('pen') is not None:amount(data['pen'])
            for interval in data.get('np') or []:
                valid_date(interval[0])
                if interval[1]:valid_date(interval[1])
            info(data);payment_public(data)
        elif kind in SRV:
            require(data.get('deal'),'deal')
            if kind in ('reschedule','paymentreport'):require(data.get('client'),'client')
            if kind in ('qr','statementlink','paymentreport'):valid_date(data.get('date'))
            if kind=='qr':qr_expiry(data)
        elif kind in ('client','bike','admin'):
            if not isinstance(data.get('name'),str):raise Bad(f'В копии отсутствует имя записи {identifier}.')
            if kind=='bike':
                if 'cost' in data:amount(data['cost'])
                if 'batteries' in data and not valid_batteries(data['batteries']):
                    raise Bad('В копии повреждена комплектация велосипеда.')
                for expense in objects(data,'exp'):
                    valid_date(expense.get('date'));amount(expense.get('amt'))
                if data.get('wo'):
                    valid_date(data['wo'].get('date'));amount(data['wo'].get('loss',0))
        elif kind=='expense':validate_expense(data)
        elif kind=='cfg':
            if data.get('mk') and not isinstance(data['mk'].get('w'),dict):raise Bad('В копии повреждены тарифы.')
            if data.get('ds') and not all(isinstance(x,list) and len(x)==2 for x in data['ds']):raise Bad('В копии повреждены скидки.')
            if 'tariffs' in data:validate_tariffs(data['tariffs'], restoring=True)
            if 'purchaseCosts' in data:validate_purchase_costs(data['purchaseCosts'])
            if 'advanceDiscounts' in data:validate_advance_discounts(data['advanceDiscounts'])
            if any(field in data for field in RENTAL_CATALOG_FIELDS):validate_rental_catalog(data)
            for field in ('pen','tax','dmin','dd','dbd','multi_discount','receipt','acq'):
                if data.get(field) is not None:amount(data[field])
    seen=set()
    for tg_id,client in bindings:
        if type(tg_id) is not int or tg_id<=0 or tg_id in seen:raise Bad('В копии повреждены привязки Telegram.')
        require(client,'client')
        if records[client][1].get('erased'):raise Bad('В копии есть привязка удалённого клиента.')
        seen.add(tg_id)
def restore(b):
    """returns (code, reply). Replaces docs and bind with the backup content; the audit log is kept."""
    try:
        if not isinstance(b,dict) or b.get('v')!=1:return 400,'Это не файл копии (или файл от другой версии).'
        docs=b['docs'];bind=b.get('bind',[]);lg=b.get('log',[])
        if not isinstance(docs,list) or not isinstance(bind,list) or not isinstance(lg,list):return 400,'Файл повреждён.'
        records={}
        for x in docs:
            i,k,d=x['id'],x['kind'],x['data']
            if k=='tch':continue
            if not isinstance(i,str) or not ID.fullmatch(i) or k not in KINDS or not isinstance(d,dict) or i in records:return 400,'Файл повреждён: неверная запись.'
            records[i]=(k,d)
        validate_backup(records,bind)
        rows=[(i,k,json.dumps(d,allow_nan=False)) for i,(k,d) in records.items()]
        lg=[tuple(None if y is None else str(y) for y in r) for r in lg if isinstance(r,list) and len(r)==5 and r[2]!='tch'][-100000:]
    except Bad as e:return 400,str(e)
    except Exception:return 400,'Файл повреждён.'
    with L:
        try:
            snap('pre-restore')
            empty=not db.execute('select 1 from log limit 1').fetchone();keep=db.execute("select id,kind,data from docs where kind='tch'").fetchall()
            db.execute('delete from docs');db.execute('delete from bind');db.execute('delete from inv')
            db.execute('delete from notice_queue')
            db.executemany('insert into docs values(?,?,?)',rows+keep);db.executemany('insert into bind values(?,?)',bind)
            migrate_fee_records()
            if bind:mine(bind[0][1])
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

def receipt_parts(d):
    yield from (('paid',k,p) for k,p in (d.get('paid') or {}).items())
    for kind in ('early','dpays'):
        yield from ((kind,k,p) for k,p in enumerate(d.get(kind) or []))
    if d.get('payoff'):yield 'payoff',None,d['payoff']

def receipt_part(d,kind,key):
    if kind=='payoff':return d.get('payoff')
    records=d.get(kind) or ({} if kind=='paid' else [])
    return records.get(key) if kind=='paid' else records[key] if key<len(records) else None

def receipt_cash(p,kind):
    return (p.get('date'),p.get('method'),p.get('paid',p.get('amt')) if kind=='early' else p.get('amt',0)+(p.get('pen') or 0))

def fee_rates(method,estimated=False):
    def rate(name):
        try:v=float(cfgv(name,0))
        except (ValueError,TypeError):return 0
        return v if math.isfinite(v) and 0<=v<=100 else 0
    values={k:rate(k) if method=='СБП' else 0 for k in ('acq','receipt')}
    if estimated and method=='СБП':values['estimated']=True
    return values

def stamp_receipts(d,old=None,legacy=False):
    for kind,key,payment in receipt_parts(d):
        previous=receipt_part(old or {},kind,key)
        same=previous and receipt_cash(previous,kind)==receipt_cash(payment,kind)
        source=(payment.get('source') if legacy else (previous or {}).get('source') if same else None)
        fees=(payment.get('fees') if legacy else (previous or {}).get('fees') if same else None)
        if not source and legacy and kind=='paid':source=payment.get('group')
        payment['source']=source or payment.get('qr') or nid()
        payment['fees']=fees or fee_rates(payment.get('method'),estimated=legacy or bool(same))
    if d.get('down'):
        method=d.get('down_method') or ((d.get('paid') or {}).get('1') or {}).get('method')
        previous=(old or {}).get('down_fees') if (old or {}).get('down')==d.get('down') else None
        d['down_fees']=(d.get('down_fees') if legacy else previous) or fee_rates(method,estimated=legacy)
        first=(d.get('paid') or {}).get('1') or {}
        if old is None and not legacy and first.get('method')==method and first.get('date')==d['start']:
            d['down_source']=first.get('source')

def migrate_fee_records():
    for i,d in docs_of('deal'):
        if any(not p.get('fees') or not p.get('source') for _,_,p in receipt_parts(d)) or (d.get('down') and not d.get('down_fees')):
            stamp_receipts(d,legacy=True);save(i,'deal',d)
def penalty(a,days,r):return int(math.floor(a*max(0,0.9 if r is None else r)/100*days+0.5))
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
    if d.get('payoff') or not g or not g.get('amt',0)>0:return None
    payment=(d.get('paid') or {}).get(str(g['k'])) or {}
    first=payment['date'] if payment.get('part') else ''
    if first>T:return None
    # The first payment already covered all charges through its own date.
    b=max(g['due'],g.get('pb') or '',first);n=pdays(b,T,d);pe=penalty(g['amt'],n,d.get('pen'))
    return {'amt':g['amt'],'due':g['due'],'k':g['k'],'days':n,'pen':pe,'total':money(minor(g['amt'])+minor(pe)),'late':max(0,diff(T,g['due'])),'over':T>g['due'],'base':b}

def installment_charges(d,period,date,*,legacy_rental_grace=None):
    limit=payment_deadline(d,period)
    if legacy_rental_grace is None:
        grace=UNPAID_PENALTY_DAY-1
        late={'amount':LATE_FEE_AMOUNT,'day':LATE_FEE_DAY}
    else:
        grace=legacy_rental_grace if d.get('lease') else 0
        late=d.get('late_fee') or {}
    days=pdays(add(limit,grace),date,d)
    fine=0
    if late.get('amount'):
        charged_on=add(limit,late['day'])
        written_off=d.get('pw') or ''
        paused=any(start<=charged_on and (not end or charged_on<end) for start,end in d.get('np') or [])
        if written_off<charged_on<=date and not paused:fine=late['amount']
    return {'days':days,'pen':penalty(period['amt'],days,d.get('pen'))+fine,'fine':fine}

def info(d,t=None,*,legacy_rental_grace=None):
    t=t or tod();sc=sched(d);un=unpaid_installments(d,sc);od=[x for x in un if payment_deadline(d,x)<t];ods=[]
    for y in od:
        ods.append({**y,**installment_charges(d,y,t,legacy_rental_grace=legacy_rental_grace)})
    pe=sum(y['pen'] for y in ods);g=dstat(d,t)
    return {'sc':sc,'un':un,'x':un[0] if un else None,'od':od,'ods':ods,'pen':pe,'g':g,'owe':sum(y['amt'] for y in od)+pe,
            'done':bool(d.get('payoff')) if d.get('lease') else not un and not g}
def minpart(x):return money(math.ceil(minor(x['amt'])*max(50,cfgv('dmin',50))/100))

def whole(value,label='сумму'):
    try:
        number=float(value)
    except (ValueError,TypeError,OverflowError):
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

def received_date(value,t):
    date=valid_date(value)
    if date>t:raise Bad('Дата получения денег не может быть в будущем.')
    return date

def positive_amount(value):
    if isinstance(value,bool):raise Bad('Введите сумму.')
    try:
        cents=minor(value)
        if not 0<cents<=1000000000 or Decimal(str(value))*100!=cents:raise ValueError()
    except (InvalidOperation,TypeError,ValueError,OverflowError):
        raise Bad('Введите сумму с точностью до копейки.')
    return money(cents)

def validate_expense(data):
    description=data.get('text')
    if not isinstance(description,str) or not 1<=len(description.strip())<=240:raise Bad('Введите описание расхода, до 240 символов.')
    return {'text':description.strip(),'date':valid_date(data.get('date')),'amt':positive_amount(data.get('amt'))}

def late_fee_record(amount,day):
    amount=whole(amount,'сумму штрафа')
    day=whole(day,'день штрафа')
    if amount<0 or not 1<=day<=365:raise Bad('Укажите сумму штрафа от 0 ₽ и день просрочки от 1 до 365.')
    return {'amount':amount,'day':day}

def valid_batteries(count):
    return type(count) is int and count in BATTERY_COUNTS

def validate_purchase_costs(costs):
    if not isinstance(costs,dict) or any(key not in BIKE_TARIFF_KEYS for key in costs):
        raise Bad('Проверьте закупочные цены по комплектациям.')
    for key,value in costs.items():
        costs[key]=positive_amount(value)

def validate_advance_discounts(discounts):
    if not isinstance(discounts,dict) or not set(discounts).issubset(map(str,ADVANCES)):
        raise Bad('Проверьте список скидок за первоначальный взнос.')
    for key,value in discounts.items():
        amount=whole(value,'скидку за первоначальный взнос')
        if amount<0:raise Bad('Скидка не может быть отрицательной.')
        discounts[key]=amount

def validate_gift(gift):
    if not isinstance(gift,dict):raise Bad('Проверьте данные подарка.')
    name=gift.get('name','')
    if not isinstance(name,str) or len(name)>160:raise Bad('Описание подарка должно быть не длиннее 160 символов.')
    amount=gift.get('amount')
    if isinstance(amount,bool):raise Bad('Укажите стоимость подарка.')
    return {'name':name.strip(),'amount':0 if amount==0 else positive_amount(amount)}

def validate_tariffs(tariffs, previous=None, *, restoring=False):
    if not isinstance(tariffs,dict) or any(key not in BIKE_TARIFF_KEYS for key in tariffs):
        raise Bad('Проверьте тарифы по комплектациям велосипеда.')
    terms={str(weeks) for weeks in WEEKLY_TERMS}
    for model,rates in tariffs.items():
        if not isinstance(rates,dict):raise Bad('Тарифы модели должны быть заданы по срокам.')
        old_rates=(previous or {}).get(model,{})
        for term,amount in rates.items():
            legacy=term in LEGACY_WEEKLY_TERMS and (restoring or (term in old_rates and amount==old_rates[term]))
            if term not in terms and not legacy:raise Bad(f'Доступные сроки выкупа: {WEEKLY_TERM_LIST} недель.')
            rates[term]=positive_amount(amount)

def rental_battery(value, *, with_cost):
    if not isinstance(value,dict):raise Bad('Проверьте параметры аккумулятора.')
    voltage=positive_amount(value.get('voltage'));capacity=positive_amount(value.get('capacity'))
    if not 1<=voltage<=300 or not 1<=capacity<=500:raise Bad('Проверьте напряжение и ёмкость АКБ.')
    result={'voltage':voltage,'capacity':capacity}
    if value.get('name'):
        result['name']=catalog_name(value['name'],'название варианта АКБ')
    if with_cost:
        result['cost']=positive_amount(value.get('cost')) if value.get('cost')!=0 else 0
    return result

def catalog_name(value,label):
    if not isinstance(value,str) or not 1<=len(value.strip())<=80:
        raise Bad(f'Введите {label} (до 80 символов).')
    return value.strip()

def catalog_id(value):
    return isinstance(value,str) and bool(ID.fullmatch(value))

def rental_key(slots):
    if not isinstance(slots,list) or not slots:raise Bad('Выберите хотя бы один АКБ.')
    identifiers=[str(slot) if type(slot) is int and slot in (1,2) else slot for slot in slots]
    if any(not catalog_id(identifier) for identifier in identifiers):raise Bad('Проверьте варианты АКБ.')
    return ','.join(sorted(identifiers))

def rental_plan(value,weeks):
    if not isinstance(value,dict) or type(weeks) is not int or weeks not in WEEKLY_TERMS:
        raise Bad(f'Выберите срок аренды: {WEEKLY_TERM_LIST} недель.')
    weekly=whole(value.get('weekly'),'арендную плату за неделю')
    price=whole(value.get('price'),'цену выкупа')
    deposit=whole(value.get('deposit',0),'обеспечительный платёж')
    if weekly<1 or not 0<=price-weekly*weeks<weeks or deposit<0:
        raise Bad('Цена выкупа и недельная плата должны соответствовать сроку тарифа.')
    return {'weekly':weekly,'price':price,'deposit':deposit}

def migrate_rental_models(models):
    migrated={}
    for model,entry in models.items():
        if isinstance(entry,dict) and isinstance(entry.get('batteries'),list):
            if model not in BIKE_MODELS or len(entry['batteries'])!=2:
                raise Bad('Проверьте список АКБ из прежней версии.')
            legacy=entry['batteries']
            entry={**entry,'name':LEGACY_MODEL_NAMES[model],'brand':'',
                   'batteries':{str(index):battery for index,battery in enumerate(legacy,1) if battery is not None}}
            for field in ('plans','kitCosts'):
                source=entry.get(field,{})
                if not isinstance(source,dict) or any(key not in RENTAL_CONFIGURATIONS for key in source):
                    raise Bad('Проверьте комплектации из прежней версии.')
                entry[field]={','.join(key):value for key,value in source.items()}
        migrated[model]=entry
    return migrated

def rental_models(settings):
    return migrate_rental_models(settings.get('rentalModels',{}))

def validate_rental_catalog(settings):
    brands=settings.get('rentalBrands',{});models=settings.get('rentalModels',{})
    if not isinstance(brands,dict) or any(not catalog_id(brand) for brand in brands):
        raise Bad('Проверьте список брендов.')
    brands={brand:catalog_name(name,'название бренда') for brand,name in brands.items()}
    if not isinstance(models,dict) or any(not catalog_id(model) for model in models):
        raise Bad('Проверьте список моделей.')
    archived=settings.get('catalogArchivedModels',[])
    if (not isinstance(archived,list)
        or any(not catalog_id(model) or (model not in models and model not in BIKE_MODELS) for model in archived)
        or len(set(archived))!=len(archived)):
        raise Bad('Проверьте список удалённых моделей.')
    models=migrate_rental_models(models)
    terms={str(n) for n in WEEKLY_TERMS}
    for model,entry in models.items():
        if not isinstance(entry,dict) or not isinstance(entry.get('batteries'),dict):
            raise Bad('Проверьте список аккумуляторов модели.')
        name=catalog_name(entry.get('name'),'название модели')
        brand=entry.get('brand','')
        if brand!='' and (not catalog_id(brand) or brand not in brands):raise Bad('Выберите бренд модели.')
        if any(not catalog_id(identifier) for identifier in entry['batteries']):raise Bad('Проверьте варианты АКБ.')
        batteries={identifier:rental_battery(battery,with_cost=True) for identifier,battery in entry['batteries'].items()}
        plans=entry.get('plans',{});kit_costs=entry.get('kitCosts',{})
        if not isinstance(plans,dict) or not isinstance(kit_costs,dict) or any(
            not isinstance(key,str) or key!=rental_key(key.split(',')) or any(slot not in batteries for slot in key.split(','))
            for key in plans.keys() | kit_costs.keys()
        ):raise Bad('Сначала заполните параметры АКБ для этой комплектации.')
        if model in archived and (plans or kit_costs):
            raise Bad('Эта модель удалена из каталога.')
        parsed={}
        for key,by_week in plans.items():
            if not isinstance(by_week,dict) or any(term not in terms for term in by_week):
                raise Bad('Проверьте сроки тарифов.')
            parsed[key]={term:rental_plan(plan,int(term)) for term,plan in by_week.items()}
        cost=entry.get('cost',0)
        models[model]={'name':name,'brand':brand,'cost':positive_amount(cost) if cost!=0 else 0,
                       'batteries':batteries,'plans':parsed,
                       'kitCosts':{key:positive_amount(cost) for key,cost in kit_costs.items()}}
    settings.update(rentalBrands=brands,rentalModels=models)

def remove_catalog_entry(b):
    old=doc('cfg') or {}
    if b.get('version')!=old.get('_v',0):
        raise Bad('Каталог изменился. Откройте запись заново.')
    kind,identifier=b.get('kind'),b.get('id')
    if not catalog_id(identifier):raise Bad('Выберите запись в каталоге.')
    brands=dict(old.get('rentalBrands',{}))
    models=rental_models(old)
    archived=list(old.get('catalogArchivedModels',[]))
    if kind=='brand':
        if identifier not in brands:raise Bad('Бренд уже удалён.')
        del brands[identifier]
        for model,entry in models.items():
            if entry.get('brand')==identifier:models[model]={**entry,'brand':''}
    elif kind=='model':
        if identifier in archived or (identifier not in models and identifier not in BIKE_MODELS):
            raise Bad('Модель недоступна.')
        archived.append(identifier)
        if identifier in models:
            # Keep the name and ID for bikes that already refer to the model.
            models[identifier]={**models[identifier],'plans':{},'kitCosts':{}}
    elif kind=='battery':
        model=b.get('model')
        if not catalog_id(model) or model in archived or model not in models:
            raise Bad('Модель недоступна.')
        entry=models[model]
        batteries=dict(entry['batteries'])
        if identifier not in batteries:raise Bad('Вариант АКБ уже удалён.')
        del batteries[identifier]
        models[model]={**entry,'batteries':batteries}
        for field in ('plans','kitCosts'):
            models[model][field]={key:value for key,value in entry.get(field,{}).items()
                                  if identifier not in key.split(',')}
    else:
        raise Bad('Выберите бренд, модель или вариант АКБ.')
    settings={**old,'id':'cfg','rentalBrands':brands,'rentalModels':models,'catalogArchivedModels':archived}
    validate_rental_catalog(settings)
    settings['_v']=old.get('_v',0)+1
    put_srv('cfg','cfg',settings,'delete-catalog-'+kind,old=old)
    return {'_v':settings['_v']}

def known_bike_model(model):
    return catalog_id(model) and (model in BIKE_MODELS or model in cfgv('rentalModels',{}))

def rental_terms(model,slots,weeks):
    if type(weeks) is not int or weeks not in RENTAL_WEEKS:raise Bad('Выберите срок аренды, 20 или 26 недель.')
    key=rental_key(slots)
    settings=doc('cfg') or {}
    if model in settings.get('catalogArchivedModels',[]):raise Bad('Эта модель удалена из каталога.')
    entry=rental_models(settings).get(model,{})
    plan=entry.get('plans',{}).get(key,{}).get(str(weeks))
    if not plan:raise Bad('Сохраните тариф для выбранной комплектации и срока в настройках.')
    batteries=[entry['batteries'][str(slot)] for slot in slots]
    cost=entry.get('kitCosts',{}).get(key)
    if cost is None:
        cost=money(minor(entry['cost'])+sum(minor(b['cost']) for b in batteries)) if entry['cost'] and all(b['cost'] for b in batteries) else 0
    terms={**plan,'model':model,'modelName':entry['name'],'brandName':settings.get('rentalBrands',{}).get(entry['brand'],''),
           'slots':slots,'weeks':weeks,
           'batteries':[rental_battery(b,with_cost=False) for b in batteries]}
    return terms,cost

def rental_paid_amounts(d,date):
    by_period={int(key):minor(p['amt']) for key,p in d['paid'].items() if p['date']<=date}
    for payment in d.get('dpays') or []:
        if payment['date']<=date:
            key=payment['k'];by_period[key]=by_period.get(key,0)+minor(payment['amt'])
    return by_period

def rent_batch_reduction(principal,count):
    return money((minor(principal)*RENTAL_BUYOUT_REDUCTION_RATE+50)//100) if count>=2 else 0

def rental_credit(d,date):
    paid=sum(rental_paid_amounts(d,date).values())
    base=minor(d['lease']['price'])
    reduction=min(base,sum(minor(p.get('buyout_reduction',0)) for p in d['paid'].values() if p['date']<=date))
    price=base-reduction
    return {'rent_paid':money(paid),'credited':money(min(paid,price)),
            'price':money(price),'buyout_reduction':money(reduction)}

def rental_payoff_quote(d,date,*,legacy_rental_grace=None):
    if d.get('payoff') or d.get('status')!='active' or diff(date,d['start'])<7*CLIENT_PAYOFF_MIN_PERIODS:return None
    paid=rental_paid_amounts(d,date);weekly=minor(d['lease']['weekly'])
    if any(paid.get(k,0)!=weekly for k in range(1,CLIENT_PAYOFF_MIN_PERIODS+1)) or any(
        p['date']>date for _,_,p in receipt_parts(d)
    ):return None
    credit=rental_credit(d,date);principal=money(minor(credit['price'])-minor(credit['credited']))
    # Only accrued rent penalties enter the calculation. Future rents end at buyout.
    installments=info(d,date,legacy_rental_grace=legacy_rental_grace)
    pe=installments['pen']+(installments['g'] or {}).get('pen',0)
    fine=sum(row['fine'] for row in installments['ods'])
    return {**credit,'date':date,'paid':credit['credited'],'principal':principal,'saved':0,
            'pen':pe,**({'fine':fine} if fine else {}),'total':money(minor(principal)+minor(pe)),'version':d.get('_v',0)}

def payoff_terms(d,tariffs):
    """Freeze comparable shorter prices with the deal's existing advance discount."""
    tariff=d.get('tariff') or {}
    weeks=tariff.get('weeks')
    if d.get('type')!='w' or weeks not in WEEKLY_TERMS:return []
    rates=tariffs.get(tariff_key(tariff.get('model'),tariff.get('batteries',1)),{})
    current=minor(d['total']);terms=[{'weeks':weeks,'price':money(current)}]
    discounts=minor(tariff.get('advanceDiscount',0))
    extras=sum(minor(x['price']) for x in d.get('extras') or [])
    for shorter in reversed(WEEKLY_TERMS):
        if shorter>=weeks or not rates.get(str(shorter)):continue
        price=((minor(rates[str(shorter)])*shorter+50)//100)*100-discounts+extras
        if not 0<price<current:continue
        terms.append({'weeks':shorter,'price':money(price)})
        current=price
    return terms[::-1] if len(terms)>1 else []

def validate_payoff_terms(d):
    points=d['payoff_terms']
    if not isinstance(points,list) or not 2<=len(points)<=len(WEEKLY_TERMS):
        raise Bad('В копии повреждены тарифы досрочного выкупа.')
    previous_weeks=previous_price=0
    for point in points:
        if not isinstance(point,dict) or type(point.get('weeks')) is not int or point['weeks'] not in WEEKLY_TERMS:
            raise Bad('В копии повреждены сроки досрочного выкупа.')
        weeks,price=point['weeks'],minor(positive_amount(point.get('price')))
        if weeks<=previous_weeks or price<=previous_price:raise Bad('В копии нарушен порядок тарифов досрочного выкупа.')
        previous_weeks,previous_price=weeks,price
    if previous_weeks!=(d.get('tariff') or {}).get('weeks') or previous_price!=minor(d['total']):
        raise Bad('Тариф досрочного выкупа не совпадает с договором.')

def validate_payoff_record(d):
    record=d['payoff']
    if not isinstance(record,dict) or not (d.get('payoff_terms') or d.get('lease')):
        raise Bad('В копии повреждена запись о досрочном выкупе.')
    date=valid_date(record.get('date'))
    version=record.get('charge_rules_version')
    if version==CHARGE_RULES_VERSION:
        policies=(None,)
    elif version is None:
        # Earlier versions of rental payments used either zero or two grace days.
        policies=(0,2) if d.get('lease') else (0,)
    else:
        raise Bad('В копии неизвестные правила расчёта выкупа.')
    fields=[('amt','principal'),('pen','pen'),('saved','saved'),('price','price')]
    if d.get('lease'):fields.extend((key,key) for key in ('credited','rent_paid'))
    active_deal={**d,'status':'active','payoff':None}
    for grace in policies:
        quote=early_buyout_quote(active_deal,date,legacy_rental_grace=grace)
        if (quote and record.get('fine',0)==quote.get('fine',0)
            and record.get('buyout_reduction',0)==quote.get('buyout_reduction',0)
            and all(record.get(key)==quote[q] for key,q in fields)
            and (quote['total']==0 or record.get('method') in PAYMENT_METHODS)):
            return
    raise Bad('В копии не сходится сумма досрочного выкупа.')

def early_buyout_quote(d,date,*,client=False,legacy_rental_grace=None):
    if d.get('lease'):return rental_payoff_quote(d,date,legacy_rental_grace=legacy_rental_grace)
    terms=d.get('payoff_terms')
    if not terms or d.get('payoff') or d.get('status')!='active' or date<d['start']:return None
    installments=info(d,date,legacy_rental_grace=legacy_rental_grace)
    if installments['done']:return None
    debt=installments['g'] or {}
    if client:
        first=installments['sc'][:CLIENT_PAYOFF_MIN_PERIODS]
        paid_periods=d.get('paid') or {}
        debt_key=str(debt.get('k'))
        if len(first)<CLIENT_PAYOFF_MIN_PERIODS or any(
            str(row['k']) not in paid_periods or str(row['k'])==debt_key for row in first
        ):return None
    if any(p['date']>date for _,_,p in receipt_parts(d)):return None
    paid=minor(d.get('down') or 0)+sum(
        minor(p.get('paid',p['amt']) if kind=='early' else p['amt']) for kind,_,p in receipt_parts(d)
    )
    balance=sum(minor(x['amt']) for x in installments['un'])+minor(debt.get('amt',0))
    elapsed=diff(date,d['start'])
    step=1 if any(minor(x['price'])%100 for x in terms) else 100
    target=minor(terms[-1]['price'])
    for i,point in enumerate(terms):
        day=point['weeks']*7-1
        if elapsed>day:continue
        target=minor(point['price'])
        if i:
            prev=terms[i-1]
            span=(point['weeks']-prev['weeks'])*7
            weighted=minor(prev['price'])*(day-elapsed)+target*(span-day+elapsed)
            target=((2*weighted+span*step)//(2*span*step))*step
        break
    principal=max(0,target-paid);saved=balance-principal
    if saved<=0:return None
    pen=minor(installments['pen']+debt.get('pen',0))
    fine=sum(row['fine'] for row in installments['ods'])
    return {'date':date,'price':money(paid+principal),'paid':money(paid),'principal':money(principal),
            'saved':money(saved),'pen':money(pen),**({'fine':fine} if fine else {}),'total':money(principal+pen),
            'terms':[{**point,'until':add(d['start'],point['weeks']*7-1)} for point in terms],
            'version':d.get('_v',0)}

def record_early_buyout(d,quote,method,qr=None,fees=None):
    d['payoff']={'date':quote['date'],'amt':quote['principal'],'pen':quote['pen'],
                 'saved':quote['saved'],'price':quote['price'],'method':method,'source':qr or nid(),
                 'fees':fees or fee_rates(method),'charge_rules_version':CHARGE_RULES_VERSION,
                 **({'qr':qr} if qr else {})}
    if d.get('lease'):
        d['payoff'].update({key:quote[key] for key in ('credited','rent_paid')})
        if quote['buyout_reduction']:d['payoff']['buyout_reduction']=quote['buyout_reduction']
    if quote.get('fine'):d['payoff']['fine']=quote['fine']

def payment_quote(d,options,t,settings=None,*,client=False,legacy_discount=False):
    if not isinstance(options,dict):raise Bad('Выберите способ оплаты.')
    settings=settings if settings is not None else (doc('cfg') or {})
    unpaid=unpaid_installments(d)
    if d.get('status')!='active' or not unpaid:raise Bad('Сейчас нечего оплачивать.')
    if d.get('lease') and d.get('debt'):raise Bad('Сначала доплатите остаток ближайшего периода.')
    minimum=max(50,min(100,settings.get('dmin',50)))
    mode=options.get('mode','periods')
    if mode=='part':
        if dstat(d,t):raise Bad('Сначала погасите остаток предыдущего платежа.')
        x=unpaid[0]
        if d.get('lease'):
            amount=money(minor(x['amt'])//2)
            if 'amount' in options and positive_amount(options['amount'])!=amount:
                raise Bad(f'Первая часть составляет 50% платы за период, {rub(amount)}.')
        else:
            amount=whole(options.get('amount'));mn=math.ceil(x['amt']*minimum/100);mx=math.ceil(x['amt'])-1
            if mn>mx:raise Bad('Этот взнос доступен только целиком.')
            if not mn<=amount<=mx:raise Bad(f'Часть платежа должна быть от {mn} до {mx} ₽.')
        charges=installment_charges(d,x,t);pe=charges['pen'];fine=charges['fine']
        return {'mode':mode,'date':t,'count':1,'items':[{**x,'amt':amount,'pen':pe,**({'fine':fine} if fine else {})}],
                'principal':amount,'pen':pe,**({'fine':fine} if fine else {}),'total':money(minor(amount)+minor(pe)),
                'bonus':0,'rate':0,'reductions':[],'rest':money(minor(x['amt'])-minor(amount)),
                'debtDue':partial_payment_deadline(d,x)}
    if mode!='periods':raise Bad('Выберите способ оплаты.')
    count=whole(options.get('count',1),'количество платежей')
    if client and count>CLIENT_PAYMENT_MAX_PERIODS:raise Bad('За один раз можно оплатить до четырёх периодов.')
    if not 1<=count<=len(unpaid):raise Bad('Выберите количество платежей.')
    selected=unpaid[:count];selected_sum=sum(minor(x['amt']) for x in selected)
    selected_keys={x['k'] for x in selected}
    tail=sorted(unpaid,key=lambda x:(x['due'],x['k']),reverse=True)
    step=100 if all(minor(x['amt'])%100==0 for x in unpaid) else 1
    rate=float(settings.get('multi_discount',1.5)) if legacy_discount and count>=2 and not d.get('lease') else 0
    if not math.isfinite(rate) or not 0<=rate<=100:raise Bad('Проверьте ставку скидки.')

    def allocate(cash,selected_limit):
        left=math.floor(cash*rate/10000+0.5)*100
        reductions=[]
        for x in tail:
            if not left:break
            selected_row=x['k'] in selected_keys
            amount=min(left,minor(x['amt']),selected_limit if selected_row else left)
            if amount:reductions.append({'k':x['k'],'amt':money(amount)})
            left-=amount
            if selected_row:selected_limit-=amount
        return reductions

    hi=selected_sum//step
    lo=0 if rate else hi
    while lo<hi:
        cash=(lo+hi)//2
        on_selected=sum(minor(x['amt']) for x in allocate(cash*step,selected_sum) if x['k'] in selected_keys)
        if cash*step+on_selected>=selected_sum:hi=cash
        else:lo=cash+1
    principal=money(lo*step);reductions=allocate(lo*step,selected_sum-lo*step)
    by_key={x['k']:minor(x['amt']) for x in reductions};bonus=money(sum(by_key.values()))
    items=[]
    for x in selected:
        charges=installment_charges(d,x,t)
        items.append({**x,'amt':money(minor(x['amt'])-by_key.get(x['k'],0)),'pen':charges['pen'],
                      **({'fine':charges['fine']} if charges['fine'] else {})})
    pe=sum(x['pen'] for x in items);fine=sum(x.get('fine',0) for x in items)
    reduction=rent_batch_reduction(principal,count) if d.get('lease') else 0
    return {'mode':mode,'date':t,'count':count,'items':items,'principal':principal,'pen':pe,
            **({'fine':fine} if fine else {}),**({'buyout_reduction':reduction} if reduction else {}),
            'total':money(minor(principal)+minor(pe)),'bonus':bonus,'rate':rate,'reductions':reductions,'rest':0}

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
    """Apply credit to unpaid periods, starting with the last."""
    left=minor(amount);reductions=[]
    for x in sorted(d['schedule'],key=lambda x:(x['due'],x['k']),reverse=True):
        if str(x['k']) in (d.get('paid') or {}):continue
        used=min(left,minor(x['amt']))
        if used:
            x['amt']=money(minor(x['amt'])-used);left-=used
            reductions.append({'k':x['k'],'due':x['due'],'amt':money(used)})
        if left<=0:break
    return money(minor(amount)-left),reductions

def restore_reductions(d,credit):
    if not credit['amt']:return
    reductions=credit.get('reductions')
    if not reductions:raise Bad('Для старой скидки отсутствует распределение по взносам. Сверьте график с журналом перед отменой.')
    rows={x['k']:x for x in d['schedule']}
    for change in reductions:
        key=change['k'];installment=rows.get(key)
        if not installment or installment['due']!=change['due']:
            raise Bad('После скидки этот взнос был изменён. Сверьте исходный и текущий графики перед отменой.')
        if str(key) in d.get('paid',{}):
            raise Bad('Сначала отмените более позднюю оплату взноса от '+dm(D(installment['due']))+'.')
        installment['amt']=money(minor(installment['amt'])+minor(change['amt']))

def recover_reductions(key,d):
    """Recover older allocations only if the saved before/after amounts prove their distribution."""
    missing=[z for z in (d.get('bonuses') or [])+(d.get('early') or [])
             if z.get('group') and z.get('amt') and not z.get('reductions')]
    if not missing:return
    for previous,current in db.execute("select old,new from log where id=? and (act like 'pay-periods%' or act='pay-qr') order by rowid desc",(key,)):
        if not previous or not current:continue
        old,new=json.loads(previous),json.loads(current)
        before={x['k']:x for x in sched(old)}
        changes=[]
        for x in new.get('schedule') or []:
            prior=before.get(x['k'])
            if prior and prior['due']==x['due'] and minor(prior['amt'])>minor(x['amt']):
                changes.append({'k':x['k'],'due':x['due'],'amt':money(minor(prior['amt'])-minor(x['amt']))})
        for credit in missing[:]:
            recorded=next((z for z in new.get('bonuses') or [] if z==credit),None)
            existed=any(z['group']==credit['group'] for z in old.get('bonuses') or [])
            if recorded and not existed and sum(minor(x['amt']) for x in changes)==minor(credit['amt']):
                credit['reductions']=changes;missing.remove(credit)
        if not missing:break

def apply_payment(d,quote,method,qr=None,fees=None):
    if sum(minor(x['amt'])+minor(x['pen']) for x in quote['items'])!=minor(quote['total']):
        raise Bad('Распределение не совпадает с суммой оплаты. Рассчитайте платёж заново.')
    if d.get('lease'):
        if d.get('debt'):raise Bad('Сначала доплатите остаток ближайшего периода.')
        source=qr or nid()
        for installment in quote['items']:
            key=installment['k']
            put_paid(d,key,quote['date'],installment['amt'],installment['pen'],method,qr,quote['mode']=='part',
                     source=source,fees=fees,fine=installment.get('fine',0))
            if quote['count']>1:
                d['paid'][str(key)].update(group=source,batch_count=quote['count'])
        # Record one reduction per received payment. Cancelling the batch removes it too.
        if quote['mode']=='periods' and quote['count']>1:
            rent=money(sum(minor(row['amt']) for row in quote['items']))
            first=d['paid'][str(quote['items'][0]['k'])]
            first['buyout_reduction']=rent_batch_reduction(rent,len(quote['items']))
        if quote['rest']:d['debt']={'k':quote['items'][0]['k'],'amt':quote['rest'],'due':quote['debtDue']}
        return source
    materialize_schedule(d)
    group=nid();reductions={x['k']:minor(x['amt']) for x in quote['reductions']};changes=[]
    for row_ in d['schedule']:
        amount=reductions.get(row_['k'],0)
        if amount:
            row_['amt']=money(minor(row_['amt'])-amount)
            changes.append({'k':row_['k'],'due':row_['due'],'amt':money(amount)})
    for x in quote['items']:
        put_paid(d,x['k'],quote['date'],x['amt'],x['pen'],method,qr,quote['mode']=='part',source=qr or group,fees=fees,
                 fine=x.get('fine',0))
        d['paid'][str(x['k'])].update(group=group,due=x['due'],batch_count=quote['count'])
    if quote['rest']:
        d['debt']={'k':quote['items'][0]['k'],'amt':quote['rest'],'due':quote['debtDue']}
    if quote['bonus']:
        d.setdefault('bonuses',[]).append({'group':group,'date':quote['date'],'amt':quote['bonus'],
                                         'base':quote['principal'],'rate':quote['rate'],'ks':[x['k'] for x in quote['items']],
                                         'reductions':changes})
    return group

def changeable_installments(d, date, schedule=None):
    if d.get('payoff'):return []
    paid = d.get('paid') or {}
    current = sched(d) if schedule is None else schedule
    return [x for x in current if str(x['k']) not in paid and x['due'] >= date and payment_deadline(d,x) == x['due']]

def client_schedule_bounds(d, date, anchor=None):
    future = changeable_installments(d, date)
    if not future:
        raise Bad('В графике нет будущих платежей для перерасчёта.')
    anchor = anchor or min(x['due'] for x in future)
    return anchor, max(date, add(anchor,-7)), min(add(anchor,7), max(x['due'] for x in future))

def replan(d,first_due,weekly,t,client_anchor=None):
    first_due = valid_date(first_due)
    weekly = whole(weekly, 'сумму платежа')
    if first_due < t:
        raise Bad('Выберите дату следующего платежа начиная с сегодняшнего дня.')
    if weekly < 1:
        raise Bad('Введите сумму платежа в целых рублях.')

    current = sched(d)
    paid = d.get('paid') or {}
    future = changeable_installments(d, t, current)
    future_keys = {row['k'] for row in future}
    kept = [row for row in current if row['k'] not in future_keys]
    balance = money(sum(minor(row['amt']) for row in future))
    if not balance:
        raise Bad('В графике нет будущих платежей для перерасчёта.')
    if client_anchor:
        _, earliest, latest = client_schedule_bounds(d, t, client_anchor)
        if not earliest <= first_due <= latest:
            raise Bad('Дата нового взноса должна быть в пределах 7 дней от даты в заявке.')

    last_due = max(row['due'] for row in future)
    if first_due > last_due:
        raise Bad('Выберите дату не позднее последнего платежа действующего графика.')
    step = 30 if d['type'] == 'm' else 7
    slots = math.ceil(diff(last_due, first_due) / step) + 1
    count = min(slots, math.ceil(balance / weekly))
    if count == 1 and first_due < last_due:
        raise Bad('Укажите взнос меньше остатка или выберите дату последнего платежа для оплаты всей суммы.')
    if count > 5200:
        raise Bad('Получается слишком длинный график. Увеличьте сумму платежа.')

    max_key = max([d.get('n', 0)] + [row['k'] for row in current])
    changed = []
    for index in range(count):
        key = future[index]['k'] if index < len(future) else max_key + index - len(future) + 1
        final = index == count - 1
        due_date = last_due if final else add(first_due, step * index)
        amount = money(minor(balance)-minor(weekly)*index) if final else weekly
        changed.append({'k': key, 'due': due_date, 'amt': amount})

    deferred = [row for row in kept if str(row['k']) not in paid and payment_deadline(d,row) >= t]
    def schedule_order(row):return row['due'],row['k']
    ending = sorted(deferred + changed,key=schedule_order)[-2:]
    previous = ending[-2]['due'] if len(ending) > 1 else None
    last = ending[-1]
    return {
        'schedule': sorted(kept + changed, key=lambda row: (row['due'], row['k'])),
        'balance': balance, 'count': count, 'pay': weekly, 'asOf': t, 'first': first_due,
        'firstAmount': changed[0]['amt'], 'last': last['due'], 'lastAmount': last['amt'],
        'previous': previous, 'gap': diff(last['due'], previous) if previous else None, 'step': step,
        'before': future, 'after': changed,
        'beforeEnding':sorted(deferred + future,key=schedule_order)[-2:], 'afterEnding':ending,
        'keptOverdue': sum(row['amt'] for row in kept if str(row['k']) not in paid and payment_deadline(d,row) < t),
        'keptDeferred': sum(row['amt'] for row in deferred),
        'debt': (dstat(d,t) or {}).get('total',0),
    }

def reschedule_details(plan):
    return {key: plan[key] for key in (
        'first', 'firstAmount', 'pay', 'balance', 'last', 'lastAmount', 'previous', 'gap', 'step'
    )}

def fingerprint(d):
    fields=('status','schedule','n','start','type','pay','last','paid','early','shift','pen','pw','np','debt','dpays','bonuses')
    data={k:d.get(k) for k in fields}
    # Migrating fee records does not invalidate a QR printed before the update.
    for field in ('paid','early','dpays'):
        if field in d and d[field] is not None:
            data[field] = payment_public(d)[field]
    grants=[grant for grant in d.get('defer') or [] if grant.get('until')]
    if grants:data['deferrals']=grants
    if d.get('lease'):data['lease']=d['lease']
    if d.get('late_fee'):data['late_fee']=d['late_fee']
    for field in ('payoff_terms','payoff'):
        if d.get(field):data[field]=d[field] if field=='payoff_terms' else payment_public(d)[field]
    return hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()

def completion_notice(old,new):
    if new.get('status')!='active':return
    if not info(new)['done']:
        new.pop('completed_at',None)
        return
    if not new.get('completed_at'):
        new['completed_at']=(new.get('payoff') or {}).get('date') or tod()
        tell(new.get('client'),'Все платежи по выкупу внесены. Приезжайте для подписания документов и получения второго комплекта ключей. Перед приездом согласуйте время с нами.')

# ---------- what can be paid, and how a payment is applied to the deal ----------
def q_now(d,t,*,client=False):
    """Quote due periods or the next period, respecting the client's payment limit."""
    I=info(d,t)
    if d.get('status')!='active' or not I['x']:return None
    count=1 if d.get('lease') else len(I['od']) or 1
    if client:count=min(count,CLIENT_PAYMENT_MAX_PERIODS)
    quote=payment_quote(d,{'count':count},t,client=client)
    return {**quote,'amt':quote['total'],'ks':[x['k'] for x in quote['items']]}
def q_debt(d,t):
    g=dstat(d,t) if d.get('status')=='active' else None
    return g and {'amt':g['total'],'pen':g['pen'],'g':g}
def plan_period(d,A,t):
    """Plan a payment for the nearest unpaid period, using the agreed payment rules."""
    if d.get('lease'):
        quote=payment_quote(d,{},t)
        if minor(A)!=minor(quote['total']):
            part=payment_quote(d,{'mode':'part'},t)
            if minor(A)!=minor(part['total']):
                return f"За период нужно {rub(quote['total'])} целиком или {rub(part['total'])} первой частью."
            quote=part
        return {'k':quote['items'][0]['k'],'pen':quote['pen'],'fine':quote.get('fine',0),'pay':quote['principal'],
                'rest':quote['rest'],'left':0,'debtDue':quote.get('debtDue')}
    I=info(d,t);x=I['x']
    if d.get('status')!='active' or not x:return 'Нечего оплачивать.'
    charges=installment_charges(d,x,t)
    pen,fine=charges['pen'],charges['fine']
    amount=minor(A);due=minor(x['amt']);principal=amount-minor(pen)
    if principal>=due:return {'k':x['k'],'pen':pen,'fine':fine,'pay':x['amt'],'rest':0,'left':money(principal-due)}
    if I['g']:return 'Пока не закрыт долг, период можно оплатить только целиком.'
    mn=minpart(x)
    if principal<minor(mn):return f'Сумма за период должна быть не меньше {rub(mn+pen)}.'
    return {'k':x['k'],'pen':pen,'fine':fine,'pay':money(principal),'rest':money(due-principal),'left':0,
            'debtDue':partial_payment_deadline(d,x)}
def put_paid(d,k,t,amt,pen,method,qr=None,part=False,source=None,fees=None,*,fine=0):
    due_=next((x['due'] for x in sched(d) if x['k']==k),None)
    p={'date':t,'amt':amt,'pen':pen,'method':method,'source':source or qr or nid(),'fees':fees or fee_rates(method)}
    if due_:p['due']=due_
    if part:p['part']=1
    if qr:p['qr']=qr
    if fine:p['fine']=fine
    d.setdefault('paid',{})[str(k)]=p
def apply_plan(d,p,t,method,qr=None,fees=None,source=None):
    put_paid(d,p['k'],t,p['pay'],p['pen'],method,qr,p['rest']>0,fees=fees,source=source,fine=p.get('fine',0))
    if p['rest']>0:d['debt']={'k':p['k'],'amt':p['rest'],'due':p['debtDue']}
    return p['left']
def apply_debt(d,A,t,method,qr=None,source=None,fees=None):
    """Money for the open debt: the penalty first, then the remainder. Returns what is left over."""
    g=dstat(d,t)
    if not g:raise Bad('Долга нет.')
    if d.get('lease') and minor(A)<minor(g['total']):raise Bad('Остаток периода оплачивается одним платежом целиком.')
    if A<=g['pen']:raise Bad(f"Сумма должна быть больше неустойки {rub(g['pen'])}.")
    available=minor(A)-minor(g['pen']);owed=minor(g['amt'])
    pr=money(min(available,owed));left=money(max(0,available-owed));rest=money(max(0,owed-available))
    z={'date':t,'amt':pr,'pen':g['pen'],'method':method,'k':g['k'],'pv':dict(d['debt']),
       'source':source or qr or nid(),'fees':fees or fee_rates(method)}
    if qr:z['qr']=qr
    d.setdefault('dpays',[]).append(z)
    if rest>0:
        d['debt']={**d['debt'],'amt':rest}
        if t>d['debt']['due']:d['debt']['pb']=t
    else:d.pop('debt',None)
    return left
def apply_money(d,kind_,A,t,method,qr=None,fees=None,source=None,settle_debt=True):
    """Bills and unrecognised payments: kind_ is 'period' or 'debt'. Returns what is left over (an overpayment); raises Bad when it cannot be applied."""
    source=source or qr or nid()
    if kind_=='debt':return apply_debt(d,A,t,method,qr,source=source,fees=fees)
    p=plan_period(d,A,t)
    if isinstance(p,str):raise Bad(p)
    left=apply_plan(d,p,t,method,qr,fees=fees,source=source)
    if settle_debt and left>0 and dstat(d,t):
        try:left=apply_debt(d,left,t,method,qr,source=source,fees=fees)
        except Bad:pass
    return left
def lg(d):return {k:v for k,v in d.items() if k not in('img','jwt','attachment','payload')}
def client_log_actor(identifier):
    name=str((doc(identifier) or {}).get('name') or '').strip()[:40]
    return f'Клиент · {name}' if name else 'Клиент'
def put_srv(i,k,d,act,by='',old=None):
    """Write a document from a server-side action (a QR payment, a bill): bumps _v for deals so that stale screens get a conflict."""
    if k=='deal':completion_notice(old,d)
    if k in ('deal','bike','client'):d['_v']=d.get('_v',0)+1
    save(i,k,d);db.execute('insert into log values(?,?,?,?,?)',(dt.datetime.now(MSK).isoformat(),act+(('@'+by) if by else ''),i,old and strip(json.dumps(lg(old))),strip(json.dumps(lg(d)))))
def docs_of(k):
    return [(i,json.loads(x)) for i,x in db.execute('select id,data from docs where kind=?',(k,)).fetchall()]

def download_file(name,mime,data,deal=None):
    now=time.time()
    for key in list(FILE_DL):
        if FILE_DL[key][0]<now:FILE_DL.pop(key,None)
    while len(FILE_DL)>=32:FILE_DL.pop(next(iter(FILE_DL)))
    key=secrets.token_urlsafe(22)
    FILE_DL[key]=(now+180,name,mime,data,deal)
    return {'url':'/files/'+key,'name':name}

def calendar_data(key,d,t):
    rows=sched(d)
    events=[]
    for number,installment in enumerate(rows,1):
        if str(installment['k']) in (d.get('paid') or {}):continue
        limit=payment_deadline(d,installment)
        if limit<t:continue
        original=f"Взнос по графику {dm(D(installment['due']))}." if limit!=installment['due'] else ''
        events.append((f"{key}-{installment['k']}",limit,f"Выкуп, взнос {number} — {rub(installment['amt'])}",original))
    debt=dstat(d,t)
    if debt and not debt['over']:
        events.append((f"{key}-debt-{debt['k']}",debt['due'],f"Доплата за электровелосипед — {rub(debt['amt'])}",''))
    if not events:raise Bad('В графике нет предстоящих платежей.')
    def escape(value):return value.replace('\\','\\\\').replace(';','\\;').replace(',','\\,').replace('\n','\\n')
    def fold(value):
        lines=[];line='';length=0
        for c in value:
            size=len(c.encode('utf-8'))
            if length+size>75:lines.append(line);line=' ';length=1
            line+=c;length+=size
        return '\r\n'.join(lines+[line])
    stamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    lines=['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//Volt Voyage//Vykup//RU','CALSCALE:GREGORIAN']
    for uid,limit,summary,desc in sorted(events,key=lambda e:e[1]):
        lines+=['BEGIN:VEVENT',f'UID:{uid}@volt-voyage-vykup',f'DTSTAMP:{stamp}',f"DTSTART;VALUE=DATE:{limit.replace('-','')}",
                f'SUMMARY:{escape(summary)}',f'DESCRIPTION:{escape(desc)}','END:VEVENT']
    return ('\r\n'.join(fold(line) for line in lines+['END:VCALENDAR',''])).encode('utf-8')

def payment_report_summary(record):
    return {key:value for key,value in record.items() if key!='attachment'} | {'hasAttachment':bool(record.get('attachment'))}

def decode_upload(value,max_size):
    if not isinstance(value,str) or not value or len(value)>4*((max_size+2)//3):raise Bad('Проверьте размер и формат файла.')
    try:data=base64.b64decode(value,validate=True)
    except (ValueError,binascii.Error):raise Bad('Не удалось прочитать файл.')
    if not data or len(data)>max_size:raise Bad('Проверьте размер файла.')
    return data

def proof_file(value):
    data=decode_upload(value,1500000)
    extensions=(('pdf','application/pdf',b'%PDF-'),('jpg','image/jpeg',b'\xff\xd8\xff'),('png','image/png',b'\x89PNG\r\n\x1a\n'))
    for extension,mime,signature in extensions:
        if data.startswith(signature):return extension,mime,data
    raise Bad('Прикрепите квитанцию в формате PDF, JPG или PNG.')

def payment_report_action(b,ro,x,t,by):
    action=b.get('do')
    if ro=='client' and action=='submit':
        key,d=action_deal(b,ro,x,allow_client=True)
        date=valid_date(b.get('date'));amount=statement_amount(b.get('amount'))
        if date>t:raise Bad('Дата платежа не может быть в будущем.')
        reference=str(b.get('reference') or '').strip()[:180]
        note=str(b.get('note') or '').strip()[:1000]
        attachment=b.get('attachment') or ''
        if attachment:proof_file(attachment)
        data={'deal':key,'client':x,'date':date,'amount':amount,'reference':reference,'note':note,'attachment':attachment,'status':'pending'}
        for i,record in docs_of('paymentreport'):
            if all(record.get(k)==v for k,v in data.items()):return {'id':i}
        key=nid();data['created']=dt.datetime.now(MSK).isoformat();put_srv(key,'paymentreport',data,'payment-report',by)
        say(f"Обращение об оплате от {(doc(x) or {}).get('name','')}, {amount/100:.2f} ₽. Откройте карточку выкупа.")
        return {'id':key}
    i=str(b.get('id') or '');record=ID.fullmatch(i) and row(i)
    if not record or record[0]!='paymentreport':raise Bad('Обращение не найдено.')
    data=record[1]
    action_deal({'deal':data['deal']},ro,x,allow_client=action=='receipt')
    if ro=='client' and data.get('client')!=x:raise Bad('Обращение не найдено.')
    if action=='receipt':
        if not data.get('attachment'):raise Bad('Квитанция не прикреплена.')
        extension,mime,raw=proof_file(data['attachment'])
        return download_file('kvitanciya.'+extension,mime,raw,data['deal'])
    if action=='resolve' and data.get('status')=='pending':
        status=b.get('status')
        if status not in ('credited','not_found'):raise Bad('Выберите результат проверки.')
        old=dict(data);data.update(status=status,resolved=t,answer=str(b.get('answer') or '').strip()[:1000])
        put_srv(i,'paymentreport',data,'payment-report-resolve',by,old)
        return {}
    raise Bad('Обращение уже рассмотрено.')

def existing_receipts(deal_id=None):
    payments={}
    def add_receipt(deal,d,date,method,cash,src,qr=None):
        if not date or method not in ('СБП','перевод') or not cash:return
        identity=(deal,src,date,method)
        if identity not in payments:
            payments[identity]={'deal':deal,'source':src,'date':date,'method':method,'qr':qr,'amount':0,'contract':d.get('contract') or ''}
        payments[identity]['amount']+=minor(cash)
    for deal,d in docs_of('deal'):
        if deal_id and deal!=deal_id:continue
        records=list(receipt_parts(d))
        if d.get('down'):
            method=d.get('down_method') or ((d.get('paid') or {}).get('1') or {}).get('method')
            records.append(('down',0,{'date':d['start'],'amt':d['down'],'method':method,'source':d.get('down_source') or 'down'}))
        for kind,key,p in records:
            date,method,cash=receipt_cash(p,kind)
            src=p.get('source') or p.get('qr') or (p.get('group') if kind=='paid' else None) or f'{kind}-{key}'
            add_receipt(deal,d,date,method,cash,src,p.get('qr'))
    for _,z in docs_of('unk'):
        deal=z.get('deal');src=z.get('source') or z.get('qr')
        if src and not z.get('unconfirmed') and z.get('status') in ('open','done') and (not deal_id or deal==deal_id):
            add_receipt(deal,doc(deal) or {},z.get('date'),z.get('method','СБП'),z.get('amt'),src,z.get('qr'))
    return list(payments.values())

def possible_duplicate(deal, date, total):
    return next((p for p in existing_receipts(deal) if p['qr'] and p['date']==date and p['amount']==round(total*100)),None)

def statement_amount(value):
    clean=re.sub(r'[\s\u00a0₽]', '', str(value or '')).replace(',','.')
    try:
        number=Decimal(clean)
        if not number.is_finite() or abs(number)>Decimal('1000000000'):raise InvalidOperation()
        cents=int((number*100).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
    except (InvalidOperation,ValueError):raise Bad('Проверьте сумму платежа.')
    if cents<=0:raise Bad('Сумма платежа должна быть больше нуля.')
    return cents

STATEMENT_FIELDS={
    'date':('дата','датаоперации','датаплатежа','датапроводки','датадокумента','датазачисления','date','operationdate','bookingdate'),
    'credit':('кредит','приход','зачислено','суммазачисления','входящаясумма','кредитруб','credit','creditamount'),
    'amount':('сумма','суммаоперации','суммаплатежа','суммаврублях','суммаруб','суммавалюте','amount','transactionamount'),
    'direction':('тип','направление','движение','типоперации','видоперации','direction','type'),
    'purpose':('назначение','назначениеплатежа','описание','комментарий','детали','description','purpose','details'),
    'reference':('идентификатор','идентификатороперации','idоперации','номероперации','номерплатежа','номердокумента','номер','transactionid','operationid','reference','rrn','id'),
}

def normalize_column(text):return re.sub(r'[^а-яa-z0-9]','',str(text).lower().replace('ё','е'))

def statement_columns(rows):
    for index,line in enumerate(rows[:60]):
        names=[normalize_column(cell) for cell in line]
        cols={field:next((i for alias in choices for i,name in enumerate(names) if name==alias),None)
              for field,choices in STATEMENT_FIELDS.items()}
        if cols['date'] is not None and (cols['amount'] is not None or cols['credit'] is not None):return index,cols
    return None

def xlsx_cells(raw):
    ns='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
    with zipfile.ZipFile(io.BytesIO(raw)) as book:
        def xml(name):
            if book.getinfo(name).file_size>16000000:raise Bad('Таблица слишком большая. Загрузите выписку за меньший период.')
            data=book.read(name)
            if re.search(br'<!\s*(?:doctype|entity)',data,re.I):raise Bad('Не удалось прочитать XLSX.')
            return ET.fromstring(data)
        sheets=[i for i in book.namelist() if re.fullmatch(r'xl/worksheets/sheet\d+\.xml',i)]
        strings=[]
        if 'xl/sharedStrings.xml' in book.namelist():
            strings=[''.join(t.text or '' for t in node.iter(ns+'t')) for node in xml('xl/sharedStrings.xml').findall(ns+'si')]
        workbook=xml('xl/workbook.xml')
        properties=workbook.find(ns+'workbookPr')
        date1904=properties is not None and properties.get('date1904') in ('1','true')
        for name in sheets[:20]:
            data=[]
            for row_ in xml(name).iter(ns+'row'):
                if len(data)>=15000:raise Bad('Загрузите выписку за меньший период.')
                values=[]
                for cell in row_.findall(ns+'c'):
                    match=re.match(r'[A-Z]+',cell.get('r') or '');index=0
                    if not match:continue
                    for letter in match[0]:index=index*26+ord(letter)-64
                    if not 1<=index<=128:continue
                    value=cell.findtext(ns+'v',default='');kind=cell.get('t')
                    if kind=='s':value=strings[int(value)] if value else ''
                    elif kind=='inlineStr':value=''.join(t.text or '' for t in cell.iter(ns+'t'))
                    values.extend(['']*max(0,index-len(values)));values[index-1]=value
                data.append(values)
            if statement_columns(data):return data,date1904
    return [],False

def statement_date(value,date1904=False):
    value=str(value).strip()
    try:
        if re.fullmatch(r'\d{4,6}(?:\.\d+)?',value):
            epoch=dt.date(1904,1,1) if date1904 else dt.date(1899,12,30)
            return (epoch+dt.timedelta(days=int(float(value)))).isoformat()
        if re.match(r'\d{4}-\d{2}-\d{2}',value):return valid_date(value[:10])
        for pattern in ('%d.%m.%Y','%d/%m/%Y','%d-%m-%Y'):
            try:return dt.datetime.strptime(value.split()[0],pattern).date().isoformat()
            except ValueError:continue
    except (ValueError,IndexError,OverflowError):pass
    raise Bad('Не удалось разобрать дату.')

def read_statement(value):
    raw=decode_upload(value,2000000);date1904=False
    try:
        if raw.startswith(b'PK\x03\x04'):rows,date1904=xlsx_cells(raw)
        else:
            try:body=raw.decode('utf-8-sig')
            except UnicodeDecodeError:body=raw.decode('cp1251')
            candidates=(list(csv.reader(io.StringIO(body),delimiter=delimiter)) for delimiter in (';','\t',','))
            rows=next((r for r in candidates if statement_columns(r)),[])
    except (ValueError,IndexError,KeyError,UnicodeError,ET.ParseError,zipfile.BadZipFile,csv.Error):
        raise Bad('Не удалось открыть выписку. Загрузите CSV или XLSX.')
    columns=statement_columns(rows)
    if not columns:raise Bad('Нужны колонки «Дата» и «Сумма» или «Кредит». Подойдут также «Назначение платежа» и «Номер операции».')
    index,cols=columns;operations=[];labels=False;skipped=0
    for line in rows[index+1:]:
        if not any(line):continue
        def get(field):
            i=cols[field];return str(line[i]).strip() if i is not None and i<len(line) else ''
        credit=cols['credit'] is not None
        if re.search(r'списан|исходящ|расход|debit|outgoing',get('direction'),re.I):continue
        try:
            amount=statement_amount(get('credit' if credit else 'amount'))
            date=statement_date(get('date'),date1904)
        except Bad:
            if get('date') and (not credit or get('credit')):skipped+=1
            continue
        purpose=get('purpose')[:280];direction=get('direction');reference=get('reference')[:180]
        sbp=bool(re.search(r'(?<![а-яa-z])(?:сбп|sbp)(?![а-яa-z])|систем[аы]\s+быстрых\s+платеж',direction+' '+purpose,re.I))
        labels=labels or sbp
        operations.append({'date':date,'amount':amount,'purpose':purpose,'reference':reference,'sbp':sbp})
        if len(operations)>5000:raise Bad('Загрузите выписку за меньший период. За одну сверку можно проверить до 5000 поступлений.')
    return operations,not labels,skipped

def statement_key(operation):
    date=valid_date(operation.get('date'));amount=operation.get('amount')
    if type(amount) is not int or not 0<amount<=100000000000:raise Bad('Проверьте сумму операции в копейках.')
    reference=str(operation.get('reference') or '').strip().lower()[:180]
    purpose='' if reference else ' '.join(str(operation.get('purpose') or '').lower()[:280].split())
    return hashlib.sha256(json.dumps([date,amount,reference,purpose],ensure_ascii=False).encode()).hexdigest()[:16]

def statement_review(operations):
    receipts=existing_receipts();by_amount={};by_source={};refs={}
    for i,q in docs_of('qr'):
        refs[i]={str(q[k]).strip().lower() for k in ('tid','trxId','refTransactionId') if q.get(k)}
    for p in receipts:
        by_amount.setdefault((p['date'],p['amount']),[]).append(p)
        by_source[(p['deal'],p['source'],p['date'],p['amount'])]=p
    links=dict(docs_of('statementlink'));claimed={(z['deal'],z['source'],z['date'],z['amount']):i for i,z in links.items()}
    seen=set();duplicates=set()
    for operation in operations:
        k=statement_key(operation)
        if k in seen:duplicates.add(k)
        seen.add(k)
    exact_matches={}
    for operation in operations:
        k=statement_key(operation);reference=str(operation.get('reference') or '').strip().lower()
        if not reference or k in duplicates or k in links:continue
        hits=[p for p in by_amount.get((operation['date'],operation['amount']),[])
              if reference in refs.get(p['qr'],()) and (p['deal'],p['source'],p['date'],p['amount']) not in claimed]
        if len(hits)==1:
            payment=hits[0];exact_matches[k]=payment
            claimed[(payment['deal'],payment['source'],payment['date'],payment['amount'])]=k
    result=[]
    for operation in operations:
        k=statement_key(operation);op={**operation,'key':k};link=links.get(k) or {}
        linked=by_source.get((link.get('deal'),link.get('source'),op['date'],op['amount']))
        matches=[p for p in by_amount.get((op['date'],op['amount']),[]) if (p['deal'],p['source'],p['date'],p['amount']) not in claimed]
        if k in duplicates:op.update(state='duplicate',matches=[])
        elif linked:op.update(state='linked',payment=linked,matches=[])
        elif k in exact_matches:op.update(state='exact',payment=exact_matches[k],matches=[])
        else:op.update(state='possible' if matches else 'unmatched',matches=matches[:30])
        result.append(op)
    return result

def link_statement(operation,deal,source,by=''):
    key=statement_key(operation);date=operation['date'];amount=operation['amount']
    old=doc(key)
    matching=next((p for p in existing_receipts(deal) if p['source']==source and (p['date'],p['amount'])==(date,amount)),None)
    if not matching:raise Bad('Платёж изменился. Сверьте выписку ещё раз.')
    if old and (old.get('deal'),old.get('source'))!=(deal,source) and any(p['source']==old.get('source') and p['date']==date and p['amount']==amount for p in existing_receipts(old['deal'])):
        raise Bad('Строка выписки уже привязана к другому платежу.')
    if any(i!=key and z.get('deal')==deal and z.get('source')==source and z.get('date')==date for i,z in docs_of('statementlink')):
        raise Bad('Этот платёж уже связан с другой строкой выписки.')
    data={'deal':deal,'source':source,'date':date,'amount':amount,'reference':str(operation.get('reference') or '')[:180]}
    put_srv(key,'statementlink',data,'statement-link',by,old)
    return matching
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
    n=dt.datetime.now(MSK);midnight=dt.datetime.combine(n.date()+dt.timedelta(days=1),dt.time(),MSK)
    ttl=int(((midnight-n).total_seconds()-(0 if t.get('mock') else 25))//60)
    if ttl<1:raise Bad('До полуночи по Москве осталось мало времени. Запросите QR после 00:00.')
    expires=(n+dt.timedelta(minutes=ttl)).isoformat(timespec='seconds')
    if t.get('mock'):return {'id':'mock'+nid(),'payload':'https://qr.nspk.ru/MOCK'+nid(),'img':None,'expires':expires}
    try:
        r=tochka(t,'POST',f"/sbp/v1.0/qr-code/merchant/{urllib.parse.quote(t['merchant'],safe='')}/{t['account']}",{'Data':{'amount':minor(amt),'currency':'RUB','paymentPurpose':purpose[:140],
            'qrcType':'02','ttl':ttl,'imageParams':{'width':400,'height':400,'mediaType':'image/png'}}})['Data']
        return {'id':r['qrcId'],'payload':r['payload'],'img':(r.get('image') or {}).get('content'),'expires':expires}
    except urllib.error.HTTPError as e:
        print('tochka qr',e.code,e.read()[:300])
        raise Bad('Точка не приняла токен. Проверьте его в Настройках.' if e.code in(401,403) else 'Точка не нашла торговую точку или счёт. Проверьте их ID в Настройках.' if e.code in(400,404) else 'Точка не ответила, попробуйте ещё раз.')
    except Exception as e:
        print('tochka qr',e);raise Bad('Точка не ответила, попробуйте ещё раз.')
def qr_paid(t,ids):
    """Which of the QR codes are paid (the bank's answer)."""
    if t.get('mock') or not ids:return {}
    r=tochka(t,'GET','/sbp/v1.0/qr-codes/'+','.join(ids)+'/payment-status')['Data']
    return {x['qrcId']:x for x in r.get('paymentList',[]) if x.get('qrcId') and x.get('status')=='Accepted'}

def qr_expiry(q):
    if q.get('expires'):return dt.datetime.fromisoformat(q['expires'])
    return dt.datetime.combine(D(q['date'])+dt.timedelta(days=1),dt.time(),MSK)
def qr_amount(d,kind_,t,bill=None,options=None,settings=None,*,client=False):
    """(amount, penalty inside it, periods) of a QR of this kind right now; raises Bad when there is nothing to pay."""
    if kind_=='now':
        z=q_now(d,t,client=client)
        if not z:raise Bad('Нечего оплачивать.')
        return z['amt'],z['pen'],z['ks'],z
    if kind_=='selection':
        z=payment_quote(d,options or {},t,settings,client=client)
        if 'preview' in (options or {}):
            preview={'version':d.get('_v',0),'date':t,'total':z['total']}
            if z.get('debtDue'):preview['debtDue']=z['debtDue']
            if isinstance(options['preview'],dict) and 'buyout_reduction' in options['preview']:
                preview['buyout_reduction']=z.get('buyout_reduction',0)
            if options['preview']!=preview:raise Bad('График оплаты обновился. Откройте расчёт заново.')
        # Keep the bank quote compatible with open QR codes from before the reduction was introduced.
        z.pop('buyout_reduction',None)
        return z['total'],z['pen'],[x['k'] for x in z['items']],z
    if kind_=='payoff':
        z=early_buyout_quote(d,t,client=client)
        if not z or not z['total']:raise Bad('Сейчас выкуп недоступен.' if d.get('lease') else 'Сейчас досрочный платёж недоступен.')
        if not options or options.get('version')!=z['version'] or options.get('date')!=t or options.get('total')!=z['total']:
            raise Bad('Условия изменились. Откройте расчёт досрочного выкупа заново.')
        return z['total'],z['pen'],None,z
    if kind_=='debt':
        z=q_debt(d,t)
        if not z:raise Bad('Долга нет.')
        return z['amt'],z['pen'],None,None
    if kind_=='bill':
        if not bill or bill.get('status')!='open':raise Bad('Платёж уже закрыт.')
        if bill['kind']=='period':
            p=plan_period(d,bill['amt'],t)
            if isinstance(p,str):raise Bad(p)
            return bill['amt'],p['pen'],None,p
        else:
            debt=q_debt(d,t)
            if not debt:raise Bad('Долга нет.')
            if d.get('lease') and minor(bill['amt'])!=minor(debt['amt']):
                raise Bad('Сумма доплаты изменилась. Свяжитесь с владельцем.')
            return bill['amt'],debt['pen'],None,None
    raise Bad('Неверный запрос.')
def qr_request(u,cl,b):
    with QR_LOCKS[hash(str(b.get('deal') or ''))%len(QR_LOCKS)]:
        return register_qr(u,cl,b)

def register_qr(u,cl,b):
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
        settings={'dmin':cfgv('dmin',50)}
        before=fingerprint(d)
        amt,pe,ks,quote=qr_amount(d,k,t,bill,options,settings,client=cl)
        for j,q in docs_of('qr'):
            if q.get('deal')==i and q.get('status')=='open' and not q.get('access_revoked') and q.get('date')==t and qr_expiry(q)>dt.datetime.now(MSK) and q.get('kind')==k and q.get('amt')==amt and q.get('bill')==(bid if bill else None) and q.get('fingerprint')==before and q.get('quote')==quote:return {'qr':j}
        title=('Выкуп' if k=='payoff' else 'Аренда') if d.get('lease') else ('Досрочный выкуп' if k=='payoff' else 'Выкуп')
        purpose=f"{title} электровелосипеда, договор {d.get('contract') or '—'}, {(doc(d.get('client')) or {}).get('name','')}"
        actor=client_log_actor(x) if cl else str(x[1].get('name') or 'Администратор')[:40] if ro=='admin' else 'Владелец'
    m=qr_make(tc,amt,purpose)
    with L:
        d=doc(i);bill=doc(bid) if bill else None
        if not d or fingerprint(d)!=before or qr_amount(d,k,t,bill,options,settings,client=cl)[0]!=amt or tod()!=t:raise Bad('Данные изменились, откройте экран заново.')
        qid=nid();put_srv(qid,'qr',{'deal':i,'kind':k,'amt':amt,'pen':pe,'ks':ks,'quote':quote,'options':options,'settings':settings,'fingerprint':before,'bill':bid if bill else None,'date':t,'status':'open','tid':m['id'],'payload':m['payload'],'img':m['img'],'expires':m.get('expires'),'ts':dt.datetime.now(MSK).isoformat(timespec='seconds')},'qr',actor)
        db.commit();return {'qr':qid}

def bank_payment_date(payment,q):
    for field in ('paymentDate','paymentDateTime','operationDate','acceptedAt'):
        value=payment.get(field)
        if not isinstance(value,str):continue
        try:
            when=dt.datetime.fromisoformat(value.replace('Z','+00:00'))
            date=when.astimezone(MSK).date().isoformat() if when.tzinfo else valid_date(value)
            if q['date']<=date<=tod():return date,value
        except (ValueError,Bad):pass
    return (q['date'],None) if q['date']==tod() else (None,None)

def on_paid(qid,q,payment=None):
    """The bank confirmed a QR payment. It is credited automatically when nothing changed since the QR was made (same day, same amount);
    otherwise it goes to «Не распознано». Call with the lock held."""
    if q.get('status')!='open':return
    payment=payment or {};old=dict(q)
    for field in ('trxId','refTransactionId'):
        if payment.get(field):q[field]=str(payment[field])[:180]
    q['confirmedAt']=dt.datetime.now(MSK).isoformat(timespec='seconds')
    t,bank_time=bank_payment_date(payment,q)
    if q.get('trxId') and any(i!=qid and z.get('status')=='paid' and z.get('trxId')==q['trxId'] for i,z in docs_of('qr')):
        q['status']='duplicate';put_srv(qid,'qr',q,'qr-duplicate','',old);return
    q.update(status='paid',fees=fee_rates('СБП'),paidDate=t,bankTime=bank_time)
    put_srv(qid,'qr',q,'qr-paid','',old)
    d=doc(q['deal']);left=q['amt'];why='Оплата пришла после изменений в выкупе или не в день создания QR.';ok=False
    if d and d.get('status')=='active' and t==q['date'] and (not q.get('fingerprint') or q['fingerprint']==fingerprint(d)):
        d2=copy.deepcopy(d)
        try:
            if q['kind']=='payoff':
                quote=early_buyout_quote(d2,t)
                accepted=q.get('quote') or {}
                if quote and quote['total']==q['amt'] and all(quote.get(k)==accepted.get(k) for k in ('price','saved','pen','fine','principal')):
                    record_early_buyout(d2,quote,'СБП',qid,q['fees']);left=0;ok=True
            elif q.get('quote') and q['kind'] in ('now','selection'):
                quote=q['quote']
                if quote['total']==q['amt']:
                    apply_payment(d2,quote,'СБП',qid);left=0;ok=True
            elif q['kind']=='now':
                current=info(d2,t)
                items=current['ods'] if current['od'] else ([{**current['x'],'pen':0}] if current['x'] else [])
                if items and sum(y['amt']+y['pen'] for y in items)==q['amt'] and [y['k'] for y in items]==q.get('ks'):
                    for y in items:put_paid(d2,y['k'],t,y['amt'],y['pen'],'СБП',qid,fine=y.get('fine',0))
                    left=0;ok=True
            elif q['kind']=='debt':
                z=q_debt(d2,t)
                if z and z['amt']==q['amt']:left=apply_debt(d2,q['amt'],t,'СБП',qid);ok=True
            elif q['kind']=='bill':
                b=doc(q.get('bill') or '')
                if b and b.get('status')=='open' and b.get('amt')==q['amt']:
                    left=apply_money(d2,b['kind'],q['amt'],t,'СБП',qid);ok=True
                    ob=dict(b);b['status']='paid';b['paid']=dt.datetime.now(MSK).isoformat(timespec='seconds');put_srv(q['bill'],'bill',b,'bill-paid','Банк',ob)
        except Bad as e:ok=False;why=str(e)
        if ok:
            if q['kind']=='payoff':save_accepted_payoff(q['deal'],d,d2,t,'Банк')
            else:put_srv(q['deal'],'deal',d2,'pay-qr','',d)
    c=(doc((d or {}).get('client','')) or {}).get('name','')
    if ok and left<=0:say(f"Оплата по QR: {c}, {rub(q['amt'])}.")
    else:
        put_srv(nid(),'unk',{'ts':q['confirmedAt'],'date':t,'amt':left if ok else q['amt'],'qr':qid,'deal':q['deal'],'status':'open','why':'Переплата сверх суммы к оплате.' if ok else why},'unk','Банк')
        say(f"Платёж по QR не распознан: {c}, {rub(left if ok else q['amt'])}. Разберите в приложении.")
PL_LAST=[0]
def poll():
    with L:
        t=tq();now=dt.datetime.now(MSK);op={}
        for i,q in docs_of('qr'):
            if q.get('status')!='open':continue
            if qr_expiry(q)+dt.timedelta(days=1)<=now:
                old=dict(q);q['status']='review';put_srv(i,'qr',q,'qr-review','',old)
                put_srv(nid(),'unk',{'deal':q['deal'],'qr':i,'amt':q['amt'],'ts':now.isoformat(timespec='seconds'),
                                    'status':'open','unconfirmed':True,'why':'Истекло окно проверки QR. Найдите операцию в выписке банка.'},'unk','Автосверка')
            elif t:
                op[q['tid']]=i
        db.commit()
    if not op:return
    def check(ids):
        try:return qr_paid(t,ids)
        except urllib.error.HTTPError as error:
            if error.code in (400,404) and len(ids)>1:
                return {k:v for tid in ids for k,v in check([tid]).items()}
            if error.code not in (400,404):print('poll',error)
        except Exception as error:print('poll',error)
        return {}
    ids=list(op)
    for start in range(0,len(ids),20):
        paid=check(ids[start:start+20])
        with L,db:
            for tid in paid:
                i=op.get(tid);q=i and doc(i)
                if q:on_paid(i,q,paid[tid] if isinstance(paid,dict) else None)
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
        save_bank_settings(n)
        db.execute('delete from docs where id=?',('tch',))
        db.execute('insert into log values(?,?,?,?,?)',(dt.datetime.now(MSK).isoformat(),'tochka','tch',json.dumps({'on':bool(old)}),json.dumps({'on':bool(n)})));db.commit();return {}
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
                duplicate=possible_duplicate(z['deal'],t,z['amt'])
                if b.get('preview'):return {'duplicate':duplicate}
                if duplicate and b.get('confirmedDuplicate')!=duplicate['source']:raise Bad('По QR уже есть платёж на эту сумму. Проверьте операцию.')
                source=nid();d2=copy.deepcopy(d);left=apply_money(d2,z['kind'],z['amt'],t,m,source=source)
                actor=by or 'Владелец'
                put_srv(z['deal'],'deal',d2,'bill-paid',actor,d);z['status']='paid';z['paid']=dt.datetime.now(MSK).isoformat(timespec='seconds');z['method']=m;put_srv(i,'bill',z,'bill-paid',actor,old)
                if left>0:put_srv(nid(),'unk',{'ts':z['paid'],'date':t,'amt':left,'deal':z['deal'],'status':'open','method':m,
                                            'source':source,'why':'Переплата сверх суммы к оплате.'},'unk',actor)
                db.commit();return {}
            raise Bad('Неверный запрос.')
        i=str(b.get('deal',''));d=ID.fullmatch(i) and doc(i);k=b.get('kind')
        if not d or d.get('status')!='active':raise Bad('Выкуп не найден.')
        A=positive_amount(b.get('amt'))
        if any(z.get('deal')==i and z.get('status')=='open' for _,z in docs_of('bill')):raise Bad('У клиента уже есть выставленный платёж. Сначала отмените его или дождитесь оплаты.')
        if k=='period':
            pl=plan_period(d,A,t)
            if isinstance(pl,str):raise Bad(pl)
            if pl['left']>0:raise Bad(f"Сумма больше, чем нужно за период: не больше {rub(A-pl['left'])}.")
        elif k=='debt':
            g=dstat(d,t)
            if not g:raise Bad('Долга нет.')
            if d.get('lease') and minor(A)!=minor(g['total']):raise Bad('Остаток периода оплачивается одним платежом целиком.')
            if A<=g['pen']:raise Bad(f"Сумма должна быть больше неустойки {rub(g['pen'])}.")
            if A>g['total']:raise Bad(f"Сумма больше долга: не больше {rub(g['total'])}.")
        else:raise Bad('Неверный запрос.')
        bid=nid();put_srv(bid,'bill',{'deal':i,'kind':k,'amt':A,'status':'open','ts':dt.datetime.now(MSK).isoformat(timespec='seconds'),'by':by or 'owner'},'bill',by);db.commit();return {'id':bid}
    if p=='/api/unk':
        i=str(b.get('id',''));record=ID.fullmatch(i) and row(i)
        if not record or record[0]!='unk' or record[1].get('status')!='open':raise Bad('Платёж уже разобран.')
        z=record[1]
        old=dict(z)
        if b.get('do')=='done':
            note=str(b.get('note') or '').strip()[:200]
            if not note:raise Bad('Укажите результат сверки в комментарии.')
            z.update(status='done',note=note,resolvedAt=dt.datetime.now(MSK).isoformat());put_srv(i,'unk',z,'unk-done',by,old)
            db.commit();return {}
        if b.get('do') in ('preview','apply'):
            d=doc(z.get('deal',''))
            if not d or d.get('status')!='active' or b.get('kind') not in ('period','debt','original'):raise Bad('Выберите, куда засчитать платёж.')
            qr=doc(z.get('qr') or '') or {}
            date=received_date(z.get('date') or b.get('date'),t)
            if date<max(d['start'],qr.get('date',d['start'])):raise Bad('Дата получения денег раньше оформления выкупа или QR.')
            reference=str(b.get('reference') or '').strip()[:180]
            if z.get('unconfirmed') and (not reference or not b.get('verified')):raise Bad('Подтвердите поступление по выписке и введите номер банковской операции.')
            if reference and any(j!=z.get('qr') and q.get('status')=='paid' and reference.lower() in {str(q.get(k) or '').lower() for k in ('tid','trxId','refTransactionId')} for j,q in docs_of('qr')):
                raise Bad('Эта банковская операция уже учтена в другом QR.')
            if reference and z.get('unconfirmed') and any(str(link.get('reference') or '').strip().lower()==reference.lower() and link.get('date')==date for _,link in docs_of('statementlink')):
                raise Bad('Операция уже связана со строкой выписки. Проверьте запись о платеже в выкупе.')
            method=z.get('method','СБП');fees=qr.get('fees') or fee_rates(method);source=z.get('source') or z.get('qr') or i
            d2=copy.deepcopy(d)
            if b['kind']=='original' and qr.get('kind')=='payoff':
                quote=early_buyout_quote(d2,date)
                if not quote or quote['total']!=z['amt']:raise Bad('Сумма досрочного выкупа изменилась. Проверьте поступление и график.')
                record_early_buyout(d2,quote,method,z.get('qr'),fees);left=0
            elif b['kind']=='original':
                original=qr.get('quote') or {}
                quote=payment_quote(d2,qr.get('options') or {'count':len(qr.get('ks') or []) or 1},date,qr.get('settings'),
                                    legacy_discount=bool(original.get('bonus')))
                if quote['total']!=z['amt'] or [x['k'] for x in quote['items']]!=qr.get('ks'):
                    raise Bad('Сумма или периоды исходного QR изменились. Выберите взнос или погашение долга.')
                apply_payment(d2,quote,method,z.get('qr'),fees=fees);left=0
            else:left=apply_money(d2,b['kind'],z['amt'],date,method,z.get('qr'),fees=fees,source=source)
            parts=[payment for kind,key,payment in receipt_parts(d2) if receipt_part(d,kind,key)!=payment and payment.get('source')==source]
            debt=dstat(d2,date) or {}
            fine=sum(p.get('fine',0) for p in parts)
            plan={'version':d.get('_v',0),'date':date,'pen':money(sum(minor(p.get('pen') or 0) for p in parts)),
                  **({'fine':fine} if fine else {}),
                  'allocated':money(minor(z['amt'])-minor(left)),'surplus':left,'debt':debt.get('amt',0),'debtDue':debt.get('due')}
            if b['do']=='preview':return plan
            check_version(d,b)
            if b.get('expected')!=plan:raise Bad('Расчёт изменился. Проверьте оплату ещё раз.')
            if qr:
                qr_before=copy.deepcopy(qr);qr.update(paidDate=date,status='paid',fees=fees)
                if reference:qr.setdefault('refTransactionId',reference)
                put_srv(z['qr'],'qr',qr,'qr-reconciled',by,qr_before)
            if d2.get('payoff') and not d.get('payoff'):save_accepted_payoff(z['deal'],d,d2,date,by)
            else:put_srv(z['deal'],'deal',d2,'unk-apply',by,d)
            z.update(status='applied',date=date,resolvedAt=dt.datetime.now(MSK).isoformat())
            if reference:z['reference']=reference
            put_srv(i,'unk',z,'unk-apply',by,old)
            if left>0:put_srv(nid(),'unk',{'ts':z['resolvedAt'],'date':date,'amt':left,'deal':z['deal'],'qr':z.get('qr'),'source':source,
                                         'status':'open','method':method,'why':'Переплата сверх суммы к оплате.'},'unk',by)
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

def deal_payment_date(d,value,t):
    date=received_date(value,t)
    if date<d['start']:raise Bad('Дата получения денег раньше даты оформления выкупа.')
    return date

def handover_confirmed(checks):
    return isinstance(checks,dict) and set(checks)==set(HANDOVER_CHECKS) and all(checks[key] is True for key in HANDOVER_CHECKS)

def statement_allocation(d,options,date,operation):
    if not isinstance(operation,dict) or operation.get('date')!=date:
        raise Bad('Дата оплаты должна совпадать со строкой выписки.')
    statement_key(operation)
    received=money(operation['amount']);mode=options.get('mode')
    if d.get('lease'):
        if mode=='bank-debt':
            debt=dstat(d,date)
            if not debt or minor(received)!=minor(debt['total']):
                raise Bad('Сумма из выписки должна совпадать с доплатой за период.')
            source=nid()
            apply_debt(d,received,date,'СБП',source=source)
            return {'mode':mode,'date':date,'principal':debt['amt'],'pen':debt['pen'],'total':received,
                    'bonus':0,'rest':0,'received':received,'credit':0,'surplus':0},source
        quote=payment_quote(d,{} if mode=='bank-period' else options,date)
        if minor(received)!=minor(quote['total']):raise Bad(f"За выбранные периоды аренды нужно {rub(quote['total'])}. Проверьте количество периодов.")
        source=apply_payment(d,quote,'СБП')
        return {**quote,'received':received,'credit':0,'surplus':0},source
    source=nid();rest=0;credit=0;reductions=[]
    if mode in ('bank-period','bank-debt'):
        left=apply_money(d,'debt' if mode=='bank-debt' else 'period',received,date,'СБП',source=source,settle_debt=False)
        items=[]
        for kind,_,p in receipt_parts(d):
            if p.get('source')==source:
                p['group']=source;items.append(p)
        total=money(minor(received)-minor(left));pen=money(sum(minor(p.get('pen') or 0) for p in items))
        fine=sum(p.get('fine',0) for p in items)
        quote={'mode':mode,'date':date,'principal':money(minor(total)-minor(pen)),'pen':pen,
               **({'fine':fine} if fine else {}),'total':total,'bonus':0}
    else:
        quote=payment_quote(d,options,date)
        if minor(received)<minor(quote['total']):raise Bad('Поступление меньше выбранных взносов. Выберите меньше взносов или оплату ближайшего взноса фактической суммой.')
        source=apply_payment(d,quote,'СБП');left=money(minor(received)-minor(quote['total']))
    if left:
        materialize_schedule(d)
        credit,reductions=reduce_tail(d,left);rest=money(minor(left)-minor(credit))
        if credit:
            group=next((p.get('group') for _,_,p in receipt_parts(d) if p.get('source')==source),None)
            d.setdefault('early',[]).append({'date':date,'amt':credit,'paid':credit,'method':'СБП','source':source,
                                             'group':group,'fees':fee_rates('СБП'),'kind':'statement-credit','reductions':reductions})
    debt=d.get('debt') or {}
    return {**quote,'received':received,'credit':credit,'surplus':rest,'rest':debt.get('amt',0),'debtDue':debt.get('due')},source

def check_version(d,b):
    if b.get('version')!=d.get('_v',0):raise Bad('Данные изменились. Обновите экран и проверьте расчёт ещё раз.')

def used_schedule_request(key,d):
    return d.get('client_rescheduled') or any(r.get('deal')==key and r.get('status')=='approved' for _,r in docs_of('reschedule'))

def save_new_schedule(key,d,plan,t,by,request_id=None):
    old=copy.deepcopy(d)
    materialize_schedule(d)
    recover_reductions(key,d)
    d.setdefault('schedule_history',[]).append({'date':t,'request':request_id,'schedule':copy.deepcopy(d['schedule']),'pay':d['pay'],'n':d['n']})
    retained={(r['k'],r['due']) for r in plan['schedule']}
    future={(r['k'],r['due']) for r in d['schedule'] if str(r['k']) not in d.get('paid',{}) and r['due']>=t and payment_deadline(d,r)==r['due']}
    final=plan['after'][-1]
    for credit in (d.get('bonuses') or [])+(d.get('early') or []):
        for change in credit.get('reductions') or []:
            pair=(change['k'],change['due'])
            if pair in future and pair not in retained:
                change.setdefault('original',{'k':change['k'],'due':change['due']})
                change.update(k=final['k'],due=final['due'])
    d.setdefault('original_n',d['n']);d['schedule']=plan['schedule'];d['shift']=0
    d['pay']=plan['pay'];d['last']=plan['lastAmount'];d['n']=max(row_['k'] for row_ in plan['schedule'])
    if request_id:d['client_rescheduled']=True
    put_srv(key,'deal',d,'reschedule-approve' if request_id else 'reschedule-manual',by,old)
    gap = plan['gap']
    interval = f" Между двумя последними взносами {gap} дн." if gap is not None and gap < plan['step'] else ''
    tell(d['client'],f"График изменён. Первый взнос нового графика {rub(plan['firstAmount'])} до {dm(D(plan['first']))}. Последний платёж {rub(plan['lastAmount'])} до {dm(D(plan['last']))}.{interval}")

PREPARATION = ('inspection','repair','ready')

def update_preparation(bike_id,status,t,by,returned=False):
    record = row(bike_id)
    if not record or record[0] != 'bike':
        raise Bad('Велосипед не найден.')
    old = record[1]
    preparation = {'status':status,'updated':t}
    returned_on = t if returned else (old.get('preparation') or {}).get('returned')
    if returned_on:preparation['returned'] = returned_on
    data = {**old,'preparation':preparation}
    if returned:data['archived'] = False
    put_srv(bike_id,'bike',data,'prepare-bike',by,old)

def bike_available(bike_id,deal_id):
    record = row(bike_id)
    return bool(record and record[0]=='bike' and not record[1].get('archived') and not record[1].get('wo') and
                (record[1].get('preparation') or {}).get('status','ready')=='ready' and not any(
        i!=deal_id and d.get('bike')==bike_id and d.get('status')=='active' for i,d in docs_of('deal')
    ))

def validate_rental_record(d):
    lease=d['lease']
    if not isinstance(lease,dict) or not catalog_id(lease.get('model')):raise Bad('Проверьте условия аренды.')
    if 'modelName' in lease:catalog_name(lease['modelName'],'название модели')
    if lease.get('brandName'):catalog_name(lease['brandName'],'название бренда')
    rental_key(lease.get('slots'));plan=rental_plan(lease,lease.get('weeks'))
    batteries=lease.get('batteries')
    if not isinstance(batteries,list) or len(batteries)!=len(lease['slots']) or any(
        rental_battery(b,with_cost=False)!=b for b in batteries
    ):raise Bad('Проверьте комплектацию аренды.')
    if d.get('type')!='w' or type(d.get('n')) is not int or not lease['weeks']<=d['n']<=520 or any(
        d.get(field) for field in ('down','schedule','shift','early','bonuses','payoff_terms','tariff','extras')
    ):raise Bad('В записи аренды должен быть только недельный график.')
    if d.get('pay')!=plan['weekly'] or d.get('last')!=plan['weekly'] or d.get('total')!=plan['price']:
        raise Bad('Суммы в аренде отличаются от условий при выдаче.')
    if d.get('contract_date'):valid_date(d['contract_date'])
    if 'late_fee' in d:
        late=d['late_fee']
        if not isinstance(late,dict) or late_fee_record(late.get('amount'),late.get('day'))!=late:
            raise Bad('Проверьте условия штрафа.')
    halves={};groups={};reductions={}
    for key,record in d['paid'].items():
        if not isinstance(key,str) or not re.fullmatch(r'[1-9][0-9]{0,2}',key) or int(key)>d['n'] or not isinstance(record,dict):
            raise Bad('Проверьте номер оплаченной недели.')
        expected=money(minor(plan['weekly'])//2) if record.get('part') else plan['weekly']
        if record.get('amt')!=expected or record.get('method') not in PAYMENT_METHODS:
            raise Bad('Сумма оплаты недели должна совпадать с полной платой или её половиной.')
        if valid_date(record.get('date'))<d['start']:raise Bad('Платёж внесён до начала аренды.')
        if record.get('part'):halves[int(key)]=record['date']
        group=record.get('group')
        if isinstance(group,str) and group:groups.setdefault(group,[]).append(record)
        if 'buyout_reduction' in record:
            if not isinstance(group,str) or not group or group in reductions:
                raise Bad('В копии повреждено уменьшение цены выкупа.')
            reductions[group]=record
    for group,record in reductions.items():
        entries=groups[group];count=len(entries)
        principal=money(sum(minor(p['amt']) for p in entries))
        if (count<2 or any(p.get('part') or p.get('batch_count')!=count or
                          p['date']!=record['date'] or p['method']!=record['method'] for p in entries)
            or positive_amount(record['buyout_reduction'])!=rent_batch_reduction(principal,count)):
            raise Bad('В копии не сходится уменьшение цены выкупа.')
    def check_balance(debt):
        if (not isinstance(debt,dict) or type(debt.get('k')) is not int or debt['k'] not in halves
            or debt.get('amt')!=money(minor(plan['weekly'])//2)):
            raise Bad('В копии не сходится остаток по неделе аренды.')
        due=valid_date(debt.get('due'))
        if due<=halves[debt['k']]:
            period={'k':debt['k'],'due':add(d['start'],7*(debt['k']-1))}
            if due!=partial_payment_deadline(d,period):
                raise Bad('В копии не сходится срок доплаты за неделю аренды.')
    for payment in d.get('dpays') or []:
        prev=payment.get('pv')
        check_balance(prev)
        if (payment.get('k')!=prev['k'] or payment.get('amt')!=prev['amt']
            or valid_date(payment.get('date'))<halves[prev['k']] or payment.get('method') not in PAYMENT_METHODS):
            raise Bad('В копии не сходится доплата за неделю аренды.')
        del halves[prev['k']]
    if d.get('debt'):
        check_balance(d['debt'])
        del halves[d['debt']['k']]
    if halves:raise Bad('В копии отсутствует остаток по неделе аренды.')
    deposit=d.get('deposit')
    if plan['deposit']:
        if not isinstance(deposit,dict) or deposit.get('amt')!=plan['deposit'] or deposit.get('date')!=d['start'] or deposit.get('method') not in PAYMENT_METHODS:
            raise Bad('Проверьте запись об обеспечительном платеже.')
    elif deposit:raise Bad('В тарифе нет обеспечительного платежа.')
    release=d.get('deposit_refund')
    if release:
        if not deposit or not isinstance(release,dict) or valid_date(release.get('date'))<d['start']:
            raise Bad('Проверьте возврат обеспечения.')
        amount=whole(release.get('amt'),'сумму возврата');held=whole(release.get('held'),'сумму удержания')
        if min(amount,held)<0 or amount+held!=plan['deposit'] or (held and not release.get('reason')):
            raise Bad('Возврат и удержание должны совпадать с суммой обеспечения.')
    if d.get('refund'):
        returned=valid_date(d.get('closed'))
        if (d['status']!='seized' or returned<d['start'] or valid_date(d.get('refund_date'))<returned
            or d['refund']!=rental_return_refund(d,returned)):
            raise Bad('Проверьте возврат арендной платы в копии.')

def validate_new_rental(d,t):
    start=received_date(d.get('start'),t);lease=d.get('lease')
    if not isinstance(lease,dict) or not known_bike_model(lease.get('model')):raise Bad('Выберите модель велосипеда.')
    if type(lease.get('weeks')) is not int or lease['weeks'] not in RENTAL_WEEKS:raise Bad('Выберите срок тарифа, 20 или 26 недель.')
    record=row(d.get('bike'))
    bike=record[1] if record and record[0]=='bike' else {}
    if bike.get('model')!=lease['model']:raise Bad('Модель в тарифе должна совпадать с велосипедом.')
    terms,cost=rental_terms(lease['model'],lease.get('slots'),lease['weeks'])
    if terms!=lease:raise Bad('Тариф изменился. Откройте оформление заново.')
    paid=d.get('paid');first=paid.get('1') if isinstance(paid,dict) else None
    if not isinstance(first,dict) or len(paid)!=1 or first.get('date')!=start or first.get('pen',0)!=0 or first.get('part') or d.get('status')!='active':
        raise Bad('Подтвердите получение полной платы за первую неделю.')
    d.update(n=terms['weeks'],type='w',pay=terms['weekly'],last=terms['weekly'],total=terms['price'],
             cost=bike.get('cost') or cost,bike_name=bike.get('name',''),bike_vin=bike.get('vin',''))
    if any(d.get(field) for field in ('refund','deposit_refund','payoff','swaps','defer','closed','signed_at','debt','dpays')):
        raise Bad('При выдаче можно учесть первую неделю и обеспечительный платёж.')
    d['late_fee']=late_fee_record(LATE_FEE_AMOUNT,LATE_FEE_DAY)
    validate_rental_record(d)
    tax=cfgv('tax',7);future_rates={'tax':tax if 0<=tax<=100 else 0,**fee_rates('СБП')}
    issue_rates={**future_rates,**fee_rates(first['method'])}
    first_cents=minor(terms['weekly']);final_cents=minor(terms['price'])-first_cents*(terms['weeks']-1)
    def charge(cents,rate):return int((Decimal(cents)*Decimal(str(rate))/100).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
    for field,rate in future_rates.items():
        d[field]=money(charge(first_cents,issue_rates[field])+charge(first_cents,rate)*(terms['weeks']-2)+charge(final_cents,rate))

def validate_new_deal(d,t):
    if 'lease' in d:return validate_new_rental(d,t)
    start=received_date(d.get('start'),t)
    total=minor(positive_amount(d.get('total')))
    advance=whole(d.get('down'),'первоначальный взнос')
    if advance not in ADVANCES:raise Bad('Выберите первоначальный взнос из списка.')
    down=advance*100
    method=d.get('down_method')
    if method not in ('наличные','СБП','перевод'):raise Bad('Выберите способ оплаты при выдаче.')
    weeks=d.get('n')
    if type(weeks) is not int or weeks not in WEEKLY_TERMS or d.get('type')!='w':
        raise Bad(f'Доступные сроки выкупа: {WEEKLY_TERM_LIST} недель.')
    if d.get('shift') or d.get('schedule') is not None or d.get('early') or d.get('debt') or d.get('dpays') or d.get('bonuses'):
        raise Bad('При оформлении требуется исходный график.')
    record=row(d.get('bike'))
    bike=record[1] if record and record[0]=='bike' else {}
    model=bike.get('model')
    if model not in BIKE_MODELS:raise Bad('Укажите модель в карточке велосипеда.')
    if model in cfgv('catalogArchivedModels',[]):raise Bad('Эта модель удалена из каталога.')
    batteries=bike.get('batteries',1)
    if not valid_batteries(batteries):raise Bad('Укажите количество аккумуляторов в карточке велосипеда.')
    weekly=cfgv('tariffs',{}).get(tariff_key(model,batteries),{}).get(str(weeks))
    if weekly is None:raise Bad('Задайте недельный платёж для комплектации и срока в настройках.')
    discount=cfgv('advanceDiscounts',{}).get(str(advance),0)
    tariff={'model':model,'batteries':batteries,'weeks':weeks,'weekly':weekly,'advanceDiscount':discount}
    if d.get('tariff')!=tariff:raise Bad('Тариф или скидка изменились. Откройте оформление выкупа заново.')
    if d.get('extras'):raise Bad('Комплектация уже входит в тариф. Подарки укажите отдельно.')
    price=((minor(weekly)*weeks+50)//100-discount)*100
    if price<down:raise Bad('Первоначальный взнос больше цены выкупа со скидкой.')
    if total!=price:raise Bad('Цена выкупа должна совпадать с тарифом со скидкой.')
    balance=price-down
    regular=balance//(weeks*100)*100
    last=balance-regular*(weeks-1)
    if not balance:
        if d.get('paid') or d.get('pay')!=0 or d.get('last')!=0:raise Bad('Цена уже покрыта первоначальным взносом.')
    else:
        if not regular:raise Bad('Остаток слишком мал для выбранного срока.')
        if minor(positive_amount(d.get('pay')))!=regular or minor(positive_amount(d.get('last')))!=last:
            raise Bad('Суммы взносов должны совпадать с расчётом по тарифу.')
        paid=d.get('paid') or {};first=paid.get('1') if isinstance(paid,dict) else None
        if not isinstance(first,dict) or len(paid)!=1 or first.get('date')!=start or first.get('pen',0)!=0 or first.get('part'):
            raise Bad('Проверьте оплату первого взноса при оформлении.')
        if minor(positive_amount(first.get('amt')))!=regular or first.get('method')!=method:
            raise Bad('Сумма и способ оплаты первого взноса должны совпадать с графиком.')
        first['amt']=money(regular)
    d.update(tariff=tariff,cost=bike.get('cost',0),down=advance,total=money(price),pay=money(regular),last=money(last))
    if terms:=payoff_terms(d,cfgv('tariffs',{})):d['payoff_terms']=terms
    tax=cfgv('tax',7)
    future_rates={'tax':tax if 0<=tax<=100 else 0,**fee_rates('СБП')}
    issue_rates={**future_rates,**fee_rates(method)}
    def charge(cents,rate):return int((Decimal(cents)*Decimal(str(rate))/100).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
    for field,rate in future_rates.items():
        cents=charge(down+regular,issue_rates[field])+charge(regular,rate)*(weeks-2)+charge(last,rate)
        d[field]=money(cents)

def close_pending_schedule(key,t,by):
    for request_id,request in docs_of('reschedule'):
        if request.get('deal')==key and request.get('status')=='pending':
            previous=dict(request);request.update(status='closed',decided=t);put_srv(request_id,'reschedule',request,'reschedule-close',by,previous)

def save_accepted_payoff(key,old,d,date,by):
    put_srv(key,'deal',d,'pay-early-buyout',by,old)
    close_pending_schedule(key,date,by)
    for bid,bill in docs_of('bill'):
        if bill.get('deal')==key and bill.get('status')=='open':
            put_srv(bid,'bill',{**bill,'status':'void'},'bill-void',by,bill)

def early_buyout_action(b,ro,x,t,by):
    operation=b.get('do')
    key,d=action_deal(b,ro,x,allow_client=operation in ('quote','settle'))
    if operation in ('enable','enable-preview'):
        if d.get('lease'):raise Bad('В договоре уже предусмотрен выкуп.')
        if ro!='owner' or d.get('status')!='active' or d.get('payoff_terms') or info(d,t)['done']:
            raise Bad('Настройка досрочного выкупа недоступна.')
        terms=payoff_terms(d,cfgv('tariffs',{}))
        if not terms:raise Bad('В тарифах комплектации нет более выгодного короткого срока.')
        quote=early_buyout_quote({**d,'payoff_terms':terms},t)
        if not quote:raise Bad('На текущую дату снижение цены недоступно.')
        if operation=='enable':
            check_version(d,b)
            if b.get('terms')!=quote['terms']:raise Bad('Тарифы изменились. Проверьте расчёт ещё раз.')
            old=copy.deepcopy(d);d['payoff_terms']=terms
            put_srv(key,'deal',d,'enable-early-buyout',by,old)
        return quote
    if operation=='cancel':
        check_version(d,b)
        if d.get('status')!='active' or not d.get('payoff') or d['payoff'].get('qr') or d.get('deposit_refund'):
            raise Bad('Отмена доступна для ручной отметки до подписания документов.')
        old=copy.deepcopy(d);d.pop('payoff')
        put_srv(key,'deal',d,'cancel-early-buyout',by,old)
        return {}
    date=t if ro=='client' else deal_payment_date(d,b.get('date',t),t)
    quote=early_buyout_quote(d,date,client=ro=='client')
    if not quote and d.get('lease'):
        raise Bad('Выкуп доступен с начала пятой недели после полной оплаты первых четырёх недель аренды.')
    if not quote:raise Bad('На выбранную дату досрочный выкуп со скидкой недоступен.')
    duplicate=possible_duplicate(key,date,quote['total']) if ro!='client' and quote['total'] else None
    if operation=='quote':return {**quote,**({'duplicate':duplicate} if duplicate else {})}
    if operation!='settle':raise Bad('Неверное действие.')
    check_version(d,b)
    if b.get('total')!=quote['total'] or b.get('saved')!=quote['saved'] or b.get('date')!=date:
        raise Bad('Условия изменились. Проверьте новый расчёт.')
    if ro=='client' and quote['total']:raise Bad('Для подтверждения дождитесь оплаты по QR.')
    method=b.get('method') if quote['total'] else None
    if quote['total'] and method not in ('наличные','СБП','перевод'):raise Bad('Выберите способ оплаты.')
    if duplicate and b.get('confirmedDuplicate')!=duplicate['source']:raise Bad('По QR уже есть платёж на эту сумму. Проверьте операцию.')
    old=copy.deepcopy(d);record_early_buyout(d,quote,method)
    save_accepted_payoff(key,old,d,date,by)
    return quote

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
    retained=[]
    if bonus:
        retained=[change for change in bonus.get('reductions') or [] if str(change['k']) in d['paid']]
        released=[change for change in bonus.get('reductions') or [] if change not in retained]
        restore_reductions(d,{**bonus,'amt':money(minor(old_bonus)-sum(minor(x['amt']) for x in retained)),'reductions':released})
        d['bonuses'].remove(bonus)
    charges=installment_charges(d,row_,payment['date'])
    pen,fine=charges['pen'],charges['fine']
    cash=money(minor(payment['amt'])+minor(payment.get('pen',0)))
    if cash<=pen:raise Bad('Суммы первой оплаты недостаточно для начислений по целевому периоду на дату получения денег.')
    principal=min(row_['amt'],money(minor(cash)-minor(pen)))
    remainder=money(minor(row_['amt'])-minor(principal));excess=money(minor(cash)-minor(pen)-minor(principal))
    source_id=payment.get('source') or payment.get('qr') or group
    receipts=payment.get('fees') or fee_rates(payment['method'],estimated=True)
    put_paid(d,target,payment['date'],principal,pen,payment['method'],payment.get('qr'),remainder>0,source=source_id,
             fees=receipts,fine=fine)
    d['paid'][str(target)].update(group=group,due=row_['due'],batch_count=payment.get('batch_count',1),moved_from=int(source))
    if remainder:
        d['debt']={'k':target,'amt':remainder,'due':partial_payment_deadline(d,row_)}
    if excess:
        used,changes=reduce_tail(d,excess)
        if used!=excess:raise Bad('Переплата превышает остаток выкупа. Выберите другой период.')
        d.setdefault('early',[]).append({'date':payment['date'],'paid':excess,'amt':excess,'method':payment['method'],'group':group,'kind':'move-credit','source':source_id,'fees':receipts,'reductions':changes})
    for supplement in supplements:
        received=supplement['amt']+supplement.get('pen',0);cash+=received
        source_id=supplement.get('source') or supplement.get('qr') or nid()
        receipts=supplement.get('fees') or fee_rates(supplement['method'],estimated=True)
        remaining_cash=received
        if dstat(d,supplement['date']):
            remaining_cash=apply_debt(d,received,supplement['date'],supplement['method'],supplement.get('qr'),source=source_id,fees=receipts)
            applied=d['dpays'][-1];applied['group']=group
            principal+=applied['amt'];pen+=applied['pen']
        if remaining_cash:
            used,changes=reduce_tail(d,remaining_cash)
            if used!=remaining_cash:raise Bad('Переплата превышает остаток выкупа. Выберите другой период.')
            d.setdefault('early',[]).append({'date':supplement['date'],'paid':remaining_cash,'amt':remaining_cash,'method':supplement['method'],'group':group,'kind':'move-credit','source':source_id,'fees':receipts,'reductions':changes})
            excess+=remaining_cash
    remainder=(d.get('debt') or {}).get('amt',0)
    if other_debt:
        if remainder:raise Bad('Перенос создаст второй долг. Сначала закройте текущий долг или выберите период с подходящей суммой.')
        d['debt']=other_debt
    new_bonus=0
    if bonus:
        grouped=[p for p in d['paid'].values() if p.get('group')==group]
        base=sum(p['amt'] for p in grouped)+sum(p['paid'] for p in d.get('early',[]) if p.get('group')==group)+sum(p['amt'] for p in d.get('dpays',[]) if p.get('group')==group)
        retained_total=sum(minor(x['amt']) for x in retained)
        wanted=minor(penalty(base,1,bonus['rate']))-retained_total
        if wanted<0:raise Bad('Сначала отмените более позднюю оплату взноса, на который уже ушла часть скидки.')
        credited,changes=reduce_tail(d,money(wanted));new_bonus=money(retained_total+minor(credited))
        d.setdefault('bonuses',[]).append({**bonus,'amt':new_bonus,'base':base,'ks':[int(k) for k,p in d['paid'].items() if p.get('group')==group],'reductions':retained+changes})
    return {'source':int(source),'target':target,'cash':cash,'principal':principal,'pen':pen,**({'fine':fine} if fine else {}),
            'debt':remainder,'excess':excess,'oldBonus':old_bonus,'bonus':new_bonus}

def cancel_payment(d,key):
    key=str(whole(key,'номер периода'));payment=d.get('paid',{}).get(key)
    if not payment:raise Bad('Оплата уже отменена.')
    group=payment.get('group')
    keys=[k for k,p in d['paid'].items() if group and p.get('group')==group] if group else [key]
    if any(str(z['k']) in keys for z in d.get('dpays') or []):
        raise Bad('По этому платежу есть доплаты долга. Сначала отмените их.')
    if d.get('lease'):
        for k in keys:del d['paid'][k]
        if d.get('debt') and str(d['debt']['k']) in keys:d.pop('debt')
        return len(keys)
    materialize_schedule(d)
    for k in keys:del d['paid'][k]
    if d.get('debt') and str(d['debt']['k']) in keys:d.pop('debt')
    bonuses=[z for z in d.get('bonuses',[]) if group and z['group']==group]
    credits=[z for z in d.get('early',[]) if group and z.get('group')==group]
    for credit in bonuses+credits:restore_reductions(d,credit)
    d['bonuses']=[z for z in d.get('bonuses',[]) if z not in bonuses]
    d['early']=[z for z in d.get('early',[]) if z not in credits]
    return len(keys)

def cancel_debt_payment(d):
    payments=d.get('dpays') or []
    if not payments:raise Bad('Оплата долга уже отменена.')
    payment=payments[-1]
    if d.get('debt') and d['debt']['k']!=payment['k']:raise Bad('Сначала закройте или отмените текущий долг.')
    credits=[x for x in d.get('early') or [] if x.get('kind')=='statement-credit' and x.get('source')==payment.get('source')]
    if credits:
        materialize_schedule(d)
        for credit in credits:restore_reductions(d,credit)
        d['early']=[x for x in d['early'] if x not in credits]
    payments.pop();d['debt']=payment['pv']
    return payment.get('source') or payment.get('qr')

def clear_statement_surplus(key,sources,t,by):
    for i,z in docs_of('unk'):
        if z.get('deal')==key and z.get('source') in sources and z.get('status')=='open' and not z.get('qr'):
            old=dict(z);z.update(status='void',resolvedAt=t)
            put_srv(i,'unk',z,'undo-statement-surplus',by,old)

def rental_return_refund(d,date):
    cents=0;paid=rental_paid_amounts(d,date)
    for installment in sched(d):
        received=paid.get(installment['k'],0)
        if received:
            unused=7-max(0,min(7,diff(date,installment['due'])+1))
            full=minor(installment['amt'])
            cents+=max(0,received-(full-(full*unused+3)//7))
    return money(cents)

def rental_action(p,b,ro,x,t,by):
    key,d=action_deal(b,ro,x,permission='deals')
    if not d.get('lease'):raise Bad('Действие доступно для аренды с правом выкупа.')
    if p=='/api/rental-act':
        if not d.get('payoff'):raise Bad('Сначала подтвердите полный расчёт за велосипед.')
        return download_file('akt-vykupa.html','text/html; charset=utf-8',rental_act(d).encode(),key)
    check_version(d,b);old=copy.deepcopy(d)
    if p=='/api/rental-renew':
        if d['status']!='active' or d.get('payoff'):raise Bad('Аренда завершена.')
        weeks=whole(b.get('weeks'),'количество недель')
        if weeks not in range(1,27) or d['n']+weeks>520:raise Bad('Укажите от 1 до 26 недель в пределах графика.')
        d['n']+=weeks
        put_srv(key,'deal',d,'rental-renew',by,old)
        return {'until':add(d['start'],d['n']*7-1)}
    if p=='/api/deposit-return':
        deposit=d.get('deposit')
        if not deposit or d.get('deposit_refund') or (d['status']=='active' and not d.get('payoff')):
            raise Bad('Запись доступна после выкупа, возврата или закрытия аренды.')
        date=received_date(b.get('date',t),t)
        if date<(d.get('payoff') or {}).get('date',d.get('closed') or d['start']):
            raise Bad('Укажите дату фактического возврата обеспечения после расчёта по договору.')
        held=whole(b.get('held',0),'сумму удержания');reason=str(b.get('reason') or '').strip()[:500]
        if not 0<=held<=deposit['amt'] or (held and not reason):raise Bad('Проверьте сумму и основание удержания.')
        d['deposit_refund']={'date':date,'held':held,'amt':deposit['amt']-held,'reason':reason}
        put_srv(key,'deal',d,'deposit-return',by,old)
        return d['deposit_refund']
    raise Bad('Неверный запрос.')

def rental_act(d):
    lease=d['lease'];payment=d['payoff'];client=doc(d['client']) or {}
    name=escape(str(client.get('name') or '____________________________'))
    def formatted(date):return dm(D(date))
    model=' '.join(filter(None,(lease.get('brandName'),lease.get('modelName') or LEGACY_MODEL_NAMES.get(lease['model']))))
    bike_name=str(d.get('bike_name') or model or lease['model'])
    bike=escape(f"{bike_name} ({model})" if model and model.casefold() not in bike_name.casefold() else bike_name)
    vin=escape(str(d.get('bike_vin') or '________________'))
    contract=escape(str(d.get('contract') or '________'))
    batteries='; '.join(f"АКБ {i} — {b['voltage']:g} В, {b['capacity']:g} А·ч" for i,b in enumerate(lease['batteries'],1))
    if payment['amt']:
        balance=f"Остаток выкупной цены в размере <b>{rub(payment['amt'])}</b> оплачен {formatted(payment['date'])}. Способ оплаты — {escape(payment['method'])}."
    else:balance=f"Полный расчёт за велосипед подтверждён {formatted(payment['date'])}."
    fine=payment.get('fine',0)
    daily=payment['pen']-fine
    penalty_text=(f" Отдельно оплачена неустойка {rub(daily)}." if daily else '')+(f" Оплачен штраф {rub(fine)}." if fine else '')
    reduction=payment.get('buyout_reduction',0)
    reduction_text=(f"<p>Исходная цена — {rub(lease['price'])}. За оплату нескольких периодов "
                    f"одним платежом выкупная цена уменьшена на {rub(reduction)}.</p>") if reduction else ''
    deposit_text=''
    if deposit:=d.get('deposit'):
        deposit_text=f"<p>Обеспечительный платёж по договору — {rub(deposit['amt'])}.</p>"
        if release:=d.get('deposit_refund'):
            if release['amt']:deposit_text+=f"<p>Возвращено арендатору {rub(release['amt'])} {formatted(release['date'])}.</p>"
            if release['held']:deposit_text+=f"<p>Удержано {rub(release['held'])}. Основание — {escape(release['reason'])}.</p>"
    return f'''<!doctype html><html lang="ru"><meta charset="utf-8"><title>Акт выкупа электровелосипеда</title>
<style>body{{max-width:720px;margin:48px auto;padding:0 24px;color:#171717;font:16px/1.55 Arial,sans-serif}}h1{{font-size:25px}}footer{{margin-top:46px}}@media print{{body{{margin:12mm auto}}}}</style>
<h1>Акт выкупа электровелосипеда</h1><p>К договору аренды с правом выкупа № {contract} от {formatted(d.get('contract_date') or d['start'])}.</p>
<p>Дата подписания _________ &nbsp;&nbsp; Место подписания ____________________</p>
<p>Арендодатель ______________________________ и арендатор {name} подтверждают полный расчёт за электровелосипед.</p>
<p>Велосипед {bike}. Номер рамы (VIN) {vin}. Комплектация — {batteries}.</p>
{reduction_text}
<p>Выкупная цена электровелосипеда составляет <b>{rub(payment['price'])}</b>.
В счёт выкупной цены засчитано <b>{rub(payment['credited'])}</b> арендной платы, ранее внесённой по договору.</p>
<p>{balance} Арендодатель подтверждает, что выкупная цена оплачена полностью.{penalty_text}</p>
<p>Право собственности на электровелосипед переходит к арендатору в соответствии с договором с «____» ____________ 20____ г.</p>
{deposit_text}
<footer><p>Арендодатель ______________________________ / подпись ____________</p>
<p>Арендатор _________________________________ / подпись ____________</p></footer></html>'''

def workflow_action(p,b,ro,x):
    """Authorised business actions run in one database transaction under L."""
    t=tod();by=str(x[1].get('name',''))[:40] if ro=='admin' else ''
    if ro=='client':by=client_log_actor(x)
    if p=='/api/catalog-delete':
        if ro!='owner':raise Bad('Удаление из каталога доступно владельцу.')
        return remove_catalog_entry(b)
    if p in ('/api/rental-act','/api/rental-renew','/api/deposit-return'):return rental_action(p,b,ro,x,t,by)
    if p=='/api/early-buyout':return early_buyout_action(b,ro,x,t,by)
    if p=='/api/calendar':
        key,d=action_deal(b,ro,x,permission='deals',allow_client=True)
        if d.get('status')!='active':raise Bad('Выкуп закрыт.')
        return download_file('platezhi.ics','text/calendar; charset=utf-8',calendar_data(key,d,t),key)
    if p=='/api/tariff-image':
        if not (ro=='owner' or (ro=='admin' and hasfin(x[1].get('perms',[])))):raise Bad('Нет доступа.')
        model,weeks,batteries=b.get('model'),b.get('weeks'),b.get('batteries',1)
        allowed_weeks=RENTAL_WEEKS if 'slots' in b else WEEKLY_TERMS
        if (not known_bike_model(model) or model in cfgv('catalogArchivedModels',[])
            or (weeks is not None and (type(weeks) is not int or weeks not in allowed_weeks))):
            raise Bad('Проверьте комплектацию и срок выкупа.')
        if 'slots' in b:
            slots=rental_key(b['slots']).split(',')
            available=rental_models(doc('cfg') or {}).get(model,{}).get('batteries',{})
            if any(slot not in available for slot in slots):raise Bad('Выберите сохранённые варианты АКБ.')
            key=f'{model}-{len(slots)}-akb'
        else:
            if not valid_batteries(batteries):raise Bad('Проверьте комплектацию и срок выкупа.')
            key=tariff_key(model,batteries)
        image=decode_upload(b.get('png'),1200000)
        if not image.startswith(b'\x89PNG\r\n\x1a\n'):raise Bad('Выберите изображение PNG.')
        filename=f'grafik-{key}-{weeks}-ned.png' if weeks else f'tarify-{key}.png'
        return download_file(filename,'image/png',image)
    if p=='/api/payment-report':return payment_report_action(b,ro,x,t,by)
    if p=='/api/statement':
        if not (ro=='owner' or (ro=='admin' and 'pay' in x[1].get('perms',[]))):raise Bad('Нет доступа.')
        if b.get('do')=='upload':
            operations,unfiltered,skipped=read_statement(b.get('file'))
            return {'rows':statement_review(operations),'unfiltered':unfiltered,'skipped':skipped}
        if b.get('do')=='link' and isinstance(b.get('operation'),dict):
            return link_statement(b['operation'],str(b.get('deal') or ''),str(b.get('source') or ''),by)
        raise Bad('Загрузите выписку.')
    if p=='/api/pay-debt':
        key,d=action_deal(b,ro,x);date=deal_payment_date(d,b.get('date',t),t);amount=positive_amount(b.get('amount'))
        debt=dstat(d,date);method=b.get('method')
        if not debt or d.get('status')!='active':raise Bad('Долга нет.')
        if d.get('lease') and minor(amount)!=minor(debt['total']):
            raise Bad('Остаток периода оплачивается одним платежом целиком.')
        if not debt['pen']<amount<=debt['total']:raise Bad('Сумма оплаты долга изменилась. Проверьте расчёт.')
        duplicate=possible_duplicate(key,date,amount)
        if b.get('preview'):return {'version':d.get('_v',0),'duplicate':duplicate,'pen':debt['pen'],'total':amount}
        check_version(d,b)
        if method not in ('наличные','СБП','перевод'):raise Bad('Выберите способ оплаты.')
        if duplicate and b.get('confirmedDuplicate')!=duplicate['source']:raise Bad('По QR уже есть платёж на эту сумму. Проверьте операцию.')
        old=copy.deepcopy(d);apply_debt(d,amount,date,method);put_srv(key,'deal',d,'pay-debt',by,old)
        return {'remaining':(d.get('debt') or {}).get('amt',0)}
    if p=='/api/cancel-debt-pay':
        key,d=action_deal(b,ro,x);check_version(d,b)
        if d.get('status')!='active' or d.get('payoff'):raise Bad('Выкуп закрыт.')
        old=copy.deepcopy(d);source=cancel_debt_payment(d)
        if source:clear_statement_surplus(key,{source},t,by)
        put_srv(key,'deal',d,'cancel-debt-pay',by,old)
        return {}
    if p=='/api/bike-preparation':
        if not (ro=='owner' or (ro=='admin' and 'bikes' in x[1].get('perms',[]))):raise Bad('Нет доступа.')
        i=str(b.get('bike') or '');record=ID.fullmatch(i) and row(i)
        if not record or record[0]!='bike' or record[1].get('archived'):raise Bad('Велосипед недоступен.')
        check_version(record[1],b)
        if any(d.get('bike')==i and d.get('status')=='active' for _,d in docs_of('deal')):raise Bad('Велосипед сейчас под выкупом.')
        status=b.get('status')
        if status not in PREPARATION:raise Bad('Выберите статус подготовки.')
        update_preparation(i,status,t,by)
        return {}
    if p=='/api/bike-writeoff':
        if not (ro=='owner' or (ro=='admin' and 'bikes' in x[1].get('perms',[]))):raise Bad('Нет доступа.')
        bike_id=str(b.get('bike') or '');record=ID.fullmatch(bike_id) and row(bike_id)
        if not record or record[0]!='bike' or record[1].get('wo') or record[1].get('erased'):raise Bad('Велосипед недоступен для списания.')
        bike=record[1];check_version(bike,b)
        active=[(i,d) for i,d in docs_of('deal') if d.get('bike')==bike_id and d.get('status')=='active']
        if len(active)>1 or (active[0][0] if active else None)!=b.get('deal'):
            raise Bad('Выкуп велосипеда изменился. Обновите экран.')
        date=received_date(b.get('date'),t);loss=positive_amount(b.get('loss')) if b.get('loss')!=0 else 0
        reason=str(b.get('reason') or '').strip()[:80]
        if not reason:raise Bad('Укажите причину списания.')
        if active:
            key,d=active[0];check_version(d,{'version':b.get('dealVersion')})
            if d.get('lease') and d.get('payoff'):raise Bad('Выкуп уже оплачен. Завершите оформление документов.')
            if date<d['start'] or any(p.get('date','')>date for _,_,p in receipt_parts(d)):
                raise Bad('Дата списания должна быть после оформления и всех полученных платежей.')
            old=copy.deepcopy(d);d.update(status='lost',closed=date)
            put_srv(key,'deal',d,'writeoff-deal',by,old)
            close_pending_schedule(key,t,by)
            for bill_id,bill in docs_of('bill'):
                if bill.get('deal')==key and bill.get('status')=='open':
                    put_srv(bill_id,'bill',{**bill,'status':'void'},'bill-void',by,bill)
        old=copy.deepcopy(bike)
        bike.update(archived=True,wo={'date':date,'loss':loss,'reason':reason,'note':str(b.get('note') or '')[:200]})
        put_srv(bike_id,'bike',bike,'writeoff-bike',by,old)
        return {}
    if p=='/api/deal-note':
        key,d=action_deal(b,ro,x,permission='deals');check_version(d,b)
        old=copy.deepcopy(d);note=str(b.get('note') or '').strip()
        if len(note)>1000:raise Bad('В заметке должно быть до 1000 символов.')
        if note:d['private_note']={'text':note,'date':t,'by':by or 'Владелец'}
        else:d.pop('private_note',None)
        put_srv(key,'deal',d,'deal-note',by,old)
        return {}
    if p=='/api/return-deal':
        key,d=action_deal(b,ro,x,permission='deals')
        if d.get('status')!='active':raise Bad('Выкуп закрыт.')
        date=t
        if d.get('lease'):
            if d.get('payoff'):raise Bad('Велосипед выкуплен. Сначала сверьте расчёт.')
            date=deal_payment_date(d,b.get('date',t),t)
            if any(p['date']>date for _,_,p in receipt_parts(d)):raise Bad('Дата возврата раньше учтённой оплаты аренды.')
            amount=rental_return_refund(d,date)
            if b.get('preview'):return {'refund':amount,'version':d.get('_v',0)}
            if b.get('refund')!=amount or (amount and b.get('paidRefund') is not True):
                raise Bad('Сверьте сумму и подтвердите, что деньги за оставшиеся дни возвращены.')
        else:amount=whole(b.get('refund',0),'сумму возврата')
        check_version(d,b)
        if amount<0:raise Bad('Укажите сумму возврата или 0.')
        old=copy.deepcopy(d);d.update(status='seized',closed=date,refund=amount)
        if d.get('lease') and amount:d['refund_date']=t
        put_srv(key,'deal',d,'return-deal',by,old)
        update_preparation(d['bike'],'inspection',date,by,returned=True)
        close_pending_schedule(key,t,by)
        for bid,bill in docs_of('bill'):
            if bill.get('deal')==key and bill.get('status')=='open':
                put_srv(bid,'bill',{**bill,'status':'void'},'bill-void',by,bill)
        return {}
    if p in ('/api/payquote','/api/pay','/api/move-payment','/api/cancel-payment'):
        key,d=action_deal(b,ro,x,allow_client=p=='/api/payquote')
        if d.get('status')!='active':raise Bad('Выкуп закрыт.')
        if d.get('payoff'):raise Bad('Выкуп полностью выплачен досрочно.')
        if p=='/api/payquote':
            date=deal_payment_date(d,b.get('date',t),t) if ro in ('owner','admin') else t
            options=b.get('options') or {};statement=b.get('statement')
            if not isinstance(options,dict):raise Bad('Выберите способ оплаты.')
            if statement is not None:
                if ro=='client':raise Bad('Нет доступа.')
                quote,_=statement_allocation(copy.deepcopy(d),options,date,statement)
            else:quote=payment_quote(d,options,date,client=ro=='client')
            if ro in ('owner','admin'):
                duplicate=possible_duplicate(key,date,quote.get('received',quote['total']))
                if duplicate:quote['duplicate']=duplicate
            return {**quote,'version':d.get('_v',0)}
        check_version(d,b);old=copy.deepcopy(d)
        if p=='/api/pay':
            date=deal_payment_date(d,b.get('date',t),t);method=b.get('method')
            if method not in ('наличные','СБП','перевод'):raise Bad('Выберите способ оплаты.')
            options=b.get('options') or {};statement=b.get('statement')
            if not isinstance(options,dict):raise Bad('Выберите способ оплаты.')
            if statement is not None:
                if method!='СБП' or not isinstance(statement,dict):raise Bad('Проверьте строку выписки.')
                if statement_review([statement])[0]['state'] in ('exact','linked'):raise Bad('Этот перевод уже учтён. Обновите сверку.')
                quote,source=statement_allocation(d,options,date,statement)
            else:quote=payment_quote(d,options,date)
            if 'expected_quote' in b:
                expected=b['expected_quote']
                if not isinstance(expected,dict) or {k:v for k,v in expected.items() if k not in ('version','duplicate')}!=quote:
                    raise Bad('Условия оплаты изменились. Проверьте новый расчёт.')
            if b.get('expected_total',quote['total'])!=quote['total'] or b.get('expected_bonus',quote['bonus'])!=quote['bonus']:
                raise Bad('Условия оплаты изменились. Проверьте новый расчёт.')
            duplicate=possible_duplicate(key,date,quote.get('received',quote['total']))
            if duplicate and b.get('confirmedDuplicate')!=duplicate['source']:raise Bad('По QR уже есть платёж на эту сумму. Проверьте операцию.')
            if statement is None:apply_payment(d,quote,method)
            put_srv(key,'deal',d,'pay-periods',by,old)
            if statement is not None:
                if quote['surplus']:
                    put_srv(nid(),'unk',{'ts':dt.datetime.now(MSK).isoformat(),'date':date,'amt':quote['surplus'],'deal':key,
                                        'source':source,'status':'open','why':'Переплата из выписки сверх остатка выкупа.'},'unk',by or 'Владелец')
                link_statement(statement,key,source,by)
            return quote
        recover_reductions(key,d)
        if p=='/api/move-payment':
            if d.get('lease'):raise Bad('Отмените ошибочную отметку и внесите оплату нужной недели по порядку.')
            preview=move_payment(d,b.get('source'),b.get('target'),t)
            if b.get('preview'):return preview
            put_srv(key,'deal',d,'move-payment',by,old)
            return preview
        count=cancel_payment(d,b.get('period'))
        removed={p['source'] for k,p in old['paid'].items() if k not in d['paid'] and p.get('source')}
        if removed:clear_statement_surplus(key,removed,t,by)
        put_srv(key,'deal',d,'cancel-payment',by,old)
        return {'count':count}
    if p=='/api/reschedule-request':
        key,d=action_deal(b,ro,x,permission='deals',allow_client=True)
        if ro!='client' or d.get('status')!='active' or d.get('lease'):raise Bad('Заявка недоступна.')
        if used_schedule_request(key,d):raise Bad('Перенос по заявке уже использован для этого выкупа.')
        anchor,_,_=client_schedule_bounds(d,t)
        plan=replan(d,b.get('first'),b.get('pay'),t,anchor)
        if b.get('preview'):return plan
        check_version(d,b)
        if b.get('asOf',t)!=t:raise Bad('Наступил новый день. Откройте заявку заново и проверьте расчёт.')
        if any(z.get('deal')==key and z.get('status')=='pending' for _,z in docs_of('reschedule')):raise Bad('Заявка уже ожидает решения.')
        request_id=nid()
        request={'deal':key,'client':x,'anchor':anchor,'reason':str(b.get('reason') or '')[:1000],
                 'status':'pending','created':dt.datetime.now(MSK).isoformat(),**reschedule_details(plan)}
        put_srv(request_id,'reschedule',request,'reschedule-request',by)
        say(f"Заявка на изменение графика: {(doc(x) or {}).get('name','')}, {rub(plan['pay'])}, следующий платёж {dm(D(plan['first']))}.")
        return {'id':request_id}
    if p=='/api/reschedule-manual':
        key,d=action_deal(b,ro,x,permission='deals')
        if d.get('status')!='active':raise Bad('Выкуп закрыт.')
        if d.get('lease'):raise Bad('Периоды аренды идут по календарю договора.')
        plan=replan(d,b.get('first'),b.get('pay'),t)
        if b.get('preview'):return {**plan,'version':d.get('_v',0)}
        check_version(d,b)
        if b.get('asOf',t)!=t:raise Bad('Наступил новый день. Рассчитайте график ещё раз.')
        save_new_schedule(key,d,plan,t,by)
        return plan
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
        if used_schedule_request(key,d):raise Bad('Перенос по заявке уже использован для этого выкупа.')
        anchor,_,_=client_schedule_bounds(d,t,request.get('anchor'))
        plan=replan(d,b.get('first',request['first']),b.get('pay',request['pay']),t,anchor)
        if action=='preview':return {**plan,'version':d.get('_v',0)}
        if action!='approve':raise Bad('Выберите действие.')
        check_version(d,b)
        if b.get('asOf',t)!=t:raise Bad('Наступил новый день. Рассчитайте график ещё раз.')
        save_new_schedule(key,d,plan,t,by,request_id)
        request.update(status='approved',decided=t,**reschedule_details(plan))
        put_srv(request_id,'reschedule',request,'reschedule-approve',by,old_request)
        return plan
    if p=='/api/close-deal':
        key,d=action_deal(b,ro,x,permission='deals');check_version(d,b)
        if d.get('status')!='active' or not info(d,t)['done']:raise Bad('Сначала закройте все платежи и долги.')
        if not handover_confirmed(b.get('handover')):raise Bad('Подтвердите все четыре пункта передачи велосипеда.')
        old=copy.deepcopy(d)
        d.update(status='archived',closed=t,signed_at=dt.datetime.now(MSK).isoformat(),handover=b['handover'])
        put_srv(key,'deal',d,'close-deal',by,old)
        for field,kind in (('bike','bike'),('client','client')):
            item=doc(d[field])
            if item and not any(z.get(field)==d[field] and z.get('status')=='active' for _,z in docs_of('deal')):
                previous=copy.deepcopy(item);item['archived']=True;put_srv(d[field],kind,item,'archive-'+kind,by,previous)
        close_pending_schedule(key,t,by)
        return {}
    raise Bad('Неверный запрос.')

def delete_archived_card(identifier,kind,card,request,ts):
    """Erase the archived profile and keep the references used by financial history. Called under L."""
    if card.get('erased'):return {'deleted':False}
    if not card.get('archived'):raise Bad('Удаление доступно из архива.')
    related=[(key,deal) for key,deal in docs_of('deal') if deal.get(kind)==identifier or (
        kind=='bike' and any(identifier in (item.get('from'),item.get('to')) for item in deal.get('swaps') or []))]
    if any(deal.get('status')=='active' for _,deal in related):
        raise Bad('Карточка связана с действующим выкупом. Сначала закройте выкуп.')
    deals={key for key,_ in related}
    if request.get('version')!=card.get('_v',0) or request.get('deals')!=sorted(deals):return None

    history={'archived':True,'erased':True,'_v':card.get('_v',0)+1}
    if kind=='client':
        history['name']='Удалённый клиент'
    else:
        history.update(name='Удалённый велосипед',created=card.get('created'),cost=card.get('cost') or 0,
                       exp=[{'date':item['date'],'amt':item['amt']} for item in card.get('exp') or []])
        if card.get('wo'):
            history['wo']={'date':card['wo']['date'],'loss':card['wo'].get('loss',0),'reason':'Списание'}

    audit_ids={identifier}
    with db:
        if kind=='client':
            db.execute('delete from notice_queue where chat in (select tg from bind where client=?)',(identifier,))
            db.execute('delete from inv where client=?',(identifier,))
            db.execute('delete from bind where client=?',(identifier,))
            private=[(key,) for record_kind in ('paymentreport','reschedule') for key,data in docs_of(record_kind)
                     if data.get('client')==identifier or data.get('deal') in deals]
            db.executemany('delete from docs where id=?',private)
            audit_ids.update(key for (key,) in private)
            audit_ids.update(deals)
            for key,deal in related:
                if 'private_note' in deal:
                    deal.pop('private_note');deal['_v']=deal.get('_v',0)+1;save(key,'deal',deal)
        for key,qr in docs_of('qr'):
            if qr.get('deal') in deals:
                qr.pop('payload',None);qr.pop('img',None);qr['access_revoked']=True
                save(key,'qr',qr);audit_ids.add(key)
        reminders=[(f'%:rem:{key}:%',) for key in deals]
        db.executemany('delete from notice_queue where k like ?',reminders)
        db.executemany('delete from ntf where k like ?',reminders)
        save(identifier,kind,history)
        db.executemany('delete from log where id=?',[(key,) for key in audit_ids])
        db.execute('insert into log values(?,?,?,?,?)',(ts,'delete-archived-'+kind,'',None,json.dumps({'name':'Архив','retained_deals':len(deals)})))
    for key,entry in list(FILE_DL.items()):
        if entry[4] in deals:FILE_DL.pop(key)
    for key,entry in list(IMG.items()):
        if entry[2] in deals or (kind=='client' and entry[3]==identifier):IMG.pop(key)
    return {'deleted':True}

def attachment_headers(name):
    return {'Content-Disposition':f'attachment; filename="{name}"','Cache-Control':'no-store',
            'Access-Control-Allow-Origin':'https://web.telegram.org','Access-Control-Expose-Headers':'Content-Disposition'}

class H(BaseHTTPRequestHandler):
    def send(s,c,b,t='application/json',x=None):
        s.send_response(c);s.send_header('Content-Type',t);s.send_header('Content-Length',str(len(b)))
        for k,v in {**HD,**(x or {})}.items():s.send_header(k,v)
        s.end_headers()
        if s.command!='HEAD':s.wfile.write(b)
    def ip(s):return s.headers.get('X-Forwarded-For','').split(',')[0].strip() or s.client_address[0]
    def user(s):
        ip=s.ip();t=time.time()
        FAIL[ip]=[x for x in FAIL.get(ip,[]) if x>t-600]
        if len(FAIL[ip])>=10:return None
        u=who(s.headers.get('X-Init',''))
        if u is None:FAIL[ip].append(t)
        return u
    def do_HEAD(s):
        if s.path.split('?',1)[0] in ('/privacy','/terms') or s.path.startswith(('/img/','/files/','/dl/')):return s.do_GET()
        return s.send(404,b'')
    def do_GET(s):
        s.path,_,query=s.path.split('#',1)[0].partition('?')
        if s.path=='/privacy':
            return s.send(200,privacy_page().encode('utf-8'),'text/html; charset=utf-8',{'Cache-Control':'no-cache'})
        if s.path=='/terms':
            with L:settings=doc('cfg') or {}
            return s.send(200,bank_terms_page(settings).encode('utf-8'),'text/html; charset=utf-8',{'Cache-Control':'no-cache'})
        if s.path in('/api/all','/api/me','/api/log'):
            u=s.user()
            if u is None:return s.send(403,b'{}')
            with L:
                ro,x=role(u)
                if s.path=='/api/all':
                    if ro not in('owner','admin'):return s.send(403,b'{}')
                    owner=ro=='owner';perms=set() if owner else set(x[1].get('perms',[]))
                    f=owner or hasfin(perms);pay=owner or 'pay' in perms
                    r=[
                        {'kind':k,'id':i,'data':payment_report_summary(json.loads(d)) if k=='paymentreport' else vw(k,json.loads(d),f,owner)}
                        for i,k,d in db.execute('select id,kind,data from docs')
                        if k not in ('qr','tch','statementlink')
                        and (pay or k not in ('unk','bill','paymentreport'))
                        and (owner or (k!='admin' and (k!='reschedule' or 'deals' in perms) and (k!='expense' or 'reports' in perms)))
                    ]
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
                if not q or q.get('access_revoked'):return s.send(404,b'{}')
                dd=doc(q['deal']) or {}
                if not(ro in('owner','admin') or (ro=='client' and dd.get('client')==x)):return s.send(403,b'{}')
                if q.get('status')=='open':poll_soon()
                details={k:q.get(k) for k in('amt','kind','pen','payload','img','status','date','expires')}
                quote=q.get('quote') or {}
                fine=quote.get('fine')
                if fine:details['fine']=fine
                if dd.get('lease') and q['kind']=='selection' and quote.get('mode')=='periods' and quote.get('count',0)>=2:
                    details['buyout_reduction']=rent_batch_reduction(quote['principal'],quote['count'])
                return s.send(200,json.dumps(details).encode())
        if s.path.startswith('/img/'):
            t=time.time()
            with L:
                for a in [a for a,entry in IMG.items() if entry[0]<t]:IMG.pop(a,None)
                z=IMG.get(s.path[5:])
            if not z:return s.send(404,b'')
            headers=attachment_headers('qr-oplata.png')
            if query=='view=1':headers['Content-Disposition']='inline; filename="qr-oplata.png"'
            return s.send(200,z[1],'image/png',headers)
        if s.path.startswith('/files/'):
            with L:entry=FILE_DL.get(s.path[7:])
            if not entry or entry[0]<time.time():return s.send(404,b'')
            _,name,mime,data,_=entry
            return s.send(200,data,mime,attachment_headers(name))
        if s.path.startswith('/dl/'):
            ip=('dl',s.ip());t=time.time();FAIL[ip]=[x for x in FAIL.get(ip,[]) if x>t-600]
            for a in [a for a,e in DL.items() if e<t]:DL.pop(a,None)
            if len(FAIL[ip])>=10 or DL.get(s.path[4:],0)<t:FAIL[ip].append(t);return s.send(404,b'')
            d=dump()
            if len(d)>MAX_BACKUP_BYTES:return s.send(413,'Копия больше 128 МиБ. Используйте снимок SQLite на сервере.'.encode(),'text/plain; charset=utf-8')
            s.send(200,d,'application/octet-stream',attachment_headers(f'velo-{dt.datetime.now(MSK):%Y-%m-%d-%H%M}.json'))
            if s.command!='HEAD':bset()
            return
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
        if n>(MAX_BACKUP_BYTES if s.path=='/api/restore' and u==OWNER else 3000000):
            return s.send(413,json.dumps({'err':'Размер файла превышает допустимый предел.'}).encode())
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
            try:png=base64.b64decode(str(b.get('png','')).split(',')[-1],validate=True)
            except Exception:return s.send(400,b'{}')
            if not png.startswith(b'\x89PNG') or len(png)>400000:return s.send(400,b'{}')
            with L:
                qr=str(b.get('qr') or '');deal_id=None
                ro_,subject=role(u)
                if ro_ not in('owner','admin','client'):return s.send(403,b'{}')
                if qr:
                    record=ID.fullmatch(qr) and row(qr)
                    if not record or record[0]!='qr' or record[1].get('access_revoked'):return s.send(404,b'{}')
                    deal_id=record[1]['deal'];deal=doc(deal_id)
                    if not deal or (ro_=='client' and deal.get('client')!=subject):return s.send(403,b'{}')
                if len(IMG)>200:IMG.clear()
                k=secrets.token_urlsafe(16);IMG[k]=(t+600,png,deal_id,subject if ro_=='client' else None)
            return s.send(200,json.dumps({'url':'/img/'+k}).encode())
        with L:
            ro,x=role(u)
            if p in ('/api/payquote','/api/pay','/api/pay-debt','/api/cancel-debt-pay','/api/move-payment','/api/cancel-payment','/api/early-buyout',
                     '/api/reschedule-request','/api/reschedule','/api/reschedule-manual','/api/close-deal','/api/return-deal',
                     '/api/calendar','/api/tariff-image','/api/deal-note','/api/bike-preparation','/api/bike-writeoff','/api/payment-report','/api/statement',
                     '/api/rental-act','/api/rental-renew','/api/deposit-return','/api/catalog-delete'):
                try:
                    result=workflow_action(p,b,ro,x);db.commit()
                    return s.send(200,json.dumps(result).encode())
                except Bad as e:
                    db.rollback();return s.send(400,json.dumps({'err':str(e)}).encode())
            if ro in('owner','admin'):
                P=set(x[1].get('perms',[])) if ro=='admin' else None
                if p in('/api/bill','/api/unk','/api/tochka','/api/mockpay'):
                    try:return s.send(200,json.dumps(owner_act(p,b,ro,x,P)).encode())
                    except Bad as e:
                        db.rollback();return s.send(400,json.dumps({'err':str(e)}).encode())
                who_=ro=='admin' and '@'+str(x[1].get('name',''))[:40] or ''
                if p in('/api/put','/api/del'):
                    if p=='/api/del' and ro!='owner':return s.send(403,b'{}')
                    i=str(b.get('id',''))
                    if not ID.fullmatch(i):return s.send(400,b'{}')
                    r=db.execute('select kind,data from docs where id=?',(i,)).fetchone();old=r and json.loads(r[1])
                    if p=='/api/del' and ((r and r[0] in ('bike','client')) or b.get('kind') in ('bike','client')):
                        if not r:return s.send(200,b'{"deleted":false}')
                        if r[0] not in ('bike','client') or b.get('kind',r[0])!=r[0]:return s.send(409,b'{"err":"conflict"}')
                        try:result=delete_archived_card(i,r[0],old,b,ts)
                        except Bad as e:return s.send(400,json.dumps({'err':str(e)}).encode())
                        if result is None:return s.send(409,b'{"err":"conflict"}')
                        return s.send(200,json.dumps(result).encode())
                    action=p[5:]
                    if p=='/api/del' and ((r and r[0]=='expense') or b.get('kind')=='expense'):
                        if not r or r[0]!='expense' or b.get('kind')!='expense' or b.get('version')!=old.get('_v',0):
                            return s.send(409,b'{"err":"conflict"}')
                        action='expense-delete'
                    if p=='/api/put':
                        k=b.get('kind');new=b.get('data')
                        if k not in KINDS or k in SRV or not isinstance(new,dict) or (r and r[0]!=k):return s.send(400,b'{}')
                        if k in ('bike','client') and ((old or {}).get('erased') or new.get('erased')):
                            return s.send(409,b'{"err":"conflict"}')
                        if ro=='admin':
                            new=amerge(P,k,old,new)
                            if new is None:return s.send(403,b'{}')
                        elif k=='admin':
                            new=clean_admin(i,old,new)
                            if new is None:return s.send(400,b'{}')
                        if ((old is not None and new.get('_v',0)!=old.get('_v',0)) or
                            (old is None and k in ('client','bike','deal','expense') and (b.get('existing') or new.get('_v',0)))):
                            return s.send(409,b'{"err":"conflict"}')
                        if k=='expense':
                            try:
                                new=validate_expense(new)
                                received_date(new['date'],tod())
                            except Bad as e:return s.send(400,json.dumps({'err':str(e)}).encode())
                            action='expense-edit' if old else 'expense-add'
                        if k=='cfg':
                            try:
                                if 'tariffs' in new:validate_tariffs(new['tariffs'],(old or {}).get('tariffs'))
                                if 'purchaseCosts' in new:validate_purchase_costs(new['purchaseCosts'])
                                if 'advanceDiscounts' in new:validate_advance_discounts(new['advanceDiscounts'])
                                if any(field in new for field in RENTAL_CATALOG_FIELDS):validate_rental_catalog(new)
                                for field in ('multi_discount','dd','dbd','late_fee_amount','late_fee_day'):
                                    new.pop(field,None)
                                for field in ('receipt','acq','tax','pen'):
                                    if field in new and (not old or old.get(field)!=new[field]):
                                        value=float(new[field])
                                        if not math.isfinite(value) or not 0<=value<=100:raise Bad('Проценты должны быть от 0 до 100.')
                                        new[field]=value
                                if 'dmin' in new and (not old or old.get('dmin')!=new['dmin']):
                                    value=whole(new['dmin'],'минимальный процент')
                                    if not 50<=value<=100:raise Bad('Минимальная частичная оплата — от 50 до 100%.')
                                    new['dmin']=value
                            except (Bad,ValueError,TypeError) as e:return s.send(400,json.dumps({'err':str(e)}).encode())
                        if k=='bike' and new.get('model') is not None:
                            model=new['model']
                            if not known_bike_model(model):
                                return s.send(400,json.dumps({'err':'Выберите модель велосипеда.'}).encode())
                            if model!=(old or {}).get('model') and model in cfgv('catalogArchivedModels',[]):
                                return s.send(400,json.dumps({'err':'Эта модель удалена из каталога.'}).encode())
                        if k=='bike' and 'batteries' in new and not valid_batteries(new['batteries']):
                            return s.send(400,json.dumps({'err':'Выберите один или два аккумулятора.'}).encode())
                        if k=='deal':
                            try:
                                if (new.get('defer') or [])!=((old or {}).get('defer') or []):
                                    raise Bad('Сроки ранее согласованных платежей зафиксированы.')
                                if old and new.get('lease')!=old.get('lease'):
                                    raise Bad('Условия аренды фиксируются при выдаче.')
                                if (old and new.get('late_fee')!=old.get('late_fee')) or (not new.get('lease') and 'late_fee' in new):
                                    raise Bad('Условия штрафа фиксируются при выдаче.')
                                if (new.get('status')=='archived' and (not old or old.get('status')!='archived')
                                    or new.get('handover')!=(old or {}).get('handover')
                                    or new.get('handover') and new.get('status')!='archived'):
                                    raise Bad('Подтвердите передачу велосипеда через «Закрыть выкуп».')
                                if old and old.get('lease'):
                                    protected=('client','start','n','type','pay','last','total','cost','paid','deposit','deposit_refund',
                                               'early','debt','dpays','bonuses','schedule','shift','status','closed','signed_at',
                                               'refund','refund_date','completed_at','defer','bike_name','bike_vin')
                                    if any(new.get(field)!=old.get(field) for field in protected):
                                        raise Bad('Для оплаты и изменения аренды используйте действия в карточке.')
                                    if new.get('bike')!=old.get('bike'):
                                        replacement=doc(new['bike']) or {}
                                        if old.get('payoff') or replacement.get('model')!=old['lease']['model']:
                                            raise Bad('Для замены выберите велосипед той же модели до выкупа.')
                                        new.update(bike_name=replacement.get('name',''),bike_vin=replacement.get('vin',''))
                                if any(new.get(field)!= (old or {}).get(field) for field in ('payoff','payoff_terms')):
                                    raise Bad('Условия досрочного выкупа меняются отдельным действием.')
                                if old and old.get('payoff_terms') and any(new.get(field)!=old.get(field) for field in ('start','total','down')):
                                    raise Bad('Цена, дата выдачи и первоначальный взнос зафиксированы.')
                                if old and old.get('payoff') and any(new.get(field)!=old.get(field) for field in ('paid','early','dpays','debt','schedule','n','type','pay','last','shift','bonuses','pen','pw','np','defer')):
                                    raise Bad('История оплат зафиксирована после досрочного выкупа.')
                                if not old:validate_new_deal(new,tod())
                                elif new.get('tariff')!=old.get('tariff'):
                                    raise Bad('Тариф фиксируется при оформлении выкупа.')
                                if 'gift' in new and (not old or old.get('gift')!=new['gift']):
                                    new['gift']=validate_gift(new['gift'])
                                if new.get('pen') is not None and (not old or old.get('pen')!=new.get('pen')):
                                    rate=float(new['pen'])
                                    if not math.isfinite(rate) or not 0<=rate<=100:raise Bad('Неустойка должна быть от 0 до 100%.')
                                    new['pen']=rate
                                opening=not old or old.get('status')!='active'
                                if new.get('status')=='active':
                                    if (opening or old.get('bike')!=new.get('bike')) and not bike_available(new.get('bike'),i):
                                        raise Bad('Выберите свободный велосипед со статусом «Готов к выдаче».')
                                    if opening or old.get('client')!=new.get('client'):
                                        client_id=new.get('client');client=row(client_id)
                                        if not client or client[0]!='client' or client[1].get('archived'):
                                            raise Bad('Выберите действующую карточку клиента.')
                                        if any(j!=i and d.get('client')==client_id and d.get('status')=='active' for j,d in docs_of('deal')):
                                            raise Bad('У клиента уже есть действующий выкуп.')
                            except (Bad,ValueError,TypeError) as e:return s.send(400,json.dumps({'err':str(e)}).encode())
                            stamp_receipts(new,old)
                            if old and old.get('status')=='active':
                                if new.get('status')=='seized':
                                    update_preparation(old['bike'],'inspection',tod(),who_.lstrip('@'),returned=True)
                                    close_pending_schedule(i,tod(),who_.lstrip('@'))
                                elif new.get('status')=='active' and new.get('bike')!=old.get('bike'):
                                    date=((new.get('swaps') or [{}])[-1]).get('date') or tod()
                                    update_preparation(old['bike'],'inspection',date,who_.lstrip('@'),returned=True)
                            completion_notice(old,new)
                        new['_v']=(old or {}).get('_v',0)+1
                        save(i,k,new)
                    else:db.execute('delete from docs where id=?',(i,));new=None
                    db.execute('insert into log values(?,?,?,?,?)',(ts,action+who_,i,r and strip(r[1]),new and strip(json.dumps(new))));db.commit()
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
                        if (ro=='admin' and 'clients' not in P) or not a or a[0]!='client' or a[1].get('erased'):return s.send(403,b'{}')
                    if p=='/api/invite':
                        if not BOT[0]:return s.send(500,b'{}')
                        quick=bool(b.get('qr')) and not c.startswith('adm:')
                        k=('q_' if quick else '')+secrets.token_urlsafe(12);ttl=600 if quick else 7*86400
                        db.execute('delete from inv where exp<?',(t,));db.execute('insert into inv values(?,?,?)',(k,c,t+ttl))
                        action='invite-qr' if quick else 'invite'
                        subject=json.dumps({'name':a[1].get('name'),'login_method':'QR' if quick else 'Ссылка','ttl':ttl})
                        db.execute('insert into log values(?,?,?,?,?)',(ts,action+who_,c,None,subject));db.commit()
                        return s.send(200,json.dumps({'tok':k,'bot':BOT[0],'qr':quick,'ttl':ttl}).encode())
                    if c.startswith('adm:'):
                        a[1]['tg']=None;a[1]['_v']=a[1].get('_v',0)+1;save(c[4:],'admin',a[1])
                    else:db.execute('delete from bind where client=?',(c,))
                    subject=json.dumps({'name':a[1].get('name')})
                    db.execute('insert into log values(?,?,?,?,?)',(ts,'unbind'+who_,c,None,subject));db.commit();return s.send(200,b'{}')
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
                        access=json.dumps({'name':c.get('name'),'login_method':'Ссылка'})
                        db.execute('insert into log values(?,?,?,?,?)',(ts,'login@'+c.get('name','')[:40],tgt,None,access));db.commit()
                        say(f"Администратор {c.get('name')} вошёл в приложение.");return s.send(200,b'{}')
                else:
                    record=tgt and row(tgt);c=record and record[0]=='client' and record[1]
                    quick=str(b.get('tok','')).startswith('q_')
                    if c and not c.get('erased') and (quick or (ph and digits(c.get('phone'))==ph)):
                        db.execute('insert or replace into bind values(?,?)',(u,tgt));db.execute('delete from inv where tok=?',(str(b.get('tok')),))
                        access=json.dumps({'name':c.get('name'),'login_method':'QR' if quick else 'Ссылка'})
                        db.execute('insert into log values(?,?,?,?,?)',(ts,'login-client@'+client_log_actor(tgt),tgt,None,access));db.commit()
                        say(f"Клиент {c.get('name')} вошёл в приложение.");return s.send(200,b'{}')
                if len(TRY[u])==3:say(f'Неудачные попытки входа (Telegram ID {u}).')
                return s.send(403,b'{}')
        return s.send(403,b'{}')
NOTICE_LOCK=threading.Lock()
def morning(t):
    """Queue and retry today's reminders. A Telegram success records the delivery."""
    if not NOTICE_LOCK.acquire(blocking=False):return
    try:
        now=time.time();day=str(t);pending={}
        with L,db:
            cf=doc('cfg') or {}
            ds=docs_of('deal')
            sent={key for (key,) in db.execute('select k from ntf where k between ? and ?',(day,day+'~'))}
            key=f'{day}:daily'
            if cf.get('nown') and key not in sent:
                count=due_today([d for _,d in ds],t)
                pending[key]=(OWNER,f'Сегодня платят клиентов: {count}' if count else 'Сегодня платежей нет')
            if cf.get('ncli'):
                chats={}
                for chat,client in db.execute('select tg,client from bind'):chats.setdefault(client,[]).append(chat)
                for i,d in ds:
                    if d.get('status')!='active':continue
                    schedule=sched(d);numbers={x['k']:n for n,x in enumerate(schedule,1)}
                    for x in sorted(unpaid_installments(d,schedule),key=lambda x:payment_deadline(d,x)):
                        deadline=D(payment_deadline(d,x));wait=(deadline-t).days
                        if wait>1:break
                        if wait<0:continue
                        base=f"{day}:rem:{i}:{x['k']}:{deadline}:{wait}"
                        if base in sent:continue
                        label=(f"аренда за неделю {numbers[x['k']]} — {rub(x['amt'])}." if d.get('lease') else
                               f"платёж {rub(x['amt'])} (период {numbers[x['k']]} из {len(schedule)}).")
                        body=f"Напоминание: завтра, {dm(deadline)}, {label}" if wait else f"Сегодня день оплаты: {label}"
                        for chat in chats.get(d['client'],[]):
                            key=f'{base}:{chat}'
                            if key not in sent:pending[key]=(chat,body)
            db.execute('delete from notice_queue where day!=?',(day,))
            obsolete=[(key,) for (key,) in db.execute('select k from notice_queue') if key not in pending]
            db.executemany('delete from notice_queue where k=?',obsolete)
            db.executemany('insert into notice_queue values(?,?,?,?,0,?) on conflict(k) do update set body=excluded.body',
                           [(key,day,chat,body,now) for key,(chat,body) in pending.items()])
            db.execute("delete from ntf where k<? and substr(k,1,1) between '0' and '9'",(str(t-dt.timedelta(days=60)),))
            ready=db.execute('select k,chat,body,attempts from notice_queue where next<=? order by next limit 50',(now,)).fetchall()
        for key,chat,body,attempts in ready:
            with L:
                if not db.execute('select 1 from notice_queue where k=?',(key,)).fetchone():continue
            try:
                delivered=tg('sendMessage',{'chat_id':chat,'text':body}).get('ok') is True
            except Exception as error:
                print('reminder',type(error).__name__);delivered=False
            with L,db:
                if delivered:
                    db.execute('insert or ignore into ntf select k from notice_queue where k=?',(key,))
                    db.execute('delete from notice_queue where k=?',(key,))
                else:
                    retry=time.time()+min(1800,30*2**min(attempts,6))
                    db.execute('update notice_queue set attempts=?,next=? where k=?',(attempts+1,retry,key))
    finally:NOTICE_LOCK.release()

def job():
    last_snapshot=None
    while 1:
        n=dt.datetime.now(MSK)
        if n.hour==3 and n.date()!=last_snapshot:
            try:
                with L:snap('app')
                last_snapshot=n.date()
            except Exception as e:print('snapshot',e)
        if n.hour>=10 and not NOTICE_LOCK.locked():
            threading.Thread(target=morning,args=(n.date(),),daemon=True).start()
        if time.time()-PL_LAST[0]>170:
            PL_LAST[0]=time.time()
            threading.Thread(target=poll,daemon=True).start()
        time.sleep(30)
def migrate():
    """One-time: administrators with early payment access also get the «Неустойка» permission."""
    with L:
        os.chmod(BK,0o700)
        legacy=row('tch')
        if legacy:
            if not os.path.exists(BANK_SETTINGS):save_bank_settings(legacy[1])
            db.execute('pragma secure_delete=on')
            db.execute("delete from docs where id='tch'")
            db.execute("delete from log where id='tch'")
        migrate_fee_records()
        if db.execute("select 1 from ntf where k='mig:pen'").fetchone():db.commit();return
        for i,d in db.execute("select id,data from docs where kind='admin'").fetchall():
            d=json.loads(d)
            if 'early' in d.get('perms',[]) and 'pen' not in d['perms']:d['perms']=[q for q in PERMS if q in d['perms']+['pen']];save(i,'admin',d)
        db.execute("insert into ntf values('mig:pen')");db.commit()
PUBLIC_OPERATOR='Старчевский Максим Юрьевич'
PUBLIC_OPERATOR_SHORT='Старчевский М.Ю.'
PUBLIC_INN='781154545535'
PUBLIC_OGRNIP='323784700210652'
PUBLIC_PHONE='+7 921 752-10-54'
PUBLIC_CITY='Санкт-Петербург'
PRIVACY_TITLE='Политика обработки персональных данных'

def privacy_paragraphs():
    source=Path(__file__).with_name('static')/'privacy.txt'
    text=source.read_text(encoding='utf-8').format(
        operator=PUBLIC_OPERATOR,inn=PUBLIC_INN,ogrnip=PUBLIC_OGRNIP,phone=PUBLIC_PHONE,city=PUBLIC_CITY
    )
    return text.strip().split('\n\n')

def privacy_body(heading):
    return ''.join(
        f'<{heading}>{escape(p[3:])}</{heading}>' if p.startswith('## ') else f'<p>{escape(p)}</p>'
        for p in privacy_paragraphs()
    )

def privacy_page():
    return f'''<!doctype html>
<html lang="ru">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{PRIVACY_TITLE} · Вольт Вояж</title>
<style>
    :root {{color-scheme:light; background:#f1f2ee; color:#1f2b28; font:16px/1.6 system-ui,sans-serif}}
    body {{margin:0; padding:clamp(12px,4vw,44px)}}
    main {{box-sizing:border-box; max-width:760px; margin:auto; padding:clamp(20px,5vw,48px);
        border-radius:24px; background:#fff; overflow-wrap:anywhere}}
    header p {{margin:0; color:#2f5d50; font-weight:750}}
    h1 {{font-size:clamp(1.55rem,5vw,2.3rem); line-height:1.15; margin:.35em 0 .8em}}
    h2 {{font-size:1.1rem; line-height:1.35; margin:1.45em 0 .45em}}
    p {{margin:.55em 0}}
</style>
<main><header><p>Вольт Вояж</p><h1>{PRIVACY_TITLE}</h1></header>{privacy_body('h2')}</main>
</html>'''

PUBLIC_MENU='vv:'
PUBLIC_PAGES=('home','tariffs','payment','return','details','contact','privacy')

def public_button(label,page):
    return {'text':label,'callback_data':PUBLIC_MENU+page}

def public_tariffs(settings):
    models=rental_models(settings)
    brands=settings.get('rentalBrands') or {}
    for entry in sorted(models.values(),key=lambda model:(brands.get(model['brand'],'').casefold(),model['name'].casefold())):
        brand=brands.get(entry['brand'],'')
        model=entry['name']
        title=f'{brand} {model}' if brand and brand.casefold() not in model.casefold() else model
        for kit,plans in sorted(entry['plans'].items()):
            batteries=entry['batteries']
            parts={}
            for slot in kit.split(','):
                battery=batteries[slot]
                label=f"{battery['voltage']} В / {battery['capacity']} А·ч".replace('.',',')
                if battery.get('name'):label+=f" ({battery['name']})"
                parts[label]=parts.get(label,0)+1
            capacity=' + '.join(f'{count} × {label}' if count>1 else label for label,count in parts.items())
            offers=[]
            for weeks in RENTAL_WEEKS:
                if plan:=plans.get(str(weeks)):
                    deposit=rub(plan['deposit']) if plan['deposit'] else '0 ₽'
                    offers.append(f"{weeks} недель · {rub(plan['weekly'])} в неделю · выкуп {rub(plan['price'])} · обеспечение {deposit}")
            if offers:
                yield '\n'.join([title+' · АКБ '+capacity,*offers])

def public_text_pages(parts,limit=3200):
    pages=[]
    page=''
    for part in parts:
        while len(part)>limit:
            if page:pages.append(page);page=''
            end=part.rfind(' ',0,limit+1)
            if end<=0:end=limit
            pages.append(part[:end]);part=part[end:].lstrip()
        if page and len(page)+len(part)+2>limit:
            pages.append(page);page=''
        page+=('\n\n' if page else '')+part
    if page:pages.append(page)
    return pages

def public_bot_message(section,index,settings,username,domain):
    rows=[]
    if section=='home':
        body=(f'Вольт Вояж\nАренда электровелосипедов с правом выкупа\n\n{PUBLIC_CITY}. '
              'Выдача и возврат по записи. Срок аренды 20 или 26 недель, оплата еженедельно. '
              'Выкуп доступен с пятой недели после полной оплаты первых четырёх.\n\n'
              'Договор подписываем при выдаче. Тогда вы получите ссылку на кабинет с графиком и оплатой.')
        rows=[
            [public_button('Тарифы','tariffs'),public_button('Как платить','payment')],
            [public_button('Выдача и возврат','return')],
            [public_button('Реквизиты и документы','details'),public_button('Связаться','contact')]
        ]
        if re.fullmatch(r'[A-Za-z0-9_]{5,32}',username or ''):
            rows.append([{'text':'Личный кабинет','url':f'https://t.me/{username}?startapp'}])
    elif section in ('tariffs','privacy'):
        if section=='tariffs':
            heading='Тарифы аренды с правом выкупа'
            parts=public_tariffs(settings)
            empty=f'Уточните актуальные цены и наличие велосипедов по телефону {PUBLIC_PHONE}.'
        else:
            heading=PRIVACY_TITLE
            parts=(p.removeprefix('## ') for p in privacy_paragraphs())
            empty=''
        pages=public_text_pages(parts) or [empty]
        index=min(index,len(pages)-1)
        body=f'{heading}'+(f' · {index+1} из {len(pages)}' if len(pages)>1 else '')+'\n\n'+pages[index]
        navigation=[]
        if index:navigation.append(public_button('← Назад',f'{section}:{index-1}'))
        if index+1<len(pages):navigation.append(public_button('Дальше →',f'{section}:{index+1}'))
        if navigation:rows.append(navigation)
        if section=='privacy':rows.append([public_button('К реквизитам','details')])
    elif section=='payment':
        body=('Как платить\n\n'
              'При выдаче оплачиваются первая неделя и обеспечительный платёж, если он указан в тарифе. '
              'Далее график, суммы и фактические оплаты видны в личном кабинете. '
              'Для оплаты по СБП откройте платёж в кабинете и выберите свой банк. '
              'Можно скачать QR-код и загрузить картинку в онлайн-банке, если он поддерживает оплату из галереи. '
              'Если оплата в кабинете недоступна, позвоните нам.\n\n'
              f'Если взнос полностью неоплачен, первые {LATE_FEE_DAY-1} дня после срока проходят без начислений. '
              f'На {LATE_FEE_DAY}-й день добавляется разовый штраф {rub(LATE_FEE_AMOUNT)}. '
              f'С {UNPAID_PENALTY_DAY}-го дня начисляется ежедневная неустойка.\n\n'
              'Можно оплатить до четырёх ближайших периодов за раз или внести 50% за ближайший период. '
              f'Внесите вторую половину до конца {PARTIAL_GRACE_DAYS}-го календарного дня после даты по графику. '
              f'С {PARTIAL_GRACE_DAYS+1}-го дня на остаток начисляется только ежедневная неустойка. '
              'Начисления, возникшие до первой оплаты, входят в этот платёж.\n\n'
              f'При оплате двух и более периодов одним платежом {RENTAL_BUYOUT_REDUCTION_RATE}% от арендной платы '
              'уменьшают цену выкупа. Сумма платежа за аренду сохраняется.\n\n'
              'Выкуп доступен с пятой недели после полной оплаты первых четырёх. '
              'Арендные платежи засчитываются в пределах цены выкупа. Сумма доплаты рассчитана в кабинете.')
    elif section=='return':
        body=(f'Выдача и возврат\n\n{PUBLIC_CITY}. Выдача и возврат по предварительной записи. '
              f'Позвоните {PUBLIC_PHONE}, чтобы согласовать дату, время и адрес.\n\n'
              'При возврате сверяем даты и платежи. Если аренда внесена вперёд, рассчитываем возврат оплаты '
              'за неиспользованные дни. Обеспечительный платёж возвращаем с учётом условий договора, '
              'отдельно от расчёта по аренде. Сумму, способ и срок возврата сообщаем после сверки. '
              'По вопросам об оплате или возврате можно позвонить по тому же номеру.')
        rows.append([public_button('Связаться','contact')])
    elif section=='details':
        body=(f'Реквизиты и документы\n\nИП {PUBLIC_OPERATOR}\n'
              f'ИНН {PUBLIC_INN}\nОГРНИП {PUBLIC_OGRNIP}\n{PUBLIC_CITY}\nТелефон {PUBLIC_PHONE}')
        rows.append([public_button('Политика обработки данных','privacy')])
        if re.fullmatch(r'[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+',domain or ''):
            rows.append([{'text':'Читать политику в браузере','url':f'https://{domain}/privacy'}])
    else:
        body=f'Связаться с Вольт Вояж\n\n{PUBLIC_PHONE}\n{PUBLIC_CITY}. Выдача и возврат по записи.'
    if section!='home':rows.append([public_button('В меню','home')])
    return {'text':body,'reply_markup':{'inline_keyboard':rows}}

def bank_terms_page(settings):
    source=Path(__file__).with_name('static')/'terms.html'
    tariffs=[]
    for offer in public_tariffs(settings):
        title,*plans=offer.splitlines()
        items=''.join(f'<li>{escape(plan)}</li>' for plan in plans)
        tariffs.append(f'<article><h3>{escape(title)}</h3><ul>{items}</ul></article>')
    sections={}
    for section in ('payment','return'):
        message=public_bot_message(section,0,settings,None,'')['text']
        _,*paragraphs=message.split('\n\n')
        sections[section]=''.join(f'<p>{escape(paragraph)}</p>' for paragraph in paragraphs)
    return Template(source.read_text(encoding='utf-8')).substitute(
        tariffs=''.join(tariffs) or '<p>Актуальные тарифы и наличие уточняйте по телефону.</p>',
        payment=sections['payment'],returns=sections['return'],city=escape(PUBLIC_CITY),
        operator=escape(PUBLIC_OPERATOR),inn=escape(PUBLIC_INN),ogrnip=escape(PUBLIC_OGRNIP),
        phone=escape(PUBLIC_PHONE),phone_href=safe_phone(PUBLIC_PHONE),
        privacy_title=escape(PRIVACY_TITLE),privacy_body=privacy_body('h3')
    )

def public_bot_update(update):
    callback=update.get('callback_query')
    message=callback.get('message',{}) if callback else update.get('message',{})
    chat=message.get('chat',{})
    if chat.get('type')!='private':return
    if callback:
        if callback.get('from',{}).get('id')!=chat['id']:return
        data=callback.get('data','')
        if not data.startswith(PUBLIC_MENU):return
        part=data[len(PUBLIC_MENU):].split(':')
        section=part[0]
        if section not in PUBLIC_PAGES or len(part)>2 or (len(part)==2 and (
            section not in ('tariffs','privacy') or not re.fullmatch(r'[0-9]{1,6}',part[1])
        )):return
        index=int(part[1]) if len(part)==2 else 0
        try:tg('answerCallbackQuery',{'callback_query_id':callback['id']})
        except urllib.error.HTTPError as e:
            if e.code!=400:raise
        method='editMessageText'
        target={'chat_id':chat['id'],'message_id':message['message_id']}
    else:
        command=message.get('text','').split(maxsplit=1)
        if not command or command[0].split('@',1)[0]!='/start':return
        section,index,method,target='home',0,'sendMessage',{'chat_id':chat['id']}
    with L:settings=doc('cfg') or {}
    response=public_bot_message(section,index,settings,BOT[0],os.environ.get('DOMAIN',''))
    tg(method,{**target,**response})

def public_bot_poll():
    botname()
    offset=0
    listening=False
    while True:
        try:
            updates=tg('getUpdates',{'offset':offset,'timeout':15,'allowed_updates':['message','callback_query']})['result']
            if not listening:
                print('Telegram menu: listening for /start')
                listening=True
            if not BOT[0]:botname()
            for update in updates:
                try:public_bot_update(update)
                except urllib.error.HTTPError as e:
                    if e.code not in (400,403):raise
                    print('Telegram menu: reply rejected',e.code)
                except (urllib.error.URLError, TimeoutError, ConnectionError, HTTPException):
                    # Keep the offset on this update so it can be retried after reconnecting.
                    raise
                except Exception as e:
                    print('Telegram menu update:',type(e).__name__)
                offset=update['update_id']+1
        except urllib.error.HTTPError as e:
            print('Telegram menu:',e.code)
            time.sleep(30 if e.code in (401,409,429) else 5)
        except Exception as e:
            print('Telegram menu:',type(e).__name__)
            time.sleep(5)

if __name__=='__main__':
    migrate()
    threading.Thread(target=job,daemon=True).start()
    threading.Thread(target=public_bot_poll,daemon=True).start()
    ThreadingHTTPServer(('',int(os.environ.get('PORT','8080'))),H).serve_forever()
