'use strict';
let libraryTags={},fileTags={},activeTag='';
const tagBar=document.createElement('div');tagBar.className='batch-bar tag-bar';
const tagSelect=document.createElement('select');tagSelect.setAttribute('aria-label','按标签筛选');
function tagOptions(){let value=activeTag;tagSelect.replaceChildren(new Option('所有标签',''),new Option('未打标签的视频','__untagged'));for(let [id,name] of Object.entries(libraryTags))tagSelect.add(new Option('# '+name,id));tagSelect.value=value;if(tagSelect.selectedIndex<0){activeTag='';tagSelect.value=''}}
async function refreshTags(){libraryTags=(await(await api('/tags')).json()).tags;tagOptions()}
async function createTag(){let name=prompt('新建标签名称（最多 40 字）');if(!name)return;await post('/tags',{action:'create',name});await refreshTags();toast('标签已新建')}
tagBar.append(tagSelect,button('＋ 新建标签',createTag),button('管理标签',async()=>{
  const {d,body}=toolDialog('管理标签');
  async function draw(){await refreshTags();body.replaceChildren();body.append(button('＋ 新建标签',async()=>{await createTag();await draw()}));for(let [id,name] of Object.entries(libraryTags)){let row=document.createElement('section'),title=document.createElement('span');title.textContent='# '+name;row.append(title,button('改名',async()=>{let value=prompt('标签的新名称',name);if(!value||value===name)return;await post('/tags',{action:'rename',id,name:value});await draw();await load()}),button('删除标签',async()=>{if(!confirm('删除标签“'+name+'”？文件本身会保留。'))return;await post('/tags',{action:'delete',id});await draw();await load()}));body.append(row)}}await draw();
}));
batchBar.before(tagBar);
tagSelect.onchange=()=>run(async()=>{activeTag=tagSelect.value;wholeLibrary=true;dir='';filter='video';$('heading').textContent=activeTag==='__untagged'?'未打标签的视频':activeTag?'标签：'+libraryTags[activeTag]:'全部视频';await load()});
// Switching the library category clears a label filter.
$('nav').addEventListener('click',()=>{activeTag='';tagSelect.value=''},true);
const tagLoad=load;
load=async function(){await refreshTags();await tagLoad();fileTags=await(await post('/tag-files',{paths:items.filter(f=>!f.directory).map(f=>join(f.name))})).json();render()};
const tagRender=render;
render=function(){let all=items;if(activeTag)items=items.filter(f=>kind(f)==='video'&&(activeTag==='__untagged'?!(fileTags[join(f.name)]||[]).length:(fileTags[join(f.name)]||[]).includes(activeTag)));try{tagRender();for(let card of document.querySelectorAll('.card')){let path=card.dataset.path,f=items.find(x=>join(x.name)===path);if(!f||kind(f)!=='video')continue;let labels=document.createElement('div');labels.className='tag-chips';for(let id of fileTags[path]||[]){let chip=document.createElement('span');chip.textContent='# '+(libraryTags[id]||'');labels.append(chip)}card.append(labels);card.querySelector('.card-actions').append(button('打标签',()=>editTags([path])))}if(activeTag)$('count').textContent=$('grid').children.length+' 个视频 · 按标签筛选'}finally{items=all}};
async function editTags(paths){
  const {d,body}=toolDialog('给视频打标签');
  async function draw(){await refreshTags();const assigned=await(await post('/tag-files',{paths})).json();body.replaceChildren();let note=document.createElement('p');note.textContent='已选 '+paths.length+' 个视频。点击添加或移除标签，文件位置不变。';body.append(note,button('＋ 新建标签',async()=>{await createTag();await draw()}));for(let [id,name] of Object.entries(libraryTags)){let count=paths.filter(p=>(assigned[p]||[]).includes(id)).length,row=document.createElement('section'),label=document.createElement('span');label.textContent='# '+name+' · '+count+'/'+paths.length+' 已添加';row.append(label,button(count===paths.length?'移除':'添加',async()=>{await post('/tags',{action:'assign',id,paths,add:count!==paths.length});await draw();await load()}));if(count>0&&count<paths.length)row.append(button('全部移除',async()=>{await post('/tags',{action:'assign',id,paths,add:false});await draw();await load()}));body.append(row)}}await draw();
}
batchBar.append(button('批量打标签',async()=>{let paths=selectedRoots().filter(path=>kind({name:path})==='video');if(!paths.length)return toast('请先勾选视频');await editTags(paths)}));
const viewerTag=button('打标签',()=>editTags([join(current.name)]));$('download').before(viewerTag);viewerTag.hidden=true;
const tagOpen=open;open=async function(f){await tagOpen(f);viewerTag.hidden=kind(f)!=='video'};
