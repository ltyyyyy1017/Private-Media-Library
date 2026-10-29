'use strict';
const rememberLabel=document.createElement('label');rememberLabel.className='remember-login';const rememberInput=document.createElement('input');rememberInput.type='checkbox';rememberInput.checked=true;rememberInput.id='remember-login';rememberLabel.append(rememberInput,' 记住登录 7 天（仅限自己的设备）');$('password').after(rememberLabel);
const originalPost=post;
// The login cookie is HttpOnly. Only non-sensitive reader preferences are
// exposed to JavaScript; no password is stored in cookies or localStorage.
post=function(path,data){return originalPost(path,path==='/login'?{...data,remember:rememberInput.checked}:data)};
let preferences={size:20,dark:false};try{let saved=document.cookie.split('; ').find(x=>x.startsWith('reader_preferences='));if(saved)preferences={...preferences,...JSON.parse(decodeURIComponent(saved.split('=').slice(1).join('=')))}}catch{}
function savePreferences(article){preferences={size:parseFloat(getComputedStyle(article).fontSize),dark:article.classList.contains('dark')};document.cookie='reader_preferences='+encodeURIComponent(JSON.stringify(preferences))+'; Path=/; Max-Age=31536000; SameSite=Strict; Secure'}
let preferenceObserver=null;
const readerSettings=button('阅读设置',()=>{$('viewer').classList.toggle('settings-open');readerSettings.setAttribute('aria-expanded',String($('viewer').classList.contains('settings-open')))});readerSettings.className='reader-settings-toggle';readerSettings.setAttribute('aria-expanded','false');$('close').before(readerSettings);
const baseOpen=open;
open=async function(f){if(preferenceObserver)preferenceObserver.disconnect();let reading=kind(f)==='text';$('viewer').classList.toggle('reading',reading);$('viewer').classList.remove('settings-open');document.body.classList.toggle('reading-open',reading);readerSettings.setAttribute('aria-expanded','false');await baseOpen(f);let article=$('stage').querySelector('.reader');if(article){article.style.fontSize=Math.min(36,Math.max(14,Number(preferences.size)||20))+'px';article.classList.toggle('dark',!!preferences.dark);preferenceObserver=new MutationObserver(()=>savePreferences(article));preferenceObserver.observe(article,{attributes:true,attributeFilter:['style','class']});article.addEventListener('paste',e=>{if(article.contentEditable==='true'){e.preventDefault();document.execCommand('insertText',false,e.clipboardData.getData('text/plain'))}})}};
function leaveReading(){document.body.classList.remove('reading-open');$('viewer').classList.remove('reading','settings-open');if(preferenceObserver)preferenceObserver.disconnect()}
const oldClose=close;close=function(){leaveReading();oldClose()};$('close').onclick=close;$('viewer').addEventListener('cancel',leaveReading);
