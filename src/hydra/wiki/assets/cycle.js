(function(){var s=document.currentScript,x=s&&s.parentNode;if(!x||x.dataset.ready)return;x.dataset.ready=1;
var f=[].slice.call(x.querySelectorAll('figure')),pos=x.querySelector('.pos'),i=0;x.classList.add('js');
function show(n){i=(n+f.length)%f.length;f.forEach(function(e,k){e.hidden=k!==i});pos.textContent=(i+1)+' / '+f.length}
x.querySelector('.prev').addEventListener('click',function(){show(i-1)});
x.querySelector('.next').addEventListener('click',function(){show(i+1)});
x.addEventListener('keydown',function(e){if(e.key==='ArrowLeft')show(i-1);else if(e.key==='ArrowRight')show(i+1)});show(0)})();
