const C=require('./static/calc.js');const t=(o,e)=>{const r=C.calc(o);for(const k in e)if(r[k]!==e[k])throw Error(JSON.stringify([o,k,r[k],e[k]]))};
t({cost:60000,type:'w',n:16,down:0},{total:93000,pay:5900,last:4500,tax:6510,profit:26490});
t({cost:60000,type:'w',n:16,down:30000},{total:91800,bal:61800,pay:3900,last:3300,profit:25374});
t({cost:60000,type:'m',n:3,down:0},{total:85200,pay:29000,last:27200,profit:19236});
t({cost:60000,type:'w',n:8,down:0},{total:78000,pay:9800,last:9400,profit:12540});
t({cost:60000,type:'w',n:16,down:0,acq:1.5},{total:93000,tax:6510,acq:1395,profit:25095});
t({cost:60000,type:'w',n:16,down:0,acq:0},{acq:0,profit:26490});
if(C.penalty(5900,3)!==159)throw 1;
const s=C.sched({type:'w',n:3,start:'2026-11-01',pay:1,last:1});if(s[1].due!='2026-11-07'||s[2].due!='2026-11-14')throw 2;
/* pdays / dstat: penalty days, waiver, freeze */
if(C.pdays('2026-11-10','2026-11-10')!==0||C.pdays('2026-11-10','2026-11-13')!==3)throw 3;
if(C.pdays('2026-11-10','2026-11-13',{pw:'2026-11-12'})!==1)throw 4;
if(C.pdays('2026-11-10','2026-11-13',{pw:'2026-11-20'})!==0)throw 5;
if(C.pdays('2026-11-10','2026-11-15',{np:[['2026-11-12','2026-11-14']]})!==3)throw 6;
if(C.pdays('2026-11-10','2026-11-15',{np:[['2026-11-12',null]]})!==1)throw 7;
if(C.pdays('2026-11-10','2026-11-15',{np:[['2026-11-01','2026-11-12']]})!==4)throw 8;
if(!C.nopen({np:[['2026-11-12',null]]})||C.nopen({np:[['2026-11-12','2026-11-13']]})||C.nopen({}))throw 9;
let g=C.dstat({debt:{amt:2950,due:'2026-11-10',k:1}},'2026-11-10');if(g.pen!==0||g.over||g.days!==0||g.total!==2950)throw Error('d1'+JSON.stringify(g));
g=C.dstat({debt:{amt:2950,due:'2026-11-10',k:1}},'2026-11-13');if(g.days!==3||g.pen!==80||g.total!==3030||!g.over||g.late!==3)throw Error('d2'+JSON.stringify(g));
g=C.dstat({debt:{amt:2950,due:'2026-11-10',k:1},pen:1},'2026-11-13');if(g.pen!==89)throw Error('d3'+JSON.stringify(g));
g=C.dstat({debt:{amt:2950,due:'2026-11-10',k:1},pw:'2026-11-12'},'2026-11-13');if(g.days!==1||g.pen!==27)throw Error('d4'+JSON.stringify(g));
g=C.dstat({debt:{amt:2950,due:'2026-11-10',pb:'2026-11-12',k:1}},'2026-11-13');if(g.days!==1)throw Error('d5'+JSON.stringify(g));
if(C.dstat({},'2026-11-13')!==null||C.dstat({debt:{amt:0,due:'2026-11-10'}},'2026-11-13')!==null)throw 10;
console.log('ok')
