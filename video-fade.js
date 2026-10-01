/* video-fade.js — softens the seam on looping background videos.

   YouTube implements loop=1 as a one-video playlist, which means it reloads the
   player every cycle and flashes black on the way round. This dips the iframe's
   opacity for half a second across that seam, so what shows through is whatever
   sits behind it (on the game pages, the still key art the .hero-video wrapper
   already carries) instead of a hard cut to black. It covers the first load the
   same way.

   Opt in per iframe with data-loop-fade. The iframe's src needs enablejsapi=1
   or the API can't see it. Non-looping players are left alone.

   Degrades to today's behaviour: opacity is only driven once a player reports a
   real duration, and if the API never loads the frames are restored after a few
   seconds. A blocked youtube.com/iframe_api means no fade, not an invisible
   video. */
(function () {
  var FADE_MS  = 500;   // transition length, both directions
  var LEAD_OUT = 0.6;   // seconds before the end to start dipping
  var LEAD_IN  = 0.45;  // seconds after the restart to come back up
  var GIVE_UP  = 6000;  // ms to wait for the API before restoring the frames

  var frames = Array.prototype.slice.call(
    document.querySelectorAll('iframe[data-loop-fade]')
  );
  if (!frames.length) return;

  var armed = false;

  frames.forEach(function (f) {
    f.style.transition = 'opacity ' + FADE_MS + 'ms ease';
    f.style.opacity = '0';
  });

  // If the API never turns up, show the videos rather than leaving them hidden.
  setTimeout(function () {
    if (!armed) frames.forEach(function (f) { f.style.opacity = '1'; });
  }, GIVE_UP);

  function watch(f, player) {
    setInterval(function () {
      var d = player.getDuration();
      var t = player.getCurrentTime();
      if (!d || typeof t !== 'number') return;   // metadata not in yet
      armed = true;
      var nearEnd = (d - t) <= LEAD_OUT;
      var justStarted = t <= LEAD_IN;
      f.style.opacity = (nearEnd || justStarted) ? '0' : '1';
    }, 120);
  }

  window.onYouTubeIframeAPIReady = function () {
    frames.forEach(function (f, i) {
      // The API binds by element id, and won't attach to an element without one.
      if (!f.id) f.id = 'loop-fade-' + i;
      new YT.Player(f.id, {
        events: {
          onReady: function (e) { watch(f, e.target); }
        }
      });
    });
  };

  var s = document.createElement('script');
  s.src = 'https://www.youtube.com/iframe_api';
  document.head.appendChild(s);
})();
