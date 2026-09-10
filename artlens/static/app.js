'use strict';
const $ = id => document.getElementById(id);
let session = null, previewURL = null, busy = false, progressTimer = null;
async function request(url, options) {
  const response = await fetch(url, options);
  let data;
  try {data = await response.json();} catch (_) {throw new Error('服务未返回有效结果，请检查终端并重试。');}
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '请求失败，请检查输入。');
  return data;
}
async function release() {
  const old = session; session = null;
  if (old) await fetch('/api/session/' + encodeURIComponent(old), {method:'DELETE'}).catch(()=>{});
}
function resetResults() {
  $('evidence').hidden = true; $('evidence').replaceChildren();
  $('answer').hidden = $('sources').hidden = $('conversation').hidden = true;
  $('empty').hidden = false; $('warnings').textContent = ''; $('messages').replaceChildren();
  $('identity').textContent = '等待分析'; $('chatError').textContent = '';
}
$('file').addEventListener('change', async () => {
  if (busy) return;
  await release(); resetResults();
  if (previewURL) URL.revokeObjectURL(previewURL);
  const file = $('file').files[0];
  $('preview').hidden = !file; $('uploadHint').hidden = !!file;
  $('filename').textContent = file ? file.name : '尚未选择图片';
  if (file) {previewURL = URL.createObjectURL(file); $('preview').src = previewURL;}
});
$('clear').onclick = async () => {if(busy)return; $('file').value=''; $('file').dispatchEvent(new Event('change'));};
for (const event of ['dragenter','dragover']) $('drop').addEventListener(event,e=>{e.preventDefault();$('drop').classList.add('drag');});
for (const event of ['dragleave','drop']) $('drop').addEventListener(event,e=>{e.preventDefault();$('drop').classList.remove('drag');});
$('drop').addEventListener('drop',e=>{if(busy)return; const f=e.dataTransfer.files[0];if(f){const dt=new DataTransfer();dt.items.add(f);$('file').files=dt.files;$('file').dispatchEvent(new Event('change'));}});
function lock(value) {busy=value;for(const id of ['analyze','file','clear','send'])$(id).disabled=value;}
function renderSources(items, identity) {
  $('cards').replaceChildren(); $('sources').hidden = !items.length;
  items.forEach((item,i)=>{
    const card=document.createElement('div');card.className='card';
    const img=document.createElement('img');img.alt=item.title;img.loading='lazy';
    // 本地索引仅允许芝加哥馆藏图片和作品链接。
    img.onerror=()=>{img.hidden=true;};
    if(/^\/api\/reference\/\d+$/.test(item.thumbnail_url || ''))img.src=item.thumbnail_url;
    const box=document.createElement('div'),a=document.createElement('a');
    a.textContent=`[${i+1}] ${item.title}`;a.target='_blank';a.rel='noopener noreferrer';
    if(/^https:\/\/www\.artic\.edu\/artworks\/\d+$/.test(item.url))a.href=item.url;
    const p=document.createElement('p');p.textContent=[item.artist,item.date].filter(Boolean).join(' · ');
    const score=document.createElement('small');score.textContent='余弦相似度 '+item.score.toFixed(3)+(i===0 && identity==='likely_match'?' · 双图核验通过':' · 未核验候选');
    box.append(a,p,score);card.append(img,box);$('cards').append(card);
  });
}
$('uploadForm').onsubmit=async e=>{
  e.preventDefault();if(busy)return;
  const file=$('file').files[0];if(!file)return;
  if(file.size>10*1024*1024){$('warnings').textContent='请上传不超过 10 MB 的图片。';return;}
  lock(true);await release();resetResults();
  startProgress('正在分析画作');$('identity').textContent='正在分析…';$('analyze').textContent='正在检索与解读…';
  try{const form=new FormData();form.append('file',file);const data=await request('/api/analyze',{method:'POST',body:form});
    session=data.session_id;ArtLensText.render($('answer'),data.answer);$('answer').hidden=false;$('empty').hidden=true;
    $('identity').textContent=data.identity==='likely_match'?'很可能匹配 · 双图核验通过':data.identity==='candidate'?'候选匹配 · 待核验':'作者尚未确认';
    renderEvidence(data);
    $('warnings').textContent=data.warnings.join('\n');renderSources(data.candidates, data.identity);$('conversation').hidden=!data.model_ok;
  }catch(err){$('warnings').textContent=err.message;$('identity').textContent='分析未完成';}
  finally{stopProgress();lock(false);$('analyze').textContent='分析画作 ↗';}
};
function message(text,role){const p=document.createElement('div');p.className='message '+role;ArtLensText.render(p,text);$('messages').append(p);}
$('chatForm').onsubmit=async e=>{
  e.preventDefault();if(busy||!session)return;const question=$('question').value.trim();if(!question)return;
  lock(true);$('send').textContent='正在回答…';$('chatError').textContent='';
  try{const data=await request('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:session,message:question})});message(question,'user');message(data.answer,'assistant');$('question').value='';}
  catch(err){$('chatError').textContent=err.message;}finally{lock(false);$('send').textContent='发送问题';}
};
request('/api/health').then(d=>{$('readiness').textContent=`视觉模型：${d.model_configured?'已配置':'待配置'} · 馆藏索引：${d.index_ready?'已构建':'待构建'}`;}).catch(()=>{$('readiness').textContent='无法连接后端，请通过本地服务地址打开页面。';});

// 支持时向浏览器智能体暴露当前可见结果；不代替用户选择或上传文件。
if (document.modelContext?.registerTool) {
  const lifecycle = new AbortController();
  try {
    Promise.resolve(document.modelContext.registerTool({
      name:'read_artwork_analysis', title:'读取当前画作分析',
      description:'读取当前页面已经显示的分析与身份状态，不发起模型请求。',
      inputSchema:{type:'object',properties:{},additionalProperties:false},
      annotations:{readOnlyHint:true,untrustedContentHint:true},
      execute(input){
        if(!input || typeof input!=='object' || Object.keys(input).length)throw new Error('此工具不接受参数。');
        return {status:$('identity').textContent,answer:$('answer').hidden?null:$('answer').textContent,warnings:$('warnings').textContent};
      }
    },{signal:lifecycle.signal})).catch(()=>{});
  } catch (_) {}
  window.addEventListener('pagehide',()=>lifecycle.abort(),{once:true});
}

function startProgress(label){
  stopProgress();const started=performance.now();$('progress').hidden=false;
  const update=()=>{$('progress').textContent=`${label} · 已等待 ${Math.floor((performance.now()-started)/1000)} 秒。首次检索需加载模型，双图核验会增加一次请求。`;};
  update();progressTimer=setInterval(update,1000);
}
function stopProgress(){clearInterval(progressTimer);progressTimer=null;$('progress').hidden=true;}
function renderEvidence(data){
  const target=$('evidence');target.replaceChildren();target.hidden=false;
  const work=data.identified_work;
  const h=document.createElement('h2');h.textContent=work?work.title:'识别依据';target.append(h);
  function row(label,value){const p=document.createElement('p');p.textContent=label+value;target.append(p);}
  if(work){row('馆藏作者：',work.artist);row('年代：',work.date||'未记录');}
  row('核验说明：',data.verification?.reason||'尚无可用核验说明。');
  for(const detail of data.verification?.matches||[])row('对应细节：',detail);
  for(const detail of data.verification?.differences||[])row('差异：',detail);
  if(data.retrieval_gap!==null && data.retrieval_gap!==undefined)row('第一名领先幅度：',data.retrieval_gap.toFixed(3)+'（相似度差值，不是概率）');
  row('本次服务处理耗时：',data.elapsed_seconds+' 秒');
  if(work)row('判断范围：','很可能为同一作品的图像；模型复核仍可能出错，不鉴定实物真伪。');
}
