'use strict';
document.querySelector('.hero').hidden=true;
document.querySelector('.side-note').textContent='文件留在电脑 · 标签整理内容';
const toolbar=document.querySelector('.toolbar');
document.querySelector('main').prepend(toolbar);
tagHeading.textContent='标签筛选';
const libraryTools=document.createElement('details');libraryTools.className='library-tools';
const toolSummary=document.createElement('summary');toolSummary.textContent='整理工具';libraryTools.append(toolSummary);
for(let node of [...$('nav').children])if(/整理记录|重复查找/.test(node.textContent))libraryTools.append(node);
document.querySelector('aside').append(libraryTools);
const tagTools=document.createElement('details');tagTools.className='tag-tools';let tagSummary=document.createElement('summary');tagSummary.textContent='标签管理';tagTools.append(tagSummary);
for(let node of [...tagBar.children])if(node.tagName==='BUTTON'&&/新建标签|管理标签/.test(node.textContent))tagTools.append(node);
tagHeading.after(tagTools);
const fileTools=document.createElement('details');fileTools.className='file-tools';let fileSummary=document.createElement('summary');fileSummary.textContent='浏览选项';fileTools.append(fileSummary);
for(let node of [...$('heading').parentElement.children])if(node.tagName==='BUTTON')fileTools.append(node);
document.querySelector('.actions').prepend(fileTools);
const density=button('列表视图',()=>{let list=$('grid').classList.toggle('list-view');density.textContent=list?'卡片视图':'列表视图';remember('layout',list?'list':'grid')});
document.querySelector('.actions').prepend(density);
if(recalled('layout')==='list'){$('grid').classList.add('list-view');density.textContent='卡片视图'}
const previousWorkspaceRender=render;
render=function(){if(loadingTags===loadVersion)return;const openMenus=new Set([...$('grid').querySelectorAll('.file-menu[open]')].map(menu=>menu.closest('.card').dataset.path));previousWorkspaceRender();for(let card of document.querySelectorAll('.card')){let actions=card.querySelector('.card-actions');if(!actions||actions.closest('.file-menu'))continue;let details=document.createElement('details');details.className='file-menu';details.open=openMenus.has(card.dataset.path);let summary=document.createElement('summary');summary.textContent='操作';details.append(summary,actions);details.onclick=e=>e.stopPropagation();details.onkeydown=e=>e.stopPropagation();card.append(details)}};
const selectionToggle=button('批量选择',()=>{let enabled=document.body.classList.toggle('selecting');selectionToggle.textContent=enabled?'结束选择':'批量选择';if(!enabled){selectedFiles.clear();render()}});
document.querySelector('.actions').prepend(selectionToggle);
batchBar.classList.add('selection-toolbar');
const refreshView=button('刷新列表',()=>load());document.querySelector('.actions').append(refreshView);

// Keep the dialog and its video element in the document when changing modes.
// Recreating the video would stop playback and exit the browser's PiP mode.
const videoViewer=$('viewer');
const dockVideo=button('小窗播放',()=>setVideoDocked(true));
const expandVideo=button('恢复大窗',()=>setVideoDocked(false));
const stopViewer=close;
const openViewer=open;
dockVideo.hidden=expandVideo.hidden=true;
$('close').before(dockVideo,expandVideo);

function setVideoDocked(docked){
    if(!player||!videoViewer.open)return;
    if(videoViewer.classList.contains('viewer-docked')===docked)return;
    videoViewer.close();
    videoViewer.classList.toggle('viewer-docked',docked);
    dockVideo.hidden=docked;
    expandVideo.hidden=!docked;
    $('close').textContent=docked?'结束播放':'关闭';
    if(docked)videoViewer.show();
    else videoViewer.showModal();
}

close=function(){
    videoViewer.classList.remove('viewer-docked');
    dockVideo.hidden=expandVideo.hidden=true;
    $('close').textContent='关闭';
    stopViewer();
};
dismissViewer=function(){
    const video=$('stage').querySelector('video');
    const inPictureInPicture=video&&(document.pictureInPictureElement===video||video.webkitPresentationMode==='picture-in-picture');
    if(player&&!videoViewer.classList.contains('viewer-docked')&&(!player.paused()||inPictureInPicture))setVideoDocked(true);
    else close();
};
$('close').onclick=()=>dismissViewer();
open=async function(file){
    if(videoViewer.classList.contains('viewer-docked')){
        const sameVideo=current&&filePath(current)===filePath(file);
        setVideoDocked(false);
        if(sameVideo)return;
    }
    dockVideo.hidden=expandVideo.hidden=true;
    await openViewer(file);
    if(current===file&&player)dockVideo.hidden=false;
};
