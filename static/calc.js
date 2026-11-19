(function(g){
const MK={w:{8:30,12:42,16:55,20:68,26:88},m:{2:30,3:42,4:55,5:68,6:88}},DS={30000:2,50000:4};
const up=(x,s)=>Math.ceil(x/s-1e-9)*s;
function add(d,n){const t=new Date(d+'T00:00:00Z');t.setUTCDate(t.getUTCDate()+n);return t.toISOString().slice(0,10)}
const diff=(a,b)=>Math.round((new Date(a)-new Date(b))/864e5);
const today=()=>new Date(Date.now()+108e5).toISOString().slice(0,10);
function calc(o){const mk=((o.mk||MK)[o.type]||{})[o.n]||0,d=o.disc!=null&&o.disc!==''?+o.disc:((o.ds||[[30000,2],[50000,4]]).find(x=>x[0]==o.down)||[0,0])[1],
bike=Math.round(o.cost*(1+(mk-d)/100)),ex=(o.extras||[]).reduce((a,e)=>a+e.price,0),exc=(o.extras||[]).reduce((a,e)=>a+e.cost,0),
total=bike+ex,bal=total-(o.down||0),pay=up(bal/o.n,o.type=='w'?100:1000),last=bal-pay*(o.n-1),
tax=Math.round(total*(o.tax==null?7:o.tax)/100),acq=Math.round(total*(o.acq==null?0:o.acq)/100),receipt=Math.round(total*(o.receipt||0)/100),profit=total-o.cost-exc-tax-acq-receipt;
return{mk,d,bike,total,bal,pay,last,tax,acq,receipt,profit,pct:o.cost?profit/o.cost*100:0}}
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
const penalty=(a,days,r)=>Math.round(a*(r==null?0.9:r)/100*days);
/* Days of penalty from the last day without penalty b up to date T.
   d.pw: penalty written off on that date (counting starts again from it); d.np: [[from,to|null],...] periods when accrual is switched off:
   the days from `from` up to (not including) `to` are not counted. */
function pdays(b,T,d){d=d||{};if(d.pw&&d.pw>b)b=d.pw;let n=diff(T,b);if(n<=0)return 0;
(d.np||[]).forEach(f=>{const a1=add(b,1),lo=a1>f[0]?a1:f[0],e=f[1]?add(f[1],-1):T,hi=e<T?e:T,o=diff(hi,lo)+1;if(o>0)n-=o});return Math.max(0,n)}
const nopen=d=>((d&&d.np)||[]).some(f=>!f[1]);
/* Debt left after a partial payment of a period: {amt, due, pb, k}. Penalty is counted on the remainder after the due date (pb: date the penalty was last paid). */
function dstat(d,T){const g=d&&d.debt;if(!g||!(g.amt>0))return null;const b=g.pb&&g.pb>g.due?g.pb:g.due,n=pdays(b,T,d),pen=penalty(g.amt,n,d.pen);return{amt:g.amt,due:g.due,k:g.k,days:n,pen,total:g.amt+pen,late:Math.max(0,diff(T,g.due)),over:T>g.due,base:b}}

function paymentQuote(d,options={},settings={},date=today()){
    const unpaid=sched(d).filter(row=>!(d.paid||{})[row.k]);
    if(d.status!='active'||!unpaid.length)throw Error('Сейчас нечего оплачивать.');
    const minimum=Math.max(50,Math.min(100,settings.dmin??50));
    const mode=options.mode||'periods';
    if(mode=='part'){
        if(dstat(d,date))throw Error('Сначала погасите остаток предыдущего платежа.');
        const row=unpaid[0],amount=Number(options.amount),min=Math.ceil(row.amt*minimum/100);
        if(!Number.isSafeInteger(amount)||amount<min||amount>=row.amt){
            throw Error(`Часть платежа должна быть от ${min} до ${row.amt-1} ₽.`);
        }
        const pen=penalty(row.amt,pdays(row.due,date,d),d.pen);
        return {mode,date,count:1,items:[{...row,amt:amount,pen}],principal:amount,pen,total:amount+pen,bonus:0,rate:0,reductions:[],rest:row.amt-amount,debtDue:add(date,settings.dbd??3)};
    }
    if(mode!='periods')throw Error('Выберите способ оплаты.');
    const count=Number(options.count??1);
    if(!Number.isSafeInteger(count)||count<1||count>unpaid.length)throw Error('Выберите количество платежей.');
    const selected=unpaid.slice(0,count);
    const selectedSum=selected.reduce((sum,row)=>sum+row.amt,0);
    const future=unpaid.slice(count).reduce((sum,row)=>sum+row.amt,0);
    const rate=count>=2?Number(settings.multi_discount??1.5):0;
    if(!Number.isFinite(rate)||rate<0||rate>100)throw Error('Проверьте ставку скидки.');
    // If the discount reaches a selected final payment, reduce the cash due too.
    let lo=0,hi=selectedSum;
    while(lo<hi){
        const cash=Math.floor((lo+hi)/2);
        if(cash+Math.max(0,Math.round(cash*rate/100)-future)>=selectedSum)hi=cash;
        else lo=cash+1;
    }
    const principal=lo,bonus=Math.min(Math.round(principal*rate/100),selectedSum+future-principal);
    const reductions=[];
    let left=bonus;
    for(let i=unpaid.length-1;i>=0&&left>0;i--){
        const amount=Math.min(left,unpaid[i].amt);
        reductions.push({k:unpaid[i].k,amt:amount});
        left-=amount;
    }
    const items=selected.map(row=>({
        ...row,
        amt:row.amt-(reductions.find(reduction=>reduction.k==row.k)?.amt||0),
        pen:penalty(row.amt,pdays(row.due,date,d),d.pen)
    }));
    const pen=items.reduce((sum,row)=>sum+row.pen,0);
    return {mode,date,count,items,principal,pen,total:principal+pen,bonus,rate,reductions,rest:0};
}

function replan(d,firstDue,weekly,date=today()){
    if(!/^\d{4}-\d{2}-\d{2}$/.test(firstDue)||add(firstDue,0)!=firstDue||firstDue<date){
        throw Error('Выберите дату следующего платежа начиная с сегодняшнего дня.');
    }
    weekly=Number(weekly);
    if(!Number.isSafeInteger(weekly)||weekly<1)throw Error('Введите сумму платежа в целых рублях.');
    const current=sched(d),paid=d.paid||{};
    const future=current.filter(row=>!paid[row.k]&&row.due>=date);
    const kept=current.filter(row=>paid[row.k]||row.due<date);
    const balance=future.reduce((sum,row)=>sum+row.amt,0);
    if(!balance)throw Error('В графике нет будущих платежей для перерасчёта.');
    const count=Math.ceil(balance/weekly),step=d.type=='m'?30:7;
    if(count>5200)throw Error('Получается слишком длинный график. Увеличьте сумму платежа.');
    let maxKey=Math.max(d.n||0,...current.map(row=>row.k)),left=balance;
    const changed=[];
    for(let i=0;i<count;i++){
        const amount=Math.min(weekly,left);
        changed.push({k:future[i]?.k||++maxKey,due:add(firstDue,step*i),amt:amount});
        left-=amount;
    }
    const schedule=[...kept,...changed].sort((a,b)=>a.due.localeCompare(b.due)||a.k-b.k);
    return {schedule,balance,count,pay:weekly,first:firstDue,last:changed[changed.length-1].due,lastAmount:changed[changed.length-1].amt,keptOverdue:kept.filter(row=>!paid[row.k]).reduce((sum,row)=>sum+row.amt,0),debt:dstat(d,date)?.total||0};
}
const C={MK,calc,sched,penalty,pdays,nopen,dstat,paymentQuote,replan,add,diff,today};
if(typeof module!='undefined')module.exports=C;else g.C=C;
})(this);
