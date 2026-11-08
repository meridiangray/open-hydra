(function(){var s=document.currentScript,bar=s&&s.parentNode;if(!bar||bar.dataset.ready)return;bar.dataset.ready=1;
var pane=bar.closest('.pane')||document,key='hydra-tl',st='vh';try{st=localStorage.getItem(key)||'vh'}catch(e){}
function parts(){return{v:[].slice.call(pane.querySelectorAll('ul.timeline')),h:[].slice.call(pane.querySelectorAll('figure.lifebarbox'))}}
function apply(){var p=parts();['v','h'].forEach(function(k){var on=st.indexOf(k)>=0;p[k].forEach(function(e){e.hidden=!on});
var b=bar.querySelector('[data-tl='+k+']');if(b){b.classList.toggle('on',on);b.hidden=!p[k].length}})}
[].forEach.call(bar.querySelectorAll('button'),function(b){b.addEventListener('click',function(){var k=b.dataset.tl;
st=st.indexOf(k)>=0?st.replace(k,''):st+k;if(!st)st=k==='v'?'h':'v';try{localStorage.setItem(key,st)}catch(e){}apply()})});
apply();document.addEventListener('DOMContentLoaded',apply)})();
