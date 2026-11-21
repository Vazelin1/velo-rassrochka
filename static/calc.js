(function(g){
const MK={w:{8:30,12:42,16:55,20:68,26:88},m:{2:30,3:42,4:55,5:68,6:88}},DS={30000:2,50000:4};
const BIKE_MODELS={monster:'Монстр',u2:'U2',u2pro:'U2 Pro'};
const BATTERY_COUNTS=[1,2];
const WEEKLY_TERMS=[8,12,16,20,26];
const ADVANCES=[10000,20000,30000,40000,50000];
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
function sched(d){
    const paid=d.paid||{},step=d.type=='m'?30:7;
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
function unpaid(d,rows=sched(d)){
    if(d.payoff)return [];
    return rows.filter(row=>!d.paid?.[row.k]).sort((a,b)=>deadline(d,a).localeCompare(deadline(d,b)));
}
const penalty=(a,days,r)=>Math.round(a*Math.max(0,r==null?0.9:r)/100*days);
/* Days of penalty from the last day without penalty b up to date T.
   d.pw: penalty written off on that date (counting starts again from it); d.np: [[from,to|null],...] periods when accrual is switched off:
   the days from `from` up to (not including) `to` are not counted. */
function pdays(b,T,d){d=d||{};if(d.pw&&d.pw>b)b=d.pw;let n=diff(T,b);if(n<=0)return 0;
(d.np||[]).forEach(f=>{const a1=add(b,1),lo=a1>f[0]?a1:f[0],e=f[1]?add(f[1],-1):T,hi=e<T?e:T,o=diff(hi,lo)+1;if(o>0)n-=o});return Math.max(0,n)}
const nopen=d=>((d&&d.np)||[]).some(f=>!f[1]);
function penaltyDetail(amount,limit,date,d){
    const rate=Math.max(0,d.pen??0.9),days=pdays(limit,date,d),base=d.pw>limit?d.pw:limit;
    let start=add(base,1);
    for(const [from,to] of [...(d.np||[])].sort((a,b)=>a[0].localeCompare(b[0]))){
        if(start&&from<=start&&(!to||to>start))start=to;
    }
    return {amount,limit,rate,start,days,total:penalty(amount,days,rate)};
}
/* Debt left after a partial payment of a period: {amt, due, pb, k}. Penalty is counted on the remainder after the due date (pb: date the penalty was last paid). */
function dstat(d,T){const g=d&&d.debt;if(d?.payoff||!g||!(g.amt>0))return null;const b=g.pb&&g.pb>g.due?g.pb:g.due,n=pdays(b,T,d),pen=penalty(g.amt,n,d.pen);return{amt:g.amt,due:g.due,k:g.k,days:n,pen,total:money(minor(g.amt)+minor(pen)),late:Math.max(0,diff(T,g.due)),over:T>g.due,base:b}}

function paymentQuote(d,options={},settings={},date=today()){
    const remaining=unpaid(d);
    if(d.status!='active'||!remaining.length)throw Error('Сейчас нечего оплачивать.');
    const minimum=Math.max(50,Math.min(100,settings.dmin??50));
    const mode=options.mode||'periods';
    if(mode=='part'){
        if(dstat(d,date))throw Error('Сначала погасите остаток предыдущего платежа.');
        const row=remaining[0],amount=Number(options.amount),min=Math.ceil(row.amt*minimum/100),max=Math.ceil(row.amt)-1;
        if(!Number.isSafeInteger(amount)||amount<min||amount>max){
            throw Error(min>max?'Этот взнос доступен только целиком.':`Часть платежа должна быть от ${min} до ${max} ₽.`);
        }
        const pen=penalty(row.amt,pdays(deadline(d,row),date,d),d.pen);
        return {mode,date,count:1,items:[{...row,amt:amount,pen}],principal:amount,pen,total:amount+pen,bonus:0,rate:0,reductions:[],rest:money(minor(row.amt)-minor(amount)),debtDue:add(date,settings.dbd??3)};
    }
    if(mode!='periods')throw Error('Выберите способ оплаты.');
    const count=Number(options.count??1);
    if(!Number.isSafeInteger(count)||count<1||count>remaining.length)throw Error('Выберите количество платежей.');
    const selected=remaining.slice(0,count);
    const selectedSum=selected.reduce((sum,row)=>sum+minor(row.amt),0);
    const selectedKeys=new Set(selected.map(row=>row.k));
    const tail=remaining.slice().sort((a,b)=>b.due.localeCompare(a.due)||b.k-a.k);
    const step=remaining.every(row=>Number.isInteger(row.amt))?100:1;
    const rate=count>=2?Number(settings.multi_discount??1.5):0;
    if(!Number.isFinite(rate)||rate<0||rate>100)throw Error('Проверьте ставку скидки.');
    function allocate(cash,selectedLimit){
        let left=Math.round(cash*rate/10000)*100;
        const reductions=[];
        for(const row of tail){
            if(!left)break;
            const selected=selectedKeys.has(row.k);
            const amount=Math.min(left,minor(row.amt),selected?selectedLimit:Infinity);
            if(amount)reductions.push({k:row.k,amt:money(amount)});
            left-=amount;
            if(selected)selectedLimit-=amount;
        }
        return reductions;
    }
    // A deferral can change which periods are paid without changing the order of discounts.
    let lo=0,hi=selectedSum/step;
    while(lo<hi){
        const cash=Math.floor((lo+hi)/2);
        const onSelected=allocate(cash*step,Infinity).reduce((sum,row)=>sum+(selectedKeys.has(row.k)?minor(row.amt):0),0);
        if(cash*step+onSelected>=selectedSum)hi=cash;
        else lo=cash+1;
    }
    const principal=money(lo*step),reductions=allocate(lo*step,selectedSum-lo*step);
    const bonus=money(reductions.reduce((sum,row)=>sum+minor(row.amt),0));
    const items=selected.map(row=>({
        ...row,
        amt:money(minor(row.amt)-minor(reductions.find(reduction=>reduction.k==row.k)?.amt||0)),
        pen:penalty(row.amt,pdays(deadline(d,row),date,d),d.pen)
    }));
    const pen=items.reduce((sum,row)=>sum+row.pen,0);
    return {mode,date,count,items,principal,pen,total:money(minor(principal)+minor(pen)),bonus,rate,reductions,rest:0};
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
const C={MK,BIKE_MODELS,BATTERY_COUNTS,WEEKLY_TERMS,ADVANCES,tariffKey,calc,buyoutQuote,receiptCharges,buyoutForecast,weeklyProfit,sched,deadline,unpaid,penalty,pdays,nopen,penaltyDetail,dstat,paymentQuote,changeable,scheduleBounds,replan,add,diff,today,minor,money};
if(typeof module!='undefined')module.exports=C;else g.C=C;
})(this);
