/* Fade each self-hosted hero background video in over its still (the wrapper's
   key-art background, which is also the video's poster) once it is actually
   playing, so there is no hard pop from the still to the first frame. If autoplay
   is blocked or the file cannot decode, the video stays at opacity 0 and the
   still shows through — same fallback as phones and reduced-motion.

   Pairs with the CSS:  .hero-video video, .hero-bg video { opacity:0; transition:opacity .8s ease }
                        .hero-video video.ready, .hero-bg video.ready { opacity:1 } */
(function () {
  var vids = document.querySelectorAll('.hero-video video, .hero-bg video');
  Array.prototype.forEach.call(vids, function (v) {
    function reveal() { v.classList.add('ready'); }
    // already running before this script ran (cached / fast decode)
    if (v.readyState >= 3 && !v.paused && !v.ended) { reveal(); return; }
    v.addEventListener('playing', reveal, { once: true });
    // nudge autoplay; a rejected promise just leaves the still showing
    var p = v.play && v.play();
    if (p && p.catch) p.catch(function () {});
  });
})();
