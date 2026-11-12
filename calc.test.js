const C=require('./static/calc.js');const t=(o,e)=>{const r=C.calc(o);for(const k in e)if(r[k]!==e[k])throw Error(JSON.stringify([o,k,r[k],e[k]]))};
t({cost:60000,type:'w',n:16,down:0},{total:93000,pay:5900,last:4500,tax:6510,profit:26490});
t({cost:60000,type:'w',n:16,down:30000},{total:91800,bal:61800,pay:3900,last:3300,profit:25374});
t({cost:60000,type:'m',n:3,down:0},{total:85200,pay:29000,last:27200,profit:19236});
t({cost:60000,type:'w',n:8,down:0},{total:78000,pay:9800,last:9400,profit:12540});
t({cost:60000,type:'w',n:16,down:0,acq:1.5},{total:93000,tax:6510,acq:1395,profit:25095});
t({cost:60000,type:'w',n:16,down:0,acq:0},{acq:0,profit:26490});
if(C.penalty(5900,3)!==159)throw 1;
const s=C.sched({type:'w',n:3,start:'2026-11-01',pay:1,last:1});if(s[1].due!='2026-11-07'||s[2].due!='2026-11-14')throw 2;
console.log('ok')
