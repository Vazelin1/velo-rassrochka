(function(g){
const MK={w:{8:30,12:42,16:55,20:68,26:88},m:{2:30,3:42,4:55,5:68,6:88}},DS={30000:2,50000:4};
const up=(x,s)=>Math.ceil(x/s-1e-9)*s;
function add(d,n){const t=new Date(d+'T00:00:00Z');t.setUTCDate(t.getUTCDate()+n);return t.toISOString().slice(0,10)}
const diff=(a,b)=>Math.round((new Date(a)-new Date(b))/864e5);
const today=()=>new Date(Date.now()+108e5).toISOString().slice(0,10);
function calc(o){const mk=((o.mk||MK)[o.type]||{})[o.n]||0,d=o.disc!=null&&o.disc!==''?+o.disc:((o.ds||[[30000,2],[50000,4]]).find(x=>x[0]==o.down)||[0,0])[1],
bike=Math.round(o.cost*(1+(mk-d)/100)),ex=(o.extras||[]).reduce((a,e)=>a+e.price,0),exc=(o.extras||[]).reduce((a,e)=>a+e.cost,0),
total=bike+ex,bal=total-(o.down||0),pay=up(bal/o.n,o.type=='w'?100:1000),last=bal-pay*(o.n-1),
tax=Math.round(total*(o.tax==null?7:o.tax)/100),acq=Math.round(total*(o.acq==null?0:o.acq)/100),profit=total-o.cost-exc-tax-acq;
return{mk,d,bike,total,bal,pay,last,tax,acq,profit,pct:o.cost?profit/o.cost*100:0}}
function sched(d){d.paid=d.paid||{};const P=d.type=='m'?30:7,r=[];for(let k=1;k<=d.n;k++)r.push({k,due:k==1?d.start:add(d.start,P*(k-1)-1+(d.paid[k]?0:(d.shift||0))),amt:k==d.n?d.last:d.pay});
let e=(d.early||[]).reduce((a,x)=>a+x.amt,0);for(let i=r.length-1;i>=0&&e>0;i--){if(d.paid[r[i].k])break;const c=Math.min(e,r[i].amt);r[i].amt-=c;e-=c}
return r.filter(x=>x.amt>0||d.paid[x.k])}
const penalty=(a,days,r)=>Math.round(a*(r==null?0.9:r)/100*days);
/* Days of penalty from the last day without penalty b up to date T.
   d.pw: penalty written off on that date (counting starts again from it); d.np: [[from,to|null],...] periods when accrual is switched off:
   the days from `from` up to (not including) `to` are not counted. */
function pdays(b,T,d){d=d||{};if(d.pw&&d.pw>b)b=d.pw;let n=diff(T,b);if(n<=0)return 0;
(d.np||[]).forEach(f=>{const a1=add(b,1),lo=a1>f[0]?a1:f[0],e=f[1]?add(f[1],-1):T,hi=e<T?e:T,o=diff(hi,lo)+1;if(o>0)n-=o});return Math.max(0,n)}
const nopen=d=>((d&&d.np)||[]).some(f=>!f[1]);
/* Debt left after a partial payment of a period: {amt, due, pb, k}. Penalty is counted on the remainder after the due date (pb: date the penalty was last paid). */
function dstat(d,T){const g=d&&d.debt;if(!g||!(g.amt>0))return null;const b=g.pb&&g.pb>g.due?g.pb:g.due,n=pdays(b,T,d),pen=penalty(g.amt,n,d.pen);return{amt:g.amt,due:g.due,k:g.k,days:n,pen,total:g.amt+pen,late:Math.max(0,diff(T,g.due)),over:T>g.due,base:b}}
const C={MK,calc,sched,penalty,pdays,nopen,dstat,add,diff,today};
if(typeof module!='undefined')module.exports=C;else g.C=C;
})(this);
