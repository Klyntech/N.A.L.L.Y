window.NALLY = window.NALLY || {};

NALLY.createOrb = function(opts) {
  opts = opts || {};
  var size = opts.size || 312;
  var state = opts.state || 'idle';
  var activated = opts.activated !== false;

  var wrapper = document.createElement('div');
  wrapper.className = 'orb-wrapper';
  wrapper.style.width = size + 'px';
  wrapper.style.height = size + 'px';

  var inner = document.createElement('div');
  inner.className = 'orb-inner orb-state-' + state;
  if (activated) inner.classList.add('breathe');

  var ambient = document.createElement('div');
  ambient.className = 'orb-ambient';
  inner.appendChild(ambient);

  if (activated) {
    for (var r = 0; r < 3; r++) {
      var rip = document.createElement('div');
      rip.className = 'ripple';
      rip.style.animationDelay = (r * 0.35) + 's';
      inner.appendChild(rip);
      rip.addEventListener('animationend', function() { this.remove(); });
    }
    var colors = ['#3ECFB8', '#7C6AEF', '#A78BFA'];
    for (var p = 0; p < 16; p++) {
      var angle = (p / 16) * Math.PI * 2;
      var dist = 60 + Math.random() * 80;
      var part = document.createElement('div');
      part.className = 'particle';
      part.style.setProperty('--px', Math.cos(angle) * dist + 'px');
      part.style.setProperty('--py', Math.sin(angle) * dist + 'px');
      part.style.animationDelay = (Math.random() * 0.3) + 's';
      part.style.background = colors[p % 3];
      part.style.boxShadow = '0 0 6px ' + colors[p % 3];
      inner.appendChild(part);
      part.addEventListener('animationend', function() { this.remove(); });
    }
  }

  var strokeColor, glowColor, orbFilter, reactStroke;
  var rootStyle = getComputedStyle(document.body);
  var irisVar = rootStyle.getPropertyValue('--iris').trim();
  var glowVar = rootStyle.getPropertyValue('--iris-glow').trim();
  switch (state) {
    case 'listening': strokeColor = '#3ECFB8'; glowColor = 'rgba(62,207,184,0.15)'; orbFilter = 'drop-shadow(0 0 25px rgba(62,207,184,0.45))'; break;
    case 'thinking': strokeColor = '#ffffff'; glowColor = 'rgba(255,255,255,0.12)'; orbFilter = 'drop-shadow(0 0 20px rgba(255,255,255,0.35))'; break;
    case 'speaking': strokeColor = '#34D399'; glowColor = 'rgba(52,211,153,0.15)'; orbFilter = 'drop-shadow(0 0 25px rgba(52,211,153,0.45))'; break;
    default: strokeColor = irisVar || '#7C6AEF'; glowColor = glowVar || 'rgba(124,106,239,0.1)'; orbFilter = 'drop-shadow(0 0 15px ' + (glowVar || 'rgba(124,106,239,0.25)') + ')';
  }
  reactStroke = state === 'idle' ? '#ffffff' : strokeColor;
  ambient.style.background = glowColor;

  var svgNS = 'http://www.w3.org/2000/svg';
  var svg = document.createElementNS(svgNS, 'svg');
  svg.setAttribute('viewBox', '0 0 500 500');
  svg.style.width = '100%';
  svg.style.height = '100%';
  svg.style.filter = orbFilter;
  svg.style.transition = 'filter 0.6s ease';

  var defs = document.createElementNS(svgNS, 'defs');
  function makeFilter(id, stdDev) {
    var f = document.createElementNS(svgNS, 'filter');
    f.setAttribute('id', id); f.setAttribute('x', '-20%'); f.setAttribute('y', '-20%');
    f.setAttribute('width', '140%'); f.setAttribute('height', '140%');
    var blur = document.createElementNS(svgNS, 'feGaussianBlur');
    blur.setAttribute('stdDeviation', stdDev); blur.setAttribute('result', 'b');
    f.appendChild(blur);
    var merge = document.createElementNS(svgNS, 'feMerge');
    var mn1 = document.createElementNS(svgNS, 'feMergeNode'); mn1.setAttribute('in', 'b');
    var mn2 = document.createElementNS(svgNS, 'feMergeNode'); mn2.setAttribute('in', 'SourceGraphic');
    merge.appendChild(mn1); merge.appendChild(mn2); f.appendChild(merge);
    return f;
  }
  defs.appendChild(makeFilter('og1', '12'));
  defs.appendChild(makeFilter('og2', '4'));
  var ft = makeFilter('otg', '4');
  ft.setAttribute('x', '-50%'); ft.setAttribute('y', '-50%');
  ft.setAttribute('width', '200%'); ft.setAttribute('height', '200%');
  defs.appendChild(ft);
  svg.appendChild(defs);

  var bgCircle = document.createElementNS(svgNS, 'circle');
  bgCircle.setAttribute('cx', '250'); bgCircle.setAttribute('cy', '250');
  bgCircle.setAttribute('r', '140'); bgCircle.setAttribute('fill', '#7C6AEF');
  bgCircle.setAttribute('fill-opacity', '0.03');
  svg.appendChild(bgCircle);

  var ringCCW = document.createElementNS(svgNS, 'circle');
  ringCCW.setAttribute('cx', '250'); ringCCW.setAttribute('cy', '250');
  ringCCW.setAttribute('r', '150'); ringCCW.setAttribute('fill', 'none');
  ringCCW.setAttribute('stroke', strokeColor); ringCCW.setAttribute('stroke-width', '10');
  ringCCW.setAttribute('filter', 'url(#og1)'); ringCCW.setAttribute('stroke-dasharray', '940 2');
  ringCCW.classList.add('orb-ring-ccw');
  ringCCW.style.transformOrigin = '250px 250px'; ringCCW.style.transition = 'stroke 0.6s ease';
  svg.appendChild(ringCCW);

  var ringCW = document.createElementNS(svgNS, 'circle');
  ringCW.setAttribute('cx', '250'); ringCW.setAttribute('cy', '250');
  ringCW.setAttribute('r', '125'); ringCW.setAttribute('fill', 'none');
  ringCW.setAttribute('stroke', reactStroke); ringCW.setAttribute('stroke-width', '5');
  ringCW.setAttribute('filter', 'url(#og2)'); ringCW.setAttribute('stroke-dasharray', '780 5');
  ringCW.classList.add('orb-ring-cw');
  ringCW.style.transformOrigin = '250px 250px'; ringCW.style.transition = 'stroke 0.6s ease';
  svg.appendChild(ringCW);

  var text = document.createElementNS(svgNS, 'text');
  text.setAttribute('x', '250'); text.setAttribute('y', '262');
  text.setAttribute('text-anchor', 'middle'); text.setAttribute('fill', reactStroke);
  text.setAttribute('filter', 'url(#otg)'); text.classList.add('orb-reactor');
  text.style.fontFamily = '"Space Grotesk",sans-serif'; text.style.fontSize = '46px';
  text.style.fontWeight = '700'; text.style.letterSpacing = '6px';
  text.style.textTransform = 'uppercase'; text.style.userSelect = 'none';
  text.style.transformOrigin = '250px 250px'; text.style.transition = 'fill 0.6s ease';
  text.textContent = 'NALLY';
  svg.appendChild(text);

  var lineCoords = [[250,100,250,116],[250,384,250,400],[100,250,116,250],[384,250,400,250]];
  lineCoords.forEach(function(l) {
    var line = document.createElementNS(svgNS, 'line');
    line.setAttribute('x1',l[0]); line.setAttribute('y1',l[1]);
    line.setAttribute('x2',l[2]); line.setAttribute('y2',l[3]);
    line.setAttribute('stroke', strokeColor); line.setAttribute('stroke-width', '2');
    line.setAttribute('opacity', '0.6'); line.style.transition = 'stroke 0.6s ease';
    svg.appendChild(line);
  });

  inner.appendChild(svg);
  wrapper.appendChild(inner);

  if (!window.matchMedia('(pointer: coarse)').matches) {
    wrapper.addEventListener('mousemove', function(e) {
      var rect = wrapper.getBoundingClientRect();
      var cx = rect.left + rect.width / 2, cy = rect.top + rect.height / 2;
      var dx = (e.clientX - cx) / (rect.width / 2);
      var dy = (e.clientY - cy) / (rect.height / 2);
      wrapper.style.transform = 'perspective(600px) rotateY(' + (Math.max(-1,Math.min(1,dx)) * 1.5) + 'deg) rotateX(' + (-Math.max(-1,Math.min(1,dy)) * 1.5) + 'deg)';
    });
    wrapper.addEventListener('mouseleave', function() {
      wrapper.style.transform = 'perspective(600px) rotateY(0deg) rotateX(0deg)';
    });
  }

  var thinkingEls = [];

  function applyColors(sc, gc, of, rs) {
    ambient.style.background = gc;
    svg.style.filter = of;
    ringCCW.setAttribute('stroke', sc);
    ringCW.setAttribute('stroke', rs);
    text.setAttribute('fill', rs);
    svg.querySelectorAll('line').forEach(function(l) { l.setAttribute('stroke', sc); });
  }

  function addThinkingElements() {
    removeThinkingElements();
    var rp = document.createElement('div');
    rp.className = 'orb-thinking-ring-pulse';
    inner.appendChild(rp);
    thinkingEls.push(rp);
    for (var i = 0; i < 2; i++) {
      var rip = document.createElement('div');
      rip.className = 'orb-thinking-ripple';
      rip.style.animationDelay = (i * 0.4) + 's';
      inner.appendChild(rip);
      thinkingEls.push(rip);
    }
  }

  function removeThinkingElements() {
    thinkingEls.forEach(function(el) { el.remove(); });
    thinkingEls = [];
  }

  return {
    el: wrapper,
    inner: inner,
    svg: svg,
    ambient: ambient,
    ringCW: ringCW,
    ringCCW: ringCCW,
    text: text,
    setState: function(newState) {
      state = newState;
      inner.className = 'orb-inner orb-state-' + state;
      if (activated) inner.classList.add('breathe');
      if (state === 'thinking') { addThinkingElements(); } else { removeThinkingElements(); }
      var sc, gc, of, rs;
      var rs2 = getComputedStyle(document.body);
      var iv = rs2.getPropertyValue('--iris').trim();
      var gv = rs2.getPropertyValue('--iris-glow').trim();
      switch (state) {
        case 'listening': sc='#3ECFB8'; gc='rgba(62,207,184,0.15)'; of='drop-shadow(0 0 25px rgba(62,207,184,0.45))'; break;
        case 'thinking': sc='#ffffff'; gc='rgba(255,255,255,0.12)'; of='drop-shadow(0 0 20px rgba(255,255,255,0.35))'; break;
        case 'speaking': sc='#34D399'; gc='rgba(52,211,153,0.15)'; of='drop-shadow(0 0 25px rgba(52,211,153,0.45))'; break;
        default: sc=iv||'#7C6AEF'; gc=gv||'rgba(124,106,239,0.1)'; of='drop-shadow(0 0 15px '+(gv||'rgba(124,106,239,0.25)')+')';
      }
      rs = state === 'idle' ? '#ffffff' : sc;
      applyColors(sc, gc, of, rs);
    },
    pulseWord: function(isEmphasis) {
      inner.classList.remove('word-pulse', 'emphasis-flare');
      void inner.offsetWidth;
      inner.classList.add(isEmphasis ? 'emphasis-flare' : 'word-pulse');
    },
    burstParticles: function(count, color) {
      for (var i = 0; i < (count || 8); i++) {
        var angle = (i / count) * Math.PI * 2;
        var dist = 40 + Math.random() * 60;
        var part = document.createElement('div');
        part.className = 'particle';
        part.style.setProperty('--px', Math.cos(angle) * dist + 'px');
        part.style.setProperty('--py', Math.sin(angle) * dist + 'px');
        part.style.animationDelay = '0s';
        part.style.background = color || '#34D399';
        part.style.boxShadow = '0 0 8px ' + (color || '#34D399');
        inner.appendChild(part);
        (function(el) { setTimeout(function() { el.remove(); }, 1100); })(part);
      }
    }
  };
};
