/* 山歌播放：唔會自動播；撳「▶ 聽山歌」先播，「■ 停止」停埋返去開頭 */
(function(){
  var box=document.querySelector('.sing-ctl'),au=document.getElementById('sing-audio');
  if(!box||!au||typeof au.play!=='function')return;
  var play=box.querySelector('.sing-play'),stop=box.querySelector('.sing-stop');
  au.volume=0.3;
  function sync(){play.setAttribute('aria-pressed',au.paused?'false':'true');}
  play.addEventListener('click',function(){au.volume=0.3;var r=au.play();if(r&&r.catch)r.catch(function(){});});
  stop.addEventListener('click',function(){au.pause();au.currentTime=0;sync();});
  au.addEventListener('play',sync);au.addEventListener('pause',sync);au.addEventListener('ended',sync);
  sync();box.hidden=false;
})();
