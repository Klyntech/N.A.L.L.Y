/* ============================================================
   NALLYMAKES — Cinematic Scrollytelling Engine
   ------------------------------------------------------------
   Vanilla JS. No dependencies. 60fps via requestAnimationFrame.
   Single scroll listener (passive). Self-contained: does not
   touch main.js. Injects its own progress bar.
   ============================================================ */
(function () {
  'use strict';

  var doc = document;
  var root = doc.documentElement;
  var body = doc.body;
  var win = window;

  // Progressive enhancement gate: only hide/reveal if JS runs.
  root.classList.add('nl-scrolly');

  /* ---------- 1. Film progress bar (no HTML edit needed) ---------- */
  var bar = doc.createElement('div');
  bar.className = 'scroll-progress';
  body.appendChild(bar);

  /* ---------- 2. Tag every section for scene reveals ---------- */
  var sections = Array.prototype.slice.call(doc.querySelectorAll('section'));
  sections.forEach(function (s) { s.classList.add('scene-reveal'); });

  var io = new IntersectionObserver(function (entries) {
    entries.forEach(function (e) {
      if (e.isIntersecting) {
        e.target.classList.add('in-view');
        io.unobserve(e.target); // reveal once, then stop watching
      }
    });
  }, { threshold: 0.15 });
  sections.forEach(function (s) { io.observe(s); });

  /* ---------- 3. Hero intro title-card ---------- */
  function playHero() {
    requestAnimationFrame(function () { root.classList.add('hero-ready'); });
  }
  if (doc.readyState === 'complete' || doc.readyState === 'interactive') {
    setTimeout(playHero, 120);
  } else {
    doc.addEventListener('DOMContentLoaded', function () { setTimeout(playHero, 120); });
  }

  /* ---------- 4. Deep-parallax targets ---------- */
  var parallaxEls = Array.prototype.slice.call(doc.querySelectorAll('.nl-parallax'));

  /* ---------- 5. Scroll engine (rAF throttled, one listener) ---------- */
  var heroBg = doc.querySelector('.hero-bg');
  var heroH = heroBg ? heroBg.offsetHeight : 0;
  var ticking = false;
  var lastY = win.pageYOffset || 0;
  var fastTimer = null;

  function onScroll() {
    var y = win.pageYOffset || doc.documentElement.scrollTop || 0;
    var velocity = Math.abs(y - lastY);
    lastY = y;

    // (a) progress bar
    var docH = doc.documentElement.scrollHeight - win.innerHeight;
    var pct = docH > 0 ? Math.min(1, Math.max(0, y / docH)) : 0;
    bar.style.transform = 'scaleX(' + pct + ')';

    // (b) hero parallax (drift slower than page)
    if (heroBg && y < heroH * 1.5) {
      heroBg.style.transform = 'translate3d(0,' + (y * 0.35) + 'px,0) scale(1.15)';
    }

    // (c) per-section subtle depth parallax on inner container
    for (var i = 0; i < sections.length; i++) {
      var sec = sections[i];
      var rect = sec.getBoundingClientRect();
      if (rect.bottom < -200 || rect.top > win.innerHeight + 200) continue;
      var inner = sec.querySelector('.container') || sec.firstElementChild;
      if (!inner || inner.classList.contains('nl-parallax')) continue;
      var local = (win.innerHeight / 2 - (rect.top + rect.height / 2)) / win.innerHeight;
      var shift = Math.max(-22, Math.min(22, local * 22));
      inner.style.transform = 'translate3d(0,' + shift.toFixed(1) + 'px,0)';
    }

    // (d) optional deep parallax
    for (var j = 0; j < parallaxEls.length; j++) {
      var el = parallaxEls[j];
      var sp = parseFloat(el.getAttribute('data-speed')) || 0.2;
      var r2 = el.getBoundingClientRect();
      if (r2.bottom < -300 || r2.top > win.innerHeight + 300) continue;
      var prog = (win.innerHeight - r2.top) / (win.innerHeight + r2.height);
      var move = (prog - 0.5) * 2 * 120 * sp;
      el.style.transform = 'translate3d(0,' + move.toFixed(1) + 'px,0)';
    }

    // (e) velocity glow
    if (velocity > 18) {
      body.classList.add('scrolling-fast');
      if (fastTimer) clearTimeout(fastTimer);
      fastTimer = setTimeout(function () { body.classList.remove('scrolling-fast'); }, 220);
    }

    ticking = false;
  }

  function requestTick() {
    if (!ticking) {
      ticking = true;
      requestAnimationFrame(onScroll);
    }
  }

  win.addEventListener('scroll', requestTick, { passive: true });
  win.addEventListener('resize', function () {
    heroH = heroBg ? heroBg.offsetHeight : 0;
    requestTick();
  }, { passive: true });

  onScroll(); // initial paint
})();
