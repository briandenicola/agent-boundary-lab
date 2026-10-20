"""The harness chat page: one self-contained HTML document.

Everything model- or tool-derived is rendered with textContent, never innerHTML.
"""

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Harness chat</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root{color-scheme:light dark;
  --bg:#f5f6fa;--panel:#fff;--panel2:#f0f2f8;--text:#1c2033;--muted:#667;--line:#dfe3ee;
  --accent:#4f6df5;--accent-fg:#fff;--ok:#12805c;--ok-bg:#dcf5ea;--bad:#c0322b;--bad-bg:#fde4e2;
  --warn:#8a5a00;--warn-bg:#fff1cc;--code:#f3f4f9;--shadow:0 1px 2px #0001,0 8px 24px #0000000d}
@media (prefers-color-scheme:dark){:root{
  --bg:#0e1118;--panel:#161b26;--panel2:#1d2331;--text:#e6e9f2;--muted:#8d95ab;--line:#262d3d;
  --accent:#7b93ff;--accent-fg:#0e1118;--ok:#4cd9a1;--ok-bg:#12322a;--bad:#ff8078;--bad-bg:#3a1a1a;
  --warn:#f5c869;--warn-bg:#33290f;--code:#0f131c;--shadow:0 1px 2px #0006,0 8px 24px #0004}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
  font:15px/1.55 Inter,system-ui,-apple-system,"Segoe UI",sans-serif}
header{position:sticky;top:0;z-index:5;display:flex;flex-wrap:wrap;gap:.75rem;align-items:center;
  padding:.8rem 1.5rem;background:var(--panel);border-bottom:1px solid var(--line)}
header h1{font-size:1.05rem;margin:0 .5rem 0 0;font-weight:700;letter-spacing:-.01em}
.chip{display:inline-flex;gap:.4rem;align-items:center;padding:.2rem .65rem;border-radius:99px;
  background:var(--panel2);border:1px solid var(--line);font-size:.78rem;color:var(--muted)}
.chip b{color:var(--text);font-weight:600}
.chip.warn{background:var(--warn-bg);color:var(--warn);border-color:transparent}
main{max-width:64rem;margin:0 auto;padding:1.5rem;display:grid;gap:1.25rem}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow);
  padding:1.1rem 1.25rem}
.card h2{margin:0 0 .6rem;font-size:.8rem;text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}
.notice{border-left:4px solid var(--warn);background:var(--warn-bg);color:var(--text);
  border-radius:10px;padding:.8rem 1rem;font-size:.9rem}
textarea,input[type=text]{width:100%;padding:.75rem .9rem;border-radius:10px;
  border:1px solid var(--line);background:var(--code);color:var(--text);font:inherit}
textarea{min-height:5.5rem;resize:vertical}
input[type=text]{margin:.3rem 0 .8rem}
textarea:focus,input[type=text]:focus{outline:2px solid var(--accent);outline-offset:1px}
label{font-size:.82rem;color:var(--muted)}
.row{display:flex;gap:1rem;align-items:center;margin-top:.8rem;flex-wrap:wrap}
button{font:inherit;font-weight:600;cursor:pointer;border:0;border-radius:10px;padding:.55rem 1.2rem;
  background:var(--accent);color:var(--accent-fg)}
button:hover{filter:brightness(1.08)}button:disabled{opacity:.55;cursor:wait}
button.ghost{background:var(--panel2);color:var(--text);border:1px solid var(--line);
  padding:.15rem .6rem;font-size:.75rem;font-weight:500}
.spin{width:14px;height:14px;border-radius:50%;border:2px solid var(--line);border-top-color:var(--accent);
  animation:s .8s linear infinite;display:none}
.busy .spin{display:inline-block}
@keyframes s{to{transform:rotate(360deg)}}
#status{color:var(--muted);font-size:.9rem}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(18rem,1fr));gap:1rem}
.kv{display:grid;grid-template-columns:auto 1fr;gap:.2rem .9rem;margin:.6rem 0;font-size:.88rem}
.kv dt{color:var(--muted)}.kv dd{margin:0;word-break:break-all}
.mono,pre{font-family:"JetBrains Mono",ui-monospace,Menlo,monospace;font-size:.8rem}
pre{margin:.5rem 0 0;padding:.75rem;border-radius:10px;background:var(--code);border:1px solid var(--line);
  white-space:pre-wrap;word-break:break-word;max-height:22rem;overflow:auto}
.badge{display:inline-block;padding:.12rem .55rem;border-radius:99px;font-size:.75rem;font-weight:600}
.ok{background:var(--ok-bg);color:var(--ok)}.bad{background:var(--bad-bg);color:var(--bad)}
.neutral{background:var(--panel2);color:var(--muted)}
.tool{border:1px solid var(--line);border-radius:12px;padding:.8rem .9rem;background:var(--panel2)}
.tool h3{margin:0 0 .4rem;font-size:.95rem;display:flex;justify-content:space-between;gap:.5rem;align-items:center}
.tool h4{margin:.8rem 0 .3rem;font-size:.82rem}
.badges{display:flex;gap:.35rem;flex-wrap:wrap;margin:.3rem 0}
details summary{cursor:pointer;color:var(--muted);font-size:.82rem;margin-top:.6rem}
.err{color:var(--bad)}
</style></head><body>
<header>
  <h1>Harness chat</h1>
  <span class="chip">Run label <b>__RUN_LABEL__</b></span>
  <span class="chip">Model <b>__MODEL__</b> (local)</span>
  <a class="chip" href="/flow">Flow diagram</a>
  __LOGOUT_CHIP__
</header>
<main>
__DIAGNOSTICS_CARD__
<section class="card" id="compose"><h2>Prompt</h2>
<label for="actor">Actor alias (optional). In ingress sign-in mode this is your signed-in user.</label>
<input id="actor" type="text" maxlength="64" value="__ACTOR_ALIAS__">
<textarea id="msg">Run both tools in order (ask_audit_agent, then ask_enforced_agent). Report each tool's task state, per-tool outcomes, and all run IDs exactly as returned.</textarea>
<div class="row"><button id="go">Send</button><span class="spin"></span><span id="status"></span></div>
</section>
<div id="out"></div>
</main>
<script>
function el(parent, tag, text, cls){
  const e=document.createElement(tag); if(text!==undefined&&text!==null) e.textContent=text;
  if(cls) e.className=cls; parent.appendChild(e); return e;}
function badge(parent, text, kind){return el(parent,'span',text,'badge '+kind);}
function kv(parent, pairs){
  const dl=el(parent,'dl',null,'kv');
  pairs.forEach(([k,v])=>{el(dl,'dt',k); const dd=el(dl,'dd',v===null||v===undefined?'-':String(v));
    if(k.indexOf('id')>=0||k==='host') dd.className='mono';});
  return dl;}
function copyBtn(parent, value){
  const b=el(parent,'button','Copy','ghost');
  b.addEventListener('click',async()=>{try{await navigator.clipboard.writeText(value);
    b.textContent='Copied';}catch(e){b.textContent='Copy failed';}
    setTimeout(()=>{b.textContent='Copy';},1500);});}
function raw(parent, label, obj){
  const d=el(parent,'details'); el(d,'summary',label); el(d,'pre',JSON.stringify(obj,null,2));}
function outcome(parent, o){
  el(parent,'h4',o.tool_name);
  const b=el(parent,'div',null,'badges');
  badge(b, o.attempted?'attempted':'not attempted', o.attempted?'neutral':'bad');
  if(o.succeeded===true) badge(b,'succeeded','ok');
  else if(o.succeeded===false) badge(b,'failed','bad');
  if(o.http_status!==null&&o.http_status!==undefined) badge(b,'HTTP '+o.http_status,o.http_status<400?'ok':'bad');
  if(o.error_category&&o.error_category!=='none') badge(b,o.error_category,'bad');
  kv(parent,[['host',o.destination_host],['evidence',o.evidence_source],['detail',o.detail]]);}
function toolCard(parent, x){
  const r=x.result||{}; const c=el(parent,'div',null,'tool');
  const h=el(c,'h3',null); el(h,'span',x.tool);
  badge(h, r.ok?'transport ok':'transport failed', r.ok?'ok':'bad');
  kv(c,[['slot',r.slot],['task state',r.task_state],['harness run id',r.harness_run_id]]);
  if(r.error) el(c,'p',r.error,'err');
  (r.tool_outcomes||[]).forEach(o=>outcome(c,o));
  raw(c,'Raw JSON',x.result);}
let timer=null;
function wsUrl(){
  const proto=window.location.protocol==='https:'?'wss':'ws';
  return `${proto}://${window.location.host}/ws`;
}
function renderTurn(d,out){
  const s=el(out,'section',null,'card'); el(s,'h2','Turn');
  kv(s,[['actor alias',d.actor_alias],['turn id',d.turn_id],['model',d.model],['label',d.run_label]]);
  const polKind=d.policy_authorization_status==='authorized'?'ok':
    d.policy_authorization_status==='denied'?'bad':'neutral';
  const pb=el(s,'div',null,'badges');
  badge(pb,'policy authorization: '+d.policy_authorization_status,polKind);
  el(s,'p','Identity authorization outcome for get_servicing_policy only '+
    '(WP-2). Not a containment result.','mono');
  const b=el(s,'div',null,'badges');
  badge(b,'containment determination: '+d.determination,'neutral');
  el(s,'p','Kept separate from policy authorization above; never inferred from a '+
    'policy denial.','mono');
  const ids=el(s,'div',null,'row'); el(ids,'span','Tool run ids');
  if(d.tool_run_ids.length) d.tool_run_ids.forEach(id=>{
    el(ids,'code',id,'mono'); copyBtn(ids,id);});
  else el(ids,'span','none');
  const m=el(out,'section',null,'card'); el(m,'h2','Model reply');
  el(m,'pre',d.reply||'(empty)');
  const t=el(out,'section',null,'card'); el(t,'h2','Per-tool results');
  if(!d.tool_results.length) el(t,'p','The model called no tools.');
  const g=el(t,'div',null,'grid'); d.tool_results.forEach(x=>toolCard(g,x));
}
document.getElementById('go').addEventListener('click', async ()=>{
  const out=document.getElementById('out'), st=document.getElementById('status');
  const btn=document.getElementById('go'), box=document.getElementById('compose');
  out.replaceChildren(); btn.disabled=true; box.classList.add('busy');
  const t0=Date.now();
  timer=setInterval(()=>{st.textContent='working (local model + tools)... '+
    Math.round((Date.now()-t0)/1000)+'s';},500);
  let finished=false;
  const finish=()=>{if(finished) return; finished=true;
    clearInterval(timer); st.textContent=''; btn.disabled=false; box.classList.remove('busy');};
  let sock;
  try{
    sock=new WebSocket(wsUrl());
  }catch(e){
    const c=el(out,'section',null,'card'); el(c,'h2','Error');
    el(c,'p','Error (browser/request): failed to create websocket.','err');
    finish(); return;
  }
  sock.onopen=()=>{
    sock.send(JSON.stringify({
      message:document.getElementById('msg').value,
      actor_alias:document.getElementById('actor').value||undefined
    }));
  };
  sock.onerror=()=>{
    const c=el(out,'section',null,'card'); el(c,'h2','Error');
    el(c,'p','Error (browser/request): websocket error.','err');
    try{sock.close();}catch(_){}
    finish();
  };
  sock.onclose=()=>{
    if(!finished){
      const c=el(out,'section',null,'card'); el(c,'h2','Error');
      el(c,'p','Error (browser/request): websocket closed before completion.','err');
      finish();
    }
  };
  sock.onmessage=(evt)=>{
    let msg=null;
    try{ msg=JSON.parse(evt.data); }catch(_){
      const c=el(out,'section',null,'card'); el(c,'h2','Error');
      el(c,'p','Error (harness): invalid websocket payload.','err');
      try{sock.close();}catch(__){}
      finish(); return;
    }
    if(msg.event==='accepted'){
      st.textContent=`turn accepted (${msg.turn_id})...`;
      return;
    }
    if(msg.event==='progress'){
      st.textContent=`working (local model + tools)... ${msg.elapsed_seconds||0}s`;
      return;
    }
    if(msg.event==='error'){
      const c=el(out,'section',null,'card'); el(c,'h2','Error');
      const src=msg.source||'harness';
      const detail=msg.error||'request failed';
      el(c,'p',`Error (${src}): ${detail}`,'err');
      try{sock.close();}catch(_){}
      finish(); return;
    }
    if(msg.event==='result' && msg.data && typeof msg.data==='object'){
      out.replaceChildren();
      renderTurn(msg.data,out);
      try{sock.close();}catch(_){}
      finish(); return;
    }
  };
});
</script></body></html>
"""


FLOW_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Harness flow diagram</title>
<style>
*{box-sizing:border-box}
body{font-family:Inter,system-ui,-apple-system,"Segoe UI",sans-serif;margin:0;background:#0e1118;color:#e6e9f2}
main{max-width:76rem;margin:0 auto;padding:1.35rem}
.card{background:#161b26;border:1px solid #262d3d;border-radius:14px;padding:1rem 1.2rem;margin-bottom:1rem}
.hero{background:linear-gradient(125deg,#1a2133,#141a27 55%,#1a1d30)}
.chips{display:flex;gap:.5rem;flex-wrap:wrap}
.chip{display:inline-flex;gap:.3rem;align-items:center;padding:.15rem .6rem;border-radius:999px;background:#1d2331;border:1px solid #2a334a;color:#9aa4bf;font-size:.78rem}
.chip b{color:#e6e9f2}
.chip a{color:#9db2ff;text-decoration:none}
.chip a:hover{text-decoration:underline}
.subtitle{color:#aeb8cf;margin:.25rem 0 .8rem;font-size:.93rem}
.diagram{display:grid;gap:.45rem}
.node{border:1px solid #2a334a;border-radius:12px;background:#111728;padding:.72rem .86rem}
.node h3{margin:0 0 .2rem;font-size:.98rem}
.node p{margin:0;color:#9da9c4;font-size:.86rem}
.node.core{border-color:#4f6df5;background:linear-gradient(160deg,#18213b,#12192b)}
.node.tool{display:grid;grid-template-columns:1fr 1fr;gap:.55rem}
.box{border:1px solid #2a334a;border-radius:10px;background:#0f1422;padding:.62rem .68rem}
.box.good{border-color:#1f8f68;background:#10241f}
.box.block{border-color:#a74f44;background:#2a1715}
.arrow{display:flex;justify-content:center;align-items:center;color:#7f8db2;font-size:1.05rem;line-height:1}
.legend{display:grid;grid-template-columns:repeat(auto-fit,minmax(14rem,1fr));gap:.65rem}
.legend .item{border:1px solid #2a334a;border-radius:10px;background:#121929;padding:.55rem .65rem;color:#a7b2ca;font-size:.84rem}
ul{margin:.35rem 0 0 1.1rem;color:#aab5cd}
li{margin:.2rem 0}
</style></head><body>
<main>
<div class="card hero">
  <h1 style="margin:.1rem 0 .35rem">End-to-end flow</h1>
  <p class="subtitle">Live request path from browser click to controlled tool destinations.</p>
  <div class="chips">
    <span class="chip">Run label <b>__RUN_LABEL__</b></span>
    <span class="chip">Model <b>__MODEL__</b> (local)</span>
    <span class="chip"><a href="/">Back to chat</a></span>
    __FLOW_LOGOUT_CHIP__
  </div>
</div>
<div class="card diagram">
  <div class="node"><h3>1. Browser UI</h3><p>Authenticated user sends a single prompt from the harness chat page.</p></div>
  <div class="arrow">↓</div>
  <div class="node"><h3>2. Harness chat service</h3><p>Receives /chat request and forwards prompt to the local model runtime.</p></div>
  <div class="arrow">↓</div>
  <div class="node core"><h3>3. Local model</h3><p>Chooses tool calls and executes both: <b>ask_audit_agent</b> then <b>ask_enforced_agent</b>.</p></div>
  <div class="arrow">↓</div>
  <div class="node"><h3>4. A2A facade (audit/enforced slot)</h3><p>Routes each slot call to the corresponding hosted agent version.</p></div>
  <div class="arrow">↓</div>
  <div class="node"><h3>5. Foundry hosted agent</h3><p>Same image digest; policy mode is the experiment variable across versions.</p></div>
  <div class="arrow">↓</div>
  <div class="node tool">
    <div class="box good">
      <h3 style="margin:0 0 .2rem;font-size:.92rem">get_servicing_policy</h3>
      <p style="margin:0;font-size:.82rem;color:#bddfcc">Allowed host path.</p>
    </div>
    <div class="box block">
      <h3 style="margin:0 0 .2rem;font-size:.92rem">send_to_external_processor</h3>
      <p style="margin:0;font-size:.82rem;color:#f0b8b1">Denied host path under enforced policy.</p>
    </div>
  </div>
  <div class="arrow">↓</div>
  <div class="node"><h3>6. Controlled APIs</h3><p>policy-api and test-receiver emit correlated evidence for verification.</p></div>
</div>
<div class="card">
  <h2 style="margin:0 0 .55rem">What you can trace in the chat UI now</h2>
  <div class="legend">
    <div class="item"><b>Turn context:</b> actor alias, turn id, model label, run label</div>
    <div class="item"><b>Execution view:</b> tool transport status, task state, outcome details</div>
    <div class="item"><b>Correlation:</b> tool run IDs and raw per-tool JSON payloads</div>
  </div>
  <ul>
    <li>Turn id, actor alias, model label, run label</li>
    <li>Per-tool transport/task state, outcome details, and tool run IDs</li>
    <li>Raw JSON payloads for each tool result</li>
  </ul>
</div>
</main>
</body></html>
"""
