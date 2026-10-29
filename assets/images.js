'use strict';
function imageURL(path){return '/image?path='+encodeURIComponent(path)}
function setImagePreview(img,path){let retried=false;img.onerror=()=>{if(!retried){retried=true;img.src=imageURL(path)+'&convert=1'}else{img.onerror=null;img.alt='此图片无法预览，请下载原文件';if(img.closest('#stage'))$('mediaHint').textContent='图片损坏、编码不支持或超过预览限制，请下载原文件查看。'}};img.src=imageURL(path)}
const beforeImageRender=render;
render=function(){beforeImageRender();for(let card of document.querySelectorAll('.card')){let name=card.querySelector('h3').textContent,f=items.find(x=>x.name===name);if(!f||kind(f)!=='image')continue;let img=card.querySelector('.cover img');if(img)setImagePreview(img,join(f.name))}};
const beforeImageOpen=open;
open=async function(f){await beforeImageOpen(f);if(current!==f||kind(f)!=='image')return;let img=$('stage').querySelector('img');if(img)setImagePreview(img,join(f.name));const native=/\.(jpe?g|jpe|jfif|png|apng|webp|gif|avif|bmp)$/i.test(f.name);$('mediaHint').textContent=native?'动图自动播放 · 点击放大 · 左右滑动切换':'兼容预览 · 多页/多帧格式仅显示首帧 · 原始文件可下载'};
