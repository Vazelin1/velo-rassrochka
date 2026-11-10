(function(g){
const MK={w:{8:30,12:42,16:55,20:68,26:88},m:{2:30,3:42,4:55,5:68,6:88}},DS={30000:2,50000:4};
const up=(x,s)=>Math.ceil(x/s-1e-9)*s;
function add(d,n){const t=new Date(d+'T00:00:00Z');t.setUTCDate(t.getUTCDate()+n);return t.toISOString().slice(0,10)}
const diff=(a,b)=>Math.round((new Date(a)-new Date(b))/864e5);
const today=()=>new Date(Date.now()+108e5).toISOString().slice(0,10);
function calc(o){const mk=((o.mk||MK)[o.type]||{})[o.n]||0,d=o.disc!=null&&o.disc!==''?+o.disc:((o.ds||[[30000,2],[50000,4]]).find(x=>x[0]==o.down)||[0,0])[1],
bike=Math.round(o.cost*(1+(mk-d)/100)),ex=(o.extras||[]).reduce((a,e)=>a+e.price,0),exc=(o.extras||[]).reduce((a,e)=>a+e.cost,0),
total=bike+ex,bal=total-(o.down||0),pay=up(bal/o.n,o.type=='w'?100:1000),last=bal-pay*(o.n-1),
tax=Math.round(total*(o.tax==null?7:o.tax)/100),profit=total-o.cost-exc-tax;
return{mk,d,bike,total,bal,pay,last,tax,profit,pct:o.cost?profit/o.cost*100:0}}
function sched(d){const P=d.type=='m'?30:7,r=[];for(let k=1;k<=d.n;k++)r.push({k,due:k==1?d.start:add(d.start,P*(k-1)-1),amt:k==d.n?d.last:d.pay});
let e=(d.early||[]).reduce((a,x)=>a+x.amt,0);for(let i=r.length-1;i>=0&&e>0;i--){if(d.paid[r[i].k])break;const c=Math.min(e,r[i].amt);r[i].amt-=c;e-=c}
return r.filter(x=>x.amt>0||d.paid[x.k])}
const penalty=(a,days,r)=>Math.round(a*(r==null?0.9:r)/100*days);
const C={MK,calc,sched,penalty,add,diff,today};
if(typeof module!='undefined')module.exports=C;else g.C=C;
})(this);
