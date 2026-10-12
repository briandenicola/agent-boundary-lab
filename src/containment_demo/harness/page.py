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
textarea{width:100%;min-height:5.5rem;resize:vertical;padding:.75rem .9rem;border-radius:10px;
  border:1px solid var(--line);background:var(--code);color:var(--text);font:inherit}
textarea:focus{outline:2px solid var(--accent);outline-offset:1px}
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
  <span class="chip warn">Not governed by Foundry egress policy</span>
</header>
<main>
<div class="notice">The harness and its model (<b>__MODEL__</b>, local) are <b>NOT governed by the Foundry egress policy</b>.
A model reply or tool result here is <b>not containment evidence</b>: the determination is <b>INCONCLUSIVE</b>
until verify_demo evidence is joined. Turns can take a minute or more.</div>
<section class="card" id="compose"><h2>Prompt</h2>
<textarea id="msg">Run the test: call both tools and report what each returned.</textarea>
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
document.getElementById('go').addEventListener('click', async ()=>{
  const out=document.getElementById('out'), st=document.getElementById('status');
  const btn=document.getElementById('go'), box=document.getElementById('compose');
  out.replaceChildren(); btn.disabled=true; box.classList.add('busy');
  const t0=Date.now();
  timer=setInterval(()=>{st.textContent='working (local model + tools)... '+
    Math.round((Date.now()-t0)/1000)+'s';},500);
  try{
    const r=await fetch('/chat',{method:'POST',
      headers:{'X-Demo-UI':'1','Content-Type':'application/json'},
      body:JSON.stringify({message:document.getElementById('msg').value})});
    const d=await r.json();
    if(!r.ok){const c=el(out,'section',null,'card'); el(c,'h2','Error');
      el(c,'p','Error ('+(d.source||'request')+'): '+(d.error||r.status),'err'); return;}
    const s=el(out,'section',null,'card'); el(s,'h2','Turn');
    const b=el(s,'div',null,'badges');
    badge(b,'determination: '+d.determination,'neutral');
    kv(s,[['turn id',d.turn_id],['model',d.model],['label',d.run_label]]);
    const ids=el(s,'div',null,'row'); el(ids,'span','Tool run ids');
    if(d.tool_run_ids.length) d.tool_run_ids.forEach(id=>{
      el(ids,'code',id,'mono'); copyBtn(ids,id);});
    else el(ids,'span','none');
    const m=el(out,'section',null,'card'); el(m,'h2','Model reply');
    el(m,'pre',d.reply||'(empty)');
    const t=el(out,'section',null,'card'); el(t,'h2','Per-tool results');
    if(!d.tool_results.length) el(t,'p','The model called no tools.');
    const g=el(t,'div',null,'grid'); d.tool_results.forEach(x=>toolCard(g,x));
  }catch(e){const c=el(out,'section',null,'card');
    el(c,'p','OUR request to the harness failed.','err');}
  finally{clearInterval(timer);st.textContent='';btn.disabled=false;box.classList.remove('busy');}
});
</script></body></html>
"""
