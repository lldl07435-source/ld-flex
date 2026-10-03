'use strict';
const $ = id => document.getElementById(id);
let token = '', noticeTimer, replay = [], lastBatch = '', activePage = 'live', hardwareAllowed = false, online = false;
const titles = {live:'实时工作台',research:'调度对照实验',records:'运行记录与重放',hardware:'实物连接',guide:'接线与起步'};
const stateNames = {LOCKED:'上电锁定',IDLE:'等待任务',ALIGN:'对准出口',RELEASE:'开闸放料',TRANSIT:'等待通过',SETTLE:'确认清空',DONE:'已确认完成',FAULT:'故障锁定'};
const faultNames = {NONE:'反馈正常',ESTOP:'急停触发',LINK_LOST:'主机失联',TIMEOUT:'通行超时',WRONG_EXIT:'出口错误',NO_ENTRY:'入口漏检',EXTRA_ITEM:'额外物料',STOPPED:'已停止'};
const metricNames = {weighted_tardiness:'加权迟交',makespan_s:'完工时间',on_time_rate:'准时率',switches:'换向次数'};
function notice(message) { $('notice').textContent=message; $('notice').hidden=false; clearTimeout(noticeTimer); noticeTimer=setTimeout(()=>$('notice').hidden=true,8500); }
async function api(path, body) {
  const options = body === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':token},body:JSON.stringify(body)};
  const response=await fetch(path, options); const data=await response.json(); if(!response.ok) throw new Error(data.error || response.statusText);return data;
}
function bind(id, action) { $(id).addEventListener('click',async()=>{try {await action();}catch(e){notice(e.message);}}); }
function cells(row, values) { for(const value of values){const td=document.createElement('td');td.textContent=String(value);row.append(td);}return row; }
function table(id, rows) { $(id).replaceChildren(...rows.map(values=>cells(document.createElement('tr'),values))); }
function number(id) { const n=Number($(id).value); if(!Number.isInteger(n)) throw new Error('请输入整数参数');return n; }
document.querySelectorAll('.nav').forEach(button=>button.addEventListener('click',()=>{
  activePage=button.dataset.page;
  document.querySelectorAll('.nav').forEach(b=>b.classList.toggle('active',b===button));
  document.querySelectorAll('.page').forEach(p=>p.classList.toggle('active',p.id===activePage));
  $('page-title').textContent=titles[activePage];
  if(activePage==='records') loadHistory().catch(e=>notice(e.message));
}));
bind('start',async()=>{await api('/api/start',{seed:number('seed'),count:number('count'),policy:$('policy').value,scenario:$('scenario').value,speed:number('speed')});await openClassicTwin();});
bind('stop',()=>api('/api/stop',{}));
bind('recover',()=>api('/api/recover',{confirmed:true}));
bind('benchmark',()=>api('/api/benchmark',{seeds:number('batch-seeds'),count:number('batch-count')}));
bind('refresh-history',loadHistory);
bind('scan-ports',loadPorts);
bind('connect',()=>api('/api/connect',{port:$('port').value}));
bind('disconnect',()=>api('/api/disconnect',{}));
bind('arm',async()=>{await api('/api/arm',{confirmed:$('clear-confirm').checked});$('clear-confirm').checked=false;});
bind('run-one',()=>api('/api/run_one',{order_id:$('order-id').value,route:number('hw-route')}));
bind('hw-stop',()=>api('/api/hw_stop',{}));
async function loadPorts(){const ports=await api('/api/ports');$('port').replaceChildren();for(const p of ports){const o=document.createElement('option');o.value=p.port;o.textContent=p.port+' · '+p.description+(p.bluetooth?'（蓝牙串口，请核对设备）':'');$('port').append(o);}if(!ports.length){const o=document.createElement('option');o.value='';o.textContent=hardwareAllowed?'未检测到串口，请连接 USB-TTL':'此账户无法使用实物连接';$('port').append(o);}}
async function loadHistory(){
  const records=await api('/api/history');$('history-rows').replaceChildren();
  for(const r of records){const s=r.summary;const row=cells(document.createElement('tr'),[r.started_at,(r.mode==='hardware'?'实物':'仿真')+' / '+(s.scenario||'—'),r.status,(s.completed??'—')+' / '+(s.unknown??'—')]);
    const td=document.createElement('td');const replayButton=document.createElement('button');replayButton.className='action-link';replayButton.textContent='重放 / 校验';replayButton.onclick=()=>loadReplay(r.id).catch(e=>notice(e.message));td.append(replayButton);
    if(r.status!=='running'&&r.status!=='interrupted'){const link=document.createElement('a');link.textContent='导出 ZIP';link.href='/api/export?id='+encodeURIComponent(r.id);link.download=r.id+'.zip';link.className='action-link';td.append(link);}row.append(td);$('history-rows').append(row);
  }
  if(!records.length)table('history-rows',[['尚无运行记录。开始一次仿真后刷新。','','','','']]);
}
async function loadReplay(id){const data=await api('/api/run?id='+encodeURIComponent(id));replay=data.events;$('replay-panel').hidden=false;$('replay-id').textContent=id;$('verify-result').textContent=data.verification.ok?'摘要与事件链一致':'未封存或校验未通过';$('replay-slider').max=Math.max(0,replay.length-1);$('replay-slider').value=0;showReplay();$('replay-panel').scrollIntoView({behavior:'smooth',block:'nearest'});}
function showReplay(){const event=replay[Number($('replay-slider').value)];$('replay-event').textContent=JSON.stringify(event,null,2);}
$('replay-slider').addEventListener('input',showReplay);
function render(s){
  const sim=s.simulation;const running=sim&&sim.status==='running';$('start').disabled=!!running;$('stop').disabled=!running;
  if(sim){const m=sim.summary,c=sim.controller;$('completed').textContent=m.completed+' / '+m.total+' 件';$('unknown').textContent=m.unknown+' 件';$('virtual-time').textContent=sim.virtual_s.toFixed(2)+' s';$('tardiness').textContent=m.weighted_tardiness.toFixed(1)+' s';$('switches').textContent='换向 '+m.switches+' 次';$('run-state').textContent=sim.status==='completed'?'本轮结束':sim.status==='stopped'?'已停止':'运行中';$('cell-state').textContent=stateNames[c.state]+' · '+c.state;$('current-item').textContent=sim.current?'#'+sim.current.id+' → '+(sim.current.route?'B':'A'):'—';$('gate-status').textContent=c.gate?'打开':'关闭';$('fault-label').textContent=faultNames[c.fault];$('recovery-box').hidden=!sim.awaiting_recovery;$('run-id').textContent=s.run_id;
    $('route-line').setAttribute('d',c.route?'M350 40 L350 145 L515 254':'M350 40 L350 145 L185 254');$('gate-shape').setAttribute('width',c.gate?'20':'68');$('gate-shape').setAttribute('fill',c.gate?'#23a089':'#243f4c');$('item-dot').setAttribute('visibility',sim.current?'visible':'hidden');$('item-dot').setAttribute('cy',c.state==='ALIGN'?'44':c.state==='RELEASE'?'97':'145');
    [['sensor-in',1],['sensor-left',2],['sensor-right',4]].forEach(([id,bit])=>$(id).classList.toggle('on',!!(sim.inputs&bit)));
    table('job-rows',sim.results.slice(-10).reverse().map(r=>['#'+r.order_id,r.route?'B 路':'A 路',r.outcome==='completed'?'确认完成':'需要核实',r.started.toFixed(2),r.finished.toFixed(2),typeof r.tardiness==='number'?r.tardiness.toFixed(2):'—']));
    $('timeline').replaceChildren(...sim.results.map(r=>{const el=document.createElement('span');el.className='task-chip'+(r.outcome==='unknown'?' unknown':'');el.textContent='#'+r.order_id+' '+(r.route?'B':'A');el.title=r.started+' s → '+r.finished+' s';return el;}));
  }
  const batch=s.batch;$('benchmark').disabled=batch.running;$('batch-progress').textContent=batch.running?'已完成 '+batch.done+' / '+batch.total+' 次':batch.error|| (batch.done?'实验完成 · '+batch.done+' 次':(online?'10 组 × 4 策略 = 40 次运行':'20 组 × 4 策略 = 80 次运行'));
  if(batch.result && lastBatch!==batch.result.folder){lastBatch=batch.result.folder;const r=batch.result.report;table('averages',r.policies.map(p=>{const m=r.averages[p];return [p,m.weighted_tardiness.toFixed(2),m.makespan_s.toFixed(2),(m.on_time_rate*100).toFixed(1)+'%',m.switches.toFixed(1)];}));table('intervals',r.paired_comparisons.map(c=>[c.contrast,metricNames[c.metric],c.mean_difference.toFixed(3),'['+c.ci95.map(x=>x.toFixed(3)).join(', ')+']']));$('batch-folder').textContent='报告已保存：'+batch.result.folder;}
  const hw=s.hardware, connected=hardwareAllowed&&!!hw?.connected;
  const device=hw?.device||{}; $('hw-control').textContent=connected?(stateNames[device.state_name]||device.state_name||'等待反馈'):'未连接'; $('hw-session').textContent=hw?.armed?'已确认':'未建立'; $('hw-rtt').textContent=typeof hw?.round_trip_ms==='number'?hw.round_trip_ms.toFixed(1)+' ms':'—'; $('hw-age').textContent=typeof hw?.feedback_age_ms==='number'?hw.feedback_age_ms.toFixed(0)+' ms':'—'; [['hw-in',1],['hw-a',2],['hw-b',4]].forEach(([id,bit])=>$(id).textContent=connected?(device.inputs&bit?'已触发':'未触发'):'—'); $('hw-counts').textContent=(device.completed||0)+' / '+(hw?.unknown_count||0); table('hw-results',(hw?.results||[]).slice().reverse().map(row=>[row.order_id,row.route?'B 路':'A 路',row.outcome==='completed'?'确认完成':'待核实',typeof row.cycle_s==='number'?row.cycle_s.toFixed(3):'—']));
  $('arm').disabled=!connected||!!hw?.current;
  $('hw-stop').disabled=!connected;$('disconnect').disabled=!connected;
  $('connect').disabled=!hardwareAllowed||connected||!$('port').value;
  $('scan-ports').disabled=!hardwareAllowed;$('clear-confirm').disabled=!connected;
  $('run-one').disabled=!connected||!hw?.armed||!!hw?.current;
  $('hardware-state').textContent=hw?JSON.stringify(hw,null,2):(hardwareAllowed?'尚未连接。请连接 STM32 的 USB-TTL 串口后点击连接；蓝牙 COM 口通常不是这块控制板。':online?'在线工作台支持仿真。实物连接请在设备所在电脑的本地工作台使用。':'实物操作需先在本机授予此账户操作权限，步骤见多用户使用与部署说明。');
  if(s.error)notice(s.error);
}
async function poll(){try{const state=await api('/api/state');render(state);$('connection').textContent=online?'服务在线':'本地服务在线';}catch(e){$('connection').textContent='服务未连接';}finally{setTimeout(poll,750);}}
api('/api/config').then(config=>{token=config.token;hardwareAllowed=config.hardware_allowed;online=config.mode==='cloud';if(online){$('batch-seeds').value='10';$('batch-seeds').max='10';$('batch-count').max='40';}$('run-environment').textContent=(online?'在线工作区':'本机工作区')+' · V'+config.version;$('data-location').textContent='数据保存到当前账户';loadPorts().catch(e=>notice(e.message));poll();}).catch(e=>notice('无法连接服务：'+e.message));

window.addEventListener('load',()=>{const id=location.hash.slice(1);const button=document.querySelector('[data-page=\"'+id+'\"]');if(button)button.click();});

let ldClassicTwin,ldClassicTwinPoll;
async function openClassicTwin(runId){
  let host=document.getElementById('classic-twin');
  if(!host){host=document.createElement('section');host.id='classic-twin';const parent=document.getElementById('ld'==='ld'?'live':'flight');parent.prepend(host);}
  const {TwinPlayer}=await import('/twin-viewer.js');
  ldClassicTwin?.dispose();clearInterval(ldClassicTwinPoll);ldClassicTwin=new TwinPlayer(host,{domain:'ld'});
  if(runId)await ldClassicTwin.load(runId);else{await ldClassicTwin.live();ldClassicTwinPoll=setInterval(()=>ldClassicTwin.live(),160);}
  host.scrollIntoView({block:'start',behavior:'smooth'});
}
window.addEventListener('pagehide',()=>{ldClassicTwin?.dispose();clearInterval(ldClassicTwinPoll);});
