(function(g){
const MK={w:{8:30,12:42,16:55,20:68,26:88},m:{2:30,3:42,4:55,5:68,6:88}},DS={30000:2,50000:4};
const BIKE_MODELS={monster:'Монстр',u2:'U2',u2pro:'U2 Pro'};
const BATTERY_COUNTS=[1,2];
const WEEKLY_TERMS=[8,12,16,20,26];
const RENTAL_WEEKS=[20,26];
const ADVANCES=[10000,20000,30000,40000,50000];
const CLIENT_PAYMENT_MAX_PERIODS=4;
const RENTAL_BUYOUT_MIN_PERIODS=4;
const LATE_FEE_AMOUNT=350;
const LATE_FEE_DAY=3;
const UNPAID_PENALTY_DAY=4;
const PARTIAL_GRACE_DAYS=4;
const tariffKey=(model,batteries=1)=>batteries===2?model+'-2-akb':model;
const up=(x,s)=>Math.ceil(x/s-1e-9)*s;
function add(d,n){const t=new Date(d+'T00:00:00Z');t.setUTCDate(t.getUTCDate()+n);return t.toISOString().slice(0,10)}
const diff=(a,b)=>Math.round((new Date(a)-new Date(b))/864e5);
const today=()=>new Date(Date.now()+108e5).toISOString().slice(0,10);
const minor=n=>Math.round(n*100), money=n=>n/100;
function calc(o){const fixed=o.weekly!=null,mk=fixed?0:((o.mk||MK)[o.type]||{})[o.n]||0,d=fixed?0:o.disc!=null&&o.disc!==''?+o.disc:((o.ds||[[30000,2],[50000,4]]).find(x=>x[0]==o.down)||[0,0])[1],
cost=o.cost||0,bike=fixed?money(minor(o.weekly)*o.n):Math.round(cost*(1+(mk-d)/100)),
extra=(o.extras||[]).reduce((sum,e)=>sum+minor(e.price),0),exc=(o.extras||[]).reduce((a,e)=>a+e.cost,0),
total=money(minor(bike)+extra),bal=money(minor(total)-minor(o.down||0)),
tax=Math.round(total*(o.tax==null?7:o.tax)/100),acq=Math.round(total*(o.acq==null?0:o.acq)/100),receipt=Math.round(total*(o.receipt||0)/100),profit=total-cost-exc-tax-acq-receipt;
const rounded=up(bal/o.n,o.type=='w'?100:1000), balance=minor(bal);
const pay=balance<=0?0:fixed?money(Math.floor(balance/o.n)):balance>minor(rounded)*(o.n-1)?rounded:Math.floor(bal/o.n)||money(Math.floor(balance/o.n));
const last=money(balance-minor(pay)*(o.n-1));
return{mk,d,bike,total,bal,pay,last,tax,acq,receipt,profit,pct:cost?profit/cost*100:0}}
function buyoutQuote({weekly,weeks,down,discount}){
    const baseTotal=Math.round(minor(weekly)*weeks/100),total=baseTotal-discount;
    const bal=total-down,pay=bal>0?Math.floor(bal/weeks):0;
    const last=bal>0?bal-pay*(weeks-1):0;
    return {baseTotal,total,down,discount,weeks,bal,pay,last};
}
function receiptCharges(cash,{tax,acq,receipt}){
    const charge=rate=>{
        const percent=Number(rate);
        if(!cash||!(percent>0&&percent<=100))return 0;
        const [coefficient,exponent=0]=String(percent).split('e');
        const [integer,decimals='']=coefficient.split('.');
        const divisor=10n**BigInt(decimals.length+2-Number(exponent));
        const numerator=BigInt(Math.abs(cash))*BigInt(integer+decimals);
        return Math.sign(cash)*Number((numerator+divisor/2n)/divisor);
    };
    return {tax:charge(tax),acq:charge(acq),receipt:charge(receipt)};
}
function buyoutForecast(quote,{cost=0,gift=0,tax,acq,receipt,issueMethod='СБП'}){
    const issue=minor(quote.down+quote.pay),regular=minor(quote.pay),final=minor(quote.last);
    const charges=receiptCharges(issue,{tax,acq:issueMethod=='СБП'?acq:0,receipt:issueMethod=='СБП'?receipt:0});
    const next=receiptCharges(regular,{tax,acq,receipt}),last=receiptCharges(final,{tax,acq,receipt});
    const gross=minor(quote.total);
    for(const kind of Object.keys(charges))charges[kind]+=next[kind]*(quote.weeks-2)+last[kind];
    const net=gross-charges.tax-charges.acq-charges.receipt,profit=net-minor(cost)-minor(gift);
    return {gross:money(gross),tax:money(charges.tax),acq:money(charges.acq),receipt:money(charges.receipt),
        net:money(net),profit:money(profit),pct:cost?profit/minor(cost)*100:0};
}
function weeklyProfit({weekly,weeks,cost,tax,acq,receipt}){
    const payment=minor(weekly),gross=payment*weeks;
    const totalFee=rate=>Math.round(payment*rate/100)*weeks;
    const taxFee=totalFee(tax),bankFee=totalFee(acq),receiptFee=totalFee(receipt);
    const net=gross-taxFee-bankFee-receiptFee,profit=net-minor(cost);
    return {gross:money(gross),tax:money(taxFee),acq:money(bankFee),receipt:money(receiptFee),
        net:money(net),profit:money(profit),pct:profit/minor(cost)*100};
}
const rentalKey=slots=>slots.map(String).sort().join(',');
function rentalPrice(value,weeks,field){
    if(!RENTAL_WEEKS.includes(weeks)||!Number.isSafeInteger(value)||value<1)return null;
    const weekly=field=='price'?Math.floor(value/weeks):value;
    const price=field=='price'?value:weekly*weeks;
    if(weekly<1||price>10000000)return null;
    return {weeks,weekly,price,last:price-weekly*(weeks-1)};
}
function rentalForecast(plan,options){
    return buyoutForecast({weeks:plan.weeks,pay:plan.weekly,down:0,
        last:plan.price-plan.weekly*(plan.weeks-1),total:plan.price},options);
}
function rentalPaidAmounts(deal,date=today()){
    const amounts=new Map();
    for(const [key,payment] of Object.entries(deal.paid||{})){
        if(payment.date<=date)amounts.set(Number(key),minor(payment.amt));
    }
    for(const payment of deal.dpays||[]){
        if(payment.date<=date)amounts.set(payment.k,(amounts.get(payment.k)||0)+minor(payment.amt));
    }
    return amounts;
}
function rentalBalance(deal,date=today()){
    const paid=[...rentalPaidAmounts(deal,date).values()].reduce((sum,cents)=>sum+cents,0);
    const price=minor(deal.lease.price);
    return {paid:money(paid),credited:money(Math.min(price,paid)),remaining:money(Math.max(0,price-paid))};
}
function rentalBuyoutProgress(deal,date=today()){
    const amounts=rentalPaidAmounts(deal,date),weekly=minor(deal.lease.weekly);
    const milestones=Array.from({length:RENTAL_BUYOUT_MIN_PERIODS},(_,i)=>amounts.get(i+1)===weekly);
    const all=[...Object.values(deal.paid||{}),...(deal.dpays||[])];
    const opensOn=all.reduce((latest,payment)=>payment.date>latest?payment.date:latest,add(deal.start,7*RENTAL_BUYOUT_MIN_PERIODS));
    return {milestones,opensOn,paid:[...amounts.values()].filter(cents=>cents===weekly).length,remaining:milestones.filter(paid=>!paid).length};
}
function rentalPayoff(deal,date=today()){
    if(!deal.lease||deal.status!='active'||deal.payoff)return null;
    const progress=rentalBuyoutProgress(deal,date);
    if(progress.remaining||progress.opensOn>date)return null;
    const {paid,credited,remaining}=rentalBalance(deal,date);
    const charges=unpaid(deal).map(row=>installmentCharges(deal,row,date));
    const pen=charges.reduce((sum,row)=>sum+row.pen,dstat(deal,date)?.pen||0),fine=charges.reduce((sum,row)=>sum+(row.fine||0),0);
    return {date,price:deal.lease.price,rent_paid:paid,credited,paid:credited,
        principal:remaining,pen,...(fine?{fine}:{}),saved:0,total:money(minor(remaining)+minor(pen)),version:deal._v||0};
}
function sched(d){
    const paid=d.paid||{},step=d.type=='m'?30:7;
    if(d.lease)return Array.from({length:d.n},(_,i)=>({k:i+1,due:add(d.start,i*7),amt:d.lease.weekly}));
    if(Array.isArray(d.schedule)){
        return d.schedule.map(row=>({...row,due:paid[row.k]?.due||add(row.due,paid[row.k]?0:(d.shift||0))}))
            .filter(row=>row.amt>0||paid[row.k]);
    }
    const rows=[];
    for(let k=1;k<=d.n;k++){
        rows.push({k,due:paid[k]?.due||(k==1?d.start:add(d.start,step*(k-1)-1+(paid[k]?0:(d.shift||0)))),amt:k==d.n?d.last:d.pay});
    }
    let remaining=(d.early||[]).reduce((sum,payment)=>sum+payment.amt,0);
    // Historic fully paid rows can already contain part of the early credit.
    const consumed=rows.reduce((sum,row)=>{
        const payment=paid[row.k];
        return sum+(payment&&!payment.part?Math.max(0,row.amt-payment.amt):0);
    },0);
    remaining=Math.max(0,remaining-consumed);
    for(let i=rows.length-1;i>=0&&remaining>0;i--){
        if(paid[rows[i].k])continue;
        const used=Math.min(remaining,rows[i].amt);
        rows[i].amt-=used;
        remaining-=used;
    }
    return rows.map(row=>{
        const payment=paid[row.k];
        return payment&&!payment.part?{...row,amt:payment.amt}:row;
    }).filter(row=>row.amt>0||paid[row.k]);
}
function deadline(d,row){
    return (d.defer||[]).reduce((date,g)=>g.k==row.k&&g.due==row.due&&g.until>date?g.until:date,row.due);
}
const partialPaymentDeadline=(d,row)=>add(deadline(d,row),PARTIAL_GRACE_DAYS);
function unpaid(d,rows=sched(d)){
    if(d.payoff)return [];
    return rows.filter(row=>!d.paid?.[row.k]).sort((a,b)=>d.lease?a.k-b.k:deadline(d,a).localeCompare(deadline(d,b)));
}
const penalty=(a,days,r)=>Math.round(a*Math.max(0,r==null?0.9:r)/100*days);
/* Days of penalty from the last day without penalty b up to date T.
   d.pw: penalty written off on that date (counting starts again from it); d.np: [[from,to|null],...] periods when accrual is switched off:
   the days from `from` up to (not including) `to` are not counted. */
function pdays(b,T,d){d=d||{};if(d.pw&&d.pw>b)b=d.pw;let n=diff(T,b);if(n<=0)return 0;
(d.np||[]).forEach(f=>{const a1=add(b,1),lo=a1>f[0]?a1:f[0],e=f[1]?add(f[1],-1):T,hi=e<T?e:T,o=diff(hi,lo)+1;if(o>0)n-=o});return Math.max(0,n)}
const nopen=d=>((d&&d.np)||[]).some(f=>!f[1]);
const installmentPenaltyBase=limit=>add(limit,UNPAID_PENALTY_DAY-1);
function installmentCharges(d,row,date){
    const limit=deadline(d,row),days=pdays(installmentPenaltyBase(limit),date,d);
    const chargedOn=add(limit,LATE_FEE_DAY);
    const paused=(d.np||[]).some(([from,to])=>from<=chargedOn&&(!to||chargedOn<to));
    const fine=(d.pw||'')<chargedOn&&chargedOn<=date&&!paused?LATE_FEE_AMOUNT:0;
    return {days,pen:penalty(row.amt,days,d.pen)+fine,...(fine?{fine}:{})};
}
function penaltyDetail(amount,limit,date,d){
    const rate=Math.max(0,d.pen??0.9),days=pdays(limit,date,d),base=d.pw>limit?d.pw:limit;
    let start=add(base,1);
    for(const [from,to] of [...(d.np||[])].sort((a,b)=>a[0].localeCompare(b[0]))){
        if(start&&from<=start&&(!to||to>start))start=to;
    }
    return {amount,limit,rate,start,days,total:penalty(amount,days,rate)};
}
/* The first payment includes accrued charges through its date. pb is the last later payment of the charges. */
function dstat(d,date){
    const g=d?.debt;
    if(d?.payoff||!g||!(g.amt>0))return null;
    const payment=d.paid?.[g.k],first=payment?.part?payment.date:'';
    if(first>date)return null;
    const base=[g.due,g.pb||'',first].sort().at(-1);
    const days=pdays(base,date,d),pen=penalty(g.amt,days,d.pen);
    return {amt:g.amt,due:g.due,k:g.k,days,pen,total:money(minor(g.amt)+minor(pen)),
        late:Math.max(0,diff(date,g.due)),over:date>g.due,base};
}

function paymentQuote(d,options={},settings={},date=today(),{client=false}={}){
    const remaining=unpaid(d);
    if(d.status!='active'||!remaining.length)throw Error('Сейчас нечего оплачивать.');
    if(d.lease&&d.debt)throw Error('Сначала доплатите остаток ближайшего периода.');
    const minimum=Math.max(50,Math.min(100,settings.dmin??50));
    const mode=options.mode||'periods';
    if(mode=='part'){
        if(dstat(d,date))throw Error('Сначала погасите остаток предыдущего платежа.');
        const row=remaining[0];
        let amount=Number(options.amount);
        if(d.lease){
            const half=money(Math.floor(minor(row.amt)/2));
            if('amount' in options&&amount!==half)throw Error('Первая часть составляет 50% платы за период.');
            amount=half;
        }else{
            const min=Math.ceil(row.amt*minimum/100),max=Math.ceil(row.amt)-1;
            if(!Number.isSafeInteger(amount)||amount<min||amount>max){
                throw Error(min>max?'Этот взнос доступен только целиком.':`Часть платежа должна быть от ${min} до ${max} ₽.`);
            }
        }
        const {days,...charges}=installmentCharges(d,row,date);
        return {mode,date,count:1,items:[{...row,amt:amount,...charges}],principal:amount,...charges,
            total:money(minor(amount)+minor(charges.pen)),bonus:0,rate:0,reductions:[],
            rest:money(minor(row.amt)-minor(amount)),debtDue:partialPaymentDeadline(d,row)};
    }
    if(mode!='periods')throw Error('Выберите способ оплаты.');
    const count=Number(options.count??1);
    if(!Number.isSafeInteger(count)||typeof options.count=='boolean'||count<1)throw Error('Выберите количество платежей.');
    if(client&&count>CLIENT_PAYMENT_MAX_PERIODS)throw Error('За один раз можно оплатить до четырёх периодов.');
    if(count>remaining.length)throw Error('Выберите количество платежей.');
    const items=remaining.slice(0,count).map(row=>{
        const {days,...charges}=installmentCharges(d,row,date);
        return {...row,...charges};
    });
    const principal=money(items.reduce((sum,row)=>sum+minor(row.amt),0));
    const pen=items.reduce((sum,row)=>sum+row.pen,0),fine=items.reduce((sum,row)=>sum+(row.fine||0),0);
    return {mode,date,count,items,principal,pen,...(fine?{fine}:{}),total:money(minor(principal)+minor(pen)),bonus:0,rate:0,reductions:[],rest:0};
}

function changeable(d,date,rows=sched(d)){
    if(d.payoff)return [];
    return rows.filter(row=>!d.paid?.[row.k]&&row.due>=date&&deadline(d,row)==row.due);
}
function scheduleBounds(d,date=today(),anchor=null){
    const dates=changeable(d,date).map(row=>row.due).sort();
    if(!dates.length)throw Error('В графике нет будущих платежей для перерасчёта.');
    anchor=anchor||dates[0];
    const min=add(anchor,-7),max=add(anchor,7),last=dates.at(-1);
    return {anchor,min:min>date?min:date,max:max<last?max:last,last};
}
function replan(d,firstDue,weekly,date=today(),clientAnchor=null){
    if(!/^\d{4}-\d{2}-\d{2}$/.test(firstDue)||add(firstDue,0)!=firstDue||firstDue<date){
        throw Error('Выберите дату следующего платежа начиная с сегодняшнего дня.');
    }
    weekly=Number(weekly);
    if(!Number.isSafeInteger(weekly)||weekly<1)throw Error('Введите сумму платежа в целых рублях.');
    const current=sched(d),paid=d.paid||{};
    const future=changeable(d,date,current),keys=new Set(future.map(row=>row.k));
    const kept=current.filter(row=>!keys.has(row.k));
    const balance=money(future.reduce((sum,row)=>sum+minor(row.amt),0));
    if(!balance)throw Error('В графике нет будущих платежей для перерасчёта.');
    if(clientAnchor){
        const bounds=scheduleBounds(d,date,clientAnchor);
        if(firstDue<bounds.min||firstDue>bounds.max)throw Error('Дата нового взноса должна быть в пределах 7 дней от даты в заявке.');
    }

    const last=future.reduce((latest,row)=>row.due>latest?row.due:latest,'');
    if(firstDue>last)throw Error('Выберите дату не позднее последнего платежа действующего графика.');
    const step=d.type=='m'?30:7;
    const slots=Math.ceil(diff(last,firstDue)/step)+1;
    const count=Math.min(slots,Math.ceil(balance/weekly));
    if(count==1&&firstDue<last){
        throw Error('Укажите взнос меньше остатка или выберите дату последнего платежа для оплаты всей суммы.');
    }
    if(count>5200)throw Error('Получается слишком длинный график. Увеличьте сумму платежа.');

    const maxKey=Math.max(d.n||0,...current.map(row=>row.k));
    const changed=[];
    for(let i=0;i<count;i++){
        const final=i==count-1;
        changed.push({
            k:future[i]?.k??(maxKey+i-future.length+1),
            due:final?last:add(firstDue,step*i),
            amt:final?money(minor(balance)-minor(weekly)*i):weekly
        });
    }
    const bySchedule=(a,b)=>a.due.localeCompare(b.due)||a.k-b.k;
    const schedule=[...kept,...changed].sort(bySchedule);
    const deferred=kept.filter(row=>!paid[row.k]&&deadline(d,row)>=date);
    const ending=[...deferred,...changed].sort(bySchedule).slice(-2);
    const previous=ending.at(-2)?.due??null,final=ending.at(-1);
    return {schedule,balance,count,pay:weekly,asOf:date,first:firstDue,firstAmount:changed[0].amt,last:final.due,
        lastAmount:final.amt,previous,gap:previous?diff(final.due,previous):null,step,before:future,after:changed,
        beforeEnding:[...deferred,...future].sort(bySchedule).slice(-2),afterEnding:ending,
        keptOverdue:kept.filter(row=>!paid[row.k]&&deadline(d,row)<date).reduce((sum,row)=>sum+row.amt,0),
        keptDeferred:deferred.reduce((sum,row)=>sum+row.amt,0),debt:dstat(d,date)?.total||0};
}
function completedDate(deal){
    if(deal.payoff?.date)return deal.payoff.date;
    if(deal.lease)return null;
    if(deal.completed_at)return deal.completed_at;
    if(deal.status!=='archived'&&(deal.status!=='active'||unpaid(deal).length||deal.debt?.amt>0))return null;
    const dates=[...Object.values(deal.paid||{}),...(deal.dpays||[]),...(deal.early||[])].map(p=>p.date);
    if(deal.down)dates.push(deal.start);
    return dates.filter(Boolean).sort().at(-1)||deal.closed||null;
}
function monthlyBuyouts(deals,year,now=today()){
    const records=deals.filter(d=>d.start).map(deal=>{
        const completed=completedDate(deal);
        const closed=deal.status==='active'?null:deal.closed||deal.signed_at?.slice(0,10)||completed||deal.start;
        return {start:deal.start,completed,closed,returned:deal.status==='seized'?deal.closed:null};
    });
    return Array.from({length:12},(_,index)=>{
        const prefix=year+'-'+String(index+1).padStart(2,'0');
        const end=new Date(Date.UTC(year,index+1,0)).toISOString().slice(0,10);
        const cutoff=end<now?end:now;
        const row={month:index+1,issued:0,completed:0,active:prefix<=now.slice(0,7)?0:null,returned:0};
        for(const record of records){
            if(record.start>cutoff)continue;
            for(const [key,date] of [['issued',record.start],['completed',record.completed],['returned',record.returned]]){
                if(date?.startsWith(prefix)&&date<=cutoff)row[key]++;
            }
            if(row.active!==null&&(!record.completed||record.completed>cutoff)&&(!record.closed||record.closed>cutoff))row.active++;
        }
        return row;
    });
}
function buyoutTimings(deals,year,now=today()){
    const rows=[
        {label:'5–8',through:8},{label:'9–12',through:12},{label:'13–16',through:16},
        {label:'17–20',through:20},{label:'21–26',through:26},{label:'27+',through:Infinity}
    ].map(row=>({...row,count:0,total:0}));
    let count=0,withoutBalance=0;
    for(const deal of deals){
        const payment=deal.payoff;
        if(!deal.lease||!payment?.date?.startsWith(year+'-')||payment.date>now)continue;
        const week=Math.floor(diff(payment.date,deal.start)/7)+1;
        if(!Number.isFinite(week)||week<5)continue;
        if(payment.amt===0){withoutBalance++;continue}
        if(!(payment.amt>0))continue;
        const row=rows.find(row=>week<=row.through);
        row.count++;row.total+=minor(payment.amt);count++;
    }
    return {count,withoutBalance,rows:rows.map(row=>({label:row.label,count:row.count,
        share:count?row.count/count:0,average:row.count?money(Math.round(row.total/row.count)):null}))};
}
const C={MK,BIKE_MODELS,BATTERY_COUNTS,WEEKLY_TERMS,RENTAL_WEEKS,ADVANCES,CLIENT_PAYMENT_MAX_PERIODS,tariffKey,calc,buyoutQuote,receiptCharges,buyoutForecast,weeklyProfit,
    rentalKey,rentalPrice,rentalForecast,rentalPaidAmounts,rentalBalance,rentalBuyoutProgress,rentalPayoff,sched,deadline,unpaid,penalty,pdays,nopen,installmentPenaltyBase,installmentCharges,penaltyDetail,dstat,
    LATE_FEE_AMOUNT,LATE_FEE_DAY,UNPAID_PENALTY_DAY,PARTIAL_GRACE_DAYS,partialPaymentDeadline,
    paymentQuote,changeable,scheduleBounds,replan,monthlyBuyouts,buyoutTimings,add,diff,today,minor,money};
if(typeof module!='undefined')module.exports=C;else g.C=C;
})(this);
