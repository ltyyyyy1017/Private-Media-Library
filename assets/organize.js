'use strict';
let wholeLibrary=false;
const folderLoad=load;
load=async function(){
  if(!wholeLibrary||filter==='favorites')return folderLoad();
  dir='';selectedFiles.clear();
  favoritePaths=new Set((await(await api('/favorites')).json()).map(x=>x.path));
  items=await(await api('/library')).json();
  $('crumb').textContent='全库虚拟分类 · 原文件位置不变';
  render();$('count').textContent=$('grid').children.length+' 项内容 · 全库';
};
const scope=button('切换全库视图',async()=>{wholeLibrary=!wholeLibrary;dir='';scope.textContent=wholeLibrary?'返回文件夹视图':'切换全库视图';$('search').placeholder=wholeLibrary?'搜索全库名称或路径…':'搜索当前文件夹…';await load()});
$('heading').after(scope);
document.querySelectorAll('nav button[data-type]').forEach(b=>b.onclick=()=>run(async()=>{
  wholeLibrary=b.dataset.type!=='all';dir='';filter=b.dataset.type;
  scope.textContent=wholeLibrary?'返回文件夹视图':'切换全库视图';
  $('search').placeholder=wholeLibrary?'搜索全库名称或路径…':'搜索当前文件夹…';
  document.querySelectorAll('nav button').forEach(x=>x.classList.toggle('active',x===b));
  $('heading').textContent=b.textContent.slice(2);await load();
}));
function toolDialog(title){let d=document.createElement('dialog');d.className='organize-dialog';let h=document.createElement('h2');h.textContent=title;let body=document.createElement('div');d.append(h,body,button('关闭',()=>{d.close();d.remove()}));document.body.append(d);d.addEventListener('cancel',()=>d.remove());d.showModal();return {d,body}}
$('nav').append(button('↶ 整理记录 / 撤销',async()=>{
  const {d,body}=toolDialog('整理记录');
  async function refresh(){let rows=await(await api('/history')).json();body.replaceChildren();let note=document.createElement('p');note.textContent='按时间倒序撤销移动、改名和删除。批量操作可逐项撤销；同名冲突或文件已变更时停止恢复。';body.append(note);
    if(!rows.length)body.append('暂无可撤销操作（更新后的操作才会记录）。');
    rows.forEach((r,i)=>{let row=document.createElement('section'),text=document.createElement('p');text.textContent=(r.trash?'删除：':'移动 / 改名：')+r.old+(r.trash?'':' → '+r.new);row.append(text);if(i===0)row.append(button('撤销最近这一步',async()=>{await post('/undo',{id:r.id});await refresh();await load();toast('已恢复')}));body.append(row)});
  }await refresh();
}));
$('nav').append(button('≡ 精确重复查找',async()=>{
  const {d,body}=toolDialog('重复与相似媒体');
  let note=document.createElement('p');note.textContent='精确结果为字节完全相同；相似结果只供人工比较。扫描在本机进行，无 AI。结果会保留，可直接预览和整理。';
  let status=document.createElement('p'),groups=document.createElement('div');
  let start=button('开始本地扫描',()=>scan(false)),approx=button('扫描相似图片 / 视频',()=>scan(true));
  body.append(note,start,approx,status,groups);
  async function scan(similar){await post('/duplicates',{similar});await poll()}
  async function preview(path){
    const view=toolDialog(path),type=kind({name:path});let message=document.createElement('p');view.body.append(message);
    if(type==='image'){let img=document.createElement('img');img.className='duplicate-preview';setImagePreview(img,path);view.body.append(img)}
    else if(type==='video'){let video=document.createElement('video');video.controls=true;video.playsInline=true;video.className='duplicate-preview';view.body.append(video);view.d.addEventListener('close',()=>{video.pause();video.removeAttribute('src');video.load()});
      if(/\.(ts|mts|m2ts|mkv|avi)$/i.test(path)){message.textContent='正在准备无损兼容播放…';let endpoint='/video-compatible?path='+encodeURIComponent(path);await post(endpoint,{});for(let n=0;n<620&&view.d.isConnected;n++){let r=await api(endpoint+'&status=1');if(r.status===200){video.src=endpoint;message.textContent='原画质 · 无损封装';break}await new Promise(resolve=>setTimeout(resolve,1000))}}
      else video.src=url(path);
      video.onerror=()=>message.textContent='当前浏览器不支持此编码，可下载原文件比较。';
    }else if(type==='text'){let r=await api(url(path));if(Number(r.headers.get('Content-Length'))>20*1024*1024){message.textContent='文档过大，请下载查看';return}let text=document.createElement('pre');text.className='duplicate-text';text.textContent=await r.text();view.body.append(text)}
    let link=document.createElement('a');link.textContent='下载原文件';link.href=url(path)+'&download=1';view.body.append(link);
  }
  async function poll(){if(!d.isConnected)return;let result=await(await api('/duplicates')).json();start.disabled=approx.disabled=result.running;status.textContent=result.phase+' · '+result.checked+'/'+result.total+' · 跳过 '+result.skipped;
    if(!result.running){groups.replaceChildren();for(let group of result.groups){let section=document.createElement('section'),h=document.createElement('h3');h.textContent=group.paths.length+(group.similar?' 个疑似相似文件 · 请人工核对':' 个完全相同的文件 · 每个 '+size(group.size));section.append(h);let keeper=group.paths[0];const radios=[];let merge=button('合并本组 · 保留所选',async()=>{let paths=[...section.querySelectorAll('.duplicate-row')].map(r=>r.dataset.path);if(paths.length<2)return;if(!paths.includes(keeper))return toast('请先选择要保留的文件');if(!confirm((group.similar?'这些只是疑似相似文件，可能有不同内容，请先预览核对。\n\n':'')+'保留：'+keeper+'\n\n移入回收区：\n'+paths.filter(p=>p!==keeper).join('\n')+'\n\n可在整理记录逐项撤销。确认合并？'))return;merge.disabled=true;try{let r=await(await post('/merge-duplicates',{paths,keeper})).json();for(let row of [...section.querySelectorAll('.duplicate-row')])if(r.removed.includes(row.dataset.path))row.remove();let left=section.querySelectorAll('.duplicate-row').length;h.textContent=left+' 个剩余文件';if(left<2)section.remove();status.textContent=r.complete?'合并完成，已保留所选文件；其他文件可从整理记录撤销。':'部分完成，已处理 '+r.removed.length+' 项；遇到变化或错误已停止，请重新扫描。'}finally{merge.disabled=false}});section.append(merge);
      for(let path of group.paths){let row=document.createElement('div');row.className='duplicate-row';row.dataset.path=path;let keep=document.createElement('input');keep.type='radio';keep.name='keeper-'+Math.random().toString(36).slice(2);keep.checked=path===keeper;keep.setAttribute('aria-label','保留 '+path);radios.push(keep);keep.onchange=()=>{keeper=path;for(let radio of radios)radio.checked=radio===keep};let keepLabel=document.createElement('label');keepLabel.className='keep-choice';keepLabel.append(keep,'保留');row.append(keepLabel);let label=document.createElement('span');label.textContent=path;let type=kind({name:path}),cover=document.createElement('div');cover.className='duplicate-cover';if(type==='image'){let img=document.createElement('img');img.loading='lazy';setImagePreview(img,path);cover.append(img)}else if(type==='video'){cover.textContent='▷';watchThumbnail(cover,{},path)}else cover.textContent='TXT';
        row.append(cover,label,button('查看',()=>preview(path)),button('移入回收区',async()=>{if(!confirm('确认移入回收区：'+path+'？请先确认保留的副本。'))return;await post('/delete',{path});row.remove();let count=section.querySelectorAll('.duplicate-row').length;h.textContent=count+' 个剩余文件 · '+(group.similar?'疑似相似':'完全相同');if(count<2)section.remove();status.textContent='已移入回收区，可在整理记录撤销。其他结果已保留。';}));section.append(row)}groups.append(section)}
      if(!result.groups.length&&result.phase.startsWith('扫描完成'))groups.textContent='没有发现符合条件的重复或相似文件。';
    }else setTimeout(()=>run(poll),1000);
  }await poll();
}));
// A remux only changes the container; decoded image quality stays unchanged.
const compatButton=button('无损兼容播放',async()=>{
  const f=current,path=join(f.name),endpoint='/video-compatible?path='+encodeURIComponent(path);
  compatButton.disabled=true;
  try{await post(endpoint,{});$('mediaHint').textContent='正在本机无损封装，保留原分辨率和音视频编码…';
    for(let i=0;i<620&&current===f&&$('viewer').open;i++){
      let response=await api(endpoint+'&status=1');if(response.status===200){if(player){player.src({src:endpoint,type:'video/mp4'});player.load()}$('mediaHint').textContent='无损兼容播放：没有降低画质。编码仍不被浏览器支持时，请下载原文件。';return}
      await new Promise(resolve=>setTimeout(resolve,1000));
    }
  }finally{compatButton.disabled=false}
});
const qualityOpen=open;
open=async function(f){await qualityOpen(f);if(current!==f)return;compatButton.hidden=kind(f)!=='video';if(kind(f)==='video'){$('mediaHint').textContent='原始画质播放 · 无降码率、无降分辨率 · 无法播放时可尝试无损兼容播放';if(/\.(ts|mts|m2ts)$/i.test(f.name))compatButton.click();}if(kind(f)==='image'){let img=$('stage').querySelector('img');if(img){img.onclick=()=>{img.classList.toggle('zoom');img.style.width=img.classList.contains('zoom')?img.naturalWidth+'px':''};$('mediaHint').textContent+=' · 点击按原始像素查看；小图放大不能增加细节';}}};
$('download').before(compatButton);compatButton.hidden=true;
watchThumbnail=function(cover,f,path){cover._thumbnailJob=async()=>{
  const endpoint='/thumbnail?path='+encodeURIComponent(path);let status;
  try{for(let attempt=0;attempt<150&&cover.isConnected;attempt++){let response=await fetch(endpoint);status=response.status;if(status===200){let img=document.createElement('img');img.alt='视频预览图';img.src=endpoint;cover.prepend(img);for(let n of [...cover.childNodes])if(n.nodeType===3)n.remove();return}if(status!==202)break;await new Promise(resolve=>setTimeout(resolve,1000))}}catch{}
  if(cover.isConnected){let retry=button('封面失败 · 重试',()=>{retry.remove();cover._thumbnailJob()});retry.className='thumbnail-retry';retry.onclick=e=>{e.stopPropagation();retry.disabled=true;setTimeout(()=>{retry.remove();run(cover._thumbnailJob)},status===422?60000:1000)};cover.append(retry)}
};observer.observe(cover)};
