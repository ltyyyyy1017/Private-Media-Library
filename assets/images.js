'use strict';
function imageURL(path){return '/image?path='+encodeURIComponent(path)}
const imageQueue=[];let activeImages=0;
const imageObserver=new IntersectionObserver(entries=>{for(let e of entries)if(e.isIntersecting){imageObserver.unobserve(e.target);imageQueue.push(e.target);pumpImages()}},{rootMargin:'100px'});
function pumpImages(){while(activeImages<2&&imageQueue.length){const img=imageQueue.shift();if(!img.isConnected)continue;activeImages++;loadImage(img,img._imagePath,()=>{activeImages--;pumpImages()})}}
function loadImage(img,path,done=()=>{}){let retried=false,finished=false,attempts=0;const timer=setTimeout(()=>{img.onload=img.onerror=null;img.removeAttribute('src');img.alt='加载超时，请刷新重试';finish()},25000);function finish(){if(finished)return;finished=true;clearTimeout(timer);done()}img.onload=finish;img.onerror=()=>{if(attempts++<2&&navigator.onLine){setTimeout(()=>{if(!finished&&img.isConnected)img.src=imageURL(path)+'&retry='+attempts},1000*attempts);return}if(!retried&&navigator.onLine){retried=true;img.src=imageURL(path)+'&convert=1'}else{img.onerror=null;img.alt='图片暂时无法加载，请检查连接或下载原文件';if(img.closest('#stage'))$('mediaHint').textContent='图片加载失败，请检查连接或下载原文件查看。';finish()}};img.src=imageURL(path)}
function setImagePreview(img,path){if(img.closest('.card')){img._imagePath=path;imageObserver.observe(img)}else loadImage(img,path)}
const beforeImageRender=render;
render=function(){imageObserver.disconnect();imageQueue.length=0;beforeImageRender();for(let card of document.querySelectorAll('.card')){let name=card.querySelector('h3').textContent,f=items.find(x=>x.name===name);if(!f||kind(f)!=='image')continue;let img=card.querySelector('.cover img');if(img)setImagePreview(img,filePath(f))}};
const beforeImageOpen=open;
open=async function(f){await beforeImageOpen(f);if(current!==f||kind(f)!=='image')return;let img=$('stage').querySelector('img');if(img)setImagePreview(img,filePath(f));const native=/\.(jpe?g|jpe|jfif|png|apng|webp|gif|avif|bmp)$/i.test(f.name);$('mediaHint').textContent=native?'动图自动播放 · 点击放大 · 左右滑动切换':'兼容预览 · 多页/多帧格式仅显示首帧 · 原始文件可下载'};
