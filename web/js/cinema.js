// ─── Cinema Engine v2 — Cosmic Dust ─────────────────
// Perlin noise flow field, bokeh particles, motion trails, additive blending

function CinemaEngine(canvasId) {
  var canvas = document.getElementById(canvasId);
  if (!canvas) return null;
  var ctx = canvas.getContext('2d');

  var W = 0, H = 0;
  var particles = [];
  var textPoints = [];
  var phase = 'idle';
  var convergeStart = 0;
  var explodeStart = 0;
  var noiseOffset = 0;
  var raf = null;
  var onPhaseDone = null;

  // ─── Perlin Noise (simple 2D) ───────────────────
  var perm = [];
  function initNoise() {
    var p = [];
    for (var i = 0; i < 256; i++) p[i] = i;
    for (var i = 255; i > 0; i--) {
      var j = Math.floor(Math.random() * (i + 1));
      var t = p[i]; p[i] = p[j]; p[j] = t;
    }
    for (var i = 0; i < 512; i++) perm[i] = p[i & 255];
  }

  function fade(t) { return t * t * t * (t * (t * 6 - 15) + 10); }
  function lerp(a, b, t) { return a + t * (b - a); }

  function grad(hash, x, y) {
    var h = hash & 3;
    var u = h < 2 ? x : y;
    var v = h < 2 ? y : x;
    return ((h & 1) === 0 ? u : -u) + ((h & 2) === 0 ? v : -v);
  }

  function noise2D(x, y) {
    var X = Math.floor(x) & 255;
    var Y = Math.floor(y) & 255;
    var xf = x - Math.floor(x);
    var yf = y - Math.floor(y);
    var u = fade(xf);
    var v = fade(yf);
    var aa = perm[perm[X] + Y];
    var ab = perm[perm[X] + Y + 1];
    var ba = perm[perm[X + 1] + Y];
    var bb = perm[perm[X + 1] + Y + 1];
    return lerp(
      lerp(grad(aa, xf, yf), grad(ba, xf - 1, yf), u),
      lerp(grad(ab, xf, yf - 1), grad(bb, xf - 1, yf - 1), u),
      v
    );
  }

  // ─── Particle ───────────────────────────────────
  function Particle(layer) {
    this.layer = layer; // 0=far, 1=medium, 2=near
    this.reset(true);
  }

  Particle.prototype.reset = function(init) {
    this.x = Math.random() * W;
    this.y = Math.random() * H;
    this.vx = 0;
    this.vy = 0;
    this.age = 0;
    this.maxAge = (8 + Math.random() * 12) * 60; // 8-20s at 60fps

    // Layer properties
    if (this.layer === 0) {
      this.size = 0.3 + Math.random() * 0.8;
      this.alphaMax = 0.08 + Math.random() * 0.15;
      this.speedMul = 0.25;
      this.hueShift = Math.random() * 30 - 15;
    } else if (this.layer === 1) {
      this.size = 0.6 + Math.random() * 1.8;
      this.alphaMax = 0.15 + Math.random() * 0.35;
      this.speedMul = 0.8 + Math.random() * 0.4;
      this.hueShift = Math.random() * 40 - 20;
    } else {
      this.size = 1.5 + Math.random() * 3;
      this.alphaMax = 0.2 + Math.random() * 0.4;
      this.speedMul = 1.2 + Math.random() * 0.8;
      this.hueShift = Math.random() * 50 - 25;
    }

    // Color: warm purple/gold spectrum
    this.hue = 260 + Math.random() * 40 + this.hueShift; // purple base
    if (Math.random() < 0.3) this.hue = 30 + Math.random() * 30 + this.hueShift; // gold variant
    this.sat = 50 + Math.random() * 40;
    this.lit = 55 + Math.random() * 30;

    this.alpha = 0;
    this.targetX = 0;
    this.targetY = 0;
    this.hasTarget = false;
  };

  Particle.prototype.update = function(t) {
    this.age++;

    // Lifespan fade
    var lifeRatio = this.age / this.maxAge;
    if (lifeRatio < 0.15) {
      this.alpha = this.alphaMax * (lifeRatio / 0.15);
    } else if (lifeRatio > 0.7) {
      this.alpha = this.alphaMax * (1 - (lifeRatio - 0.7) / 0.3);
    } else {
      this.alpha = this.alphaMax;
    }

    // Dead?
    if (this.age >= this.maxAge) {
      this.reset(false);
      return;
    }

    if (phase === 'drift' || phase === 'converge') {
      // Sample Perlin noise flow field
      var scale = 0.002;
      var n = noise2D(this.x * scale + noiseOffset, this.y * scale + noiseOffset * 0.7);
      var angle = n * Math.PI * 4;

      var noiseForce = 0.15 * this.speedMul;
      this.vx += Math.cos(angle) * noiseForce;
      this.vy += Math.sin(angle) * noiseForce;

      // Converge: vortex pull toward target
      if (phase === 'converge' && this.hasTarget) {
        var dx = this.targetX - this.x;
        var dy = this.targetY - this.y;
        var dist = Math.sqrt(dx * dx + dy * dy) || 1;
        var ease = Math.min(1, (t - convergeStart) / 3000);
        var pull = 0.015 * ease * this.speedMul;
        
        // Radial pull
        this.vx += (dx / dist) * pull * 4;
        this.vy += (dy / dist) * pull * 4;
        
        // Swirl pull (tangential) for vortex effect
        var swirl = (1 - ease) * 1.5 * this.speedMul;
        this.vx += (-dy / dist) * swirl;
        this.vy += (dx / dist) * swirl;
      }

      // Damping
      this.vx *= 0.94;
      this.vy *= 0.94;

      // Speed cap
      var spd = Math.sqrt(this.vx * this.vx + this.vy * this.vy);
      var maxSpd = (phase === 'converge' ? 3 : 1.5) * this.speedMul;
      if (spd > maxSpd) {
        this.vx = (this.vx / spd) * maxSpd;
        this.vy = (this.vy / spd) * maxSpd;
      }

      this.x += this.vx;
      this.y += this.vy;

      // Wrap edges
      if (this.x < -20) this.x = W + 20;
      if (this.x > W + 20) this.x = -20;
      if (this.y < -20) this.y = H + 20;
      if (this.y > H + 20) this.y = -20;
    }
    else if (phase === 'explode') {
      var elapsed = t - explodeStart;
      var ex = this.x - W / 2;
      var ey = this.y - H / 2;
      var dist = Math.sqrt(ex * ex + ey * ey) || 1;
      
      // Supernova expansion force
      var force = Math.min(15, 3 + elapsed * 0.01);
      this.vx += (ex / dist) * force * 0.25;
      this.vy += (ey / dist) * force * 0.25;
      
      // Propagation shockwave ring
      var waveRadius = elapsed * 0.8;
      var waveDist = Math.abs(dist - waveRadius);
      if (waveDist < 60) {
        var push = (1 - waveDist / 60) * 2.5;
        this.vx += (ex / dist) * push;
        this.vy += (ey / dist) * push;
      }
      
      this.vx *= 0.95;
      this.vy *= 0.95;
      this.x += this.vx;
      this.y += this.vy;
    }
  };

  Particle.prototype.draw = function(ctx) {
    if (this.alpha <= 0.005) return;
    var c = `hsl(${this.hue}, ${this.sat}%, ${this.lit}%)`;

    // Soft bokeh: radial gradient circle
    var r = this.size;
    var grad = ctx.createRadialGradient(this.x, this.y, 0, this.x, this.y, r);
    grad.addColorStop(0, c);
    grad.addColorStop(0.4, c.replace(')', ', 0.6)').replace('hsl', 'hsla'));
    grad.addColorStop(1, 'rgba(0,0,0,0)');

    ctx.globalAlpha = this.alpha;
    ctx.globalCompositeOperation = 'lighter';
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.arc(this.x, this.y, r, 0, Math.PI * 2);
    ctx.fill();
  };

  // ─── Text Sampling ──────────────────────────────
  function sampleText(text, fontSize, fontFamily) {
    var oc = document.createElement('canvas');
    var octx = oc.getContext('2d');
    oc.width = W;
    oc.height = H;
    octx.fillStyle = '#000';
    octx.fillRect(0, 0, W, H);
    octx.fillStyle = '#fff';
    octx.font = '900 ' + fontSize + 'px ' + fontFamily;
    octx.textAlign = 'center';
    octx.textBaseline = 'middle';
    octx.fillText(text, W / 2, H / 2);
    var imgData = octx.getImageData(0, 0, W, H).data;
    var points = [];
    var step = Math.max(3, Math.floor(4 * (fontSize / 80)));
    for (var y = 0; y < H; y += step) {
      for (var x = 0; x < W; x += step) {
        if (imgData[(y * W + x) * 4 + 3] > 128) {
          points.push({ x: x, y: y });
        }
      }
    }
    return points;
  }

  // ─── Assign Targets ─────────────────────────────
  function assignTargets() {
    var shuffled = textPoints.slice();
    for (var i = shuffled.length - 1; i > 0; i--) {
      var j = Math.floor(Math.random() * (i + 1));
      var tmp = shuffled[i]; shuffled[i] = shuffled[j]; shuffled[j] = tmp;
    }
    var len = Math.min(particles.length, shuffled.length);
    for (var i = 0; i < len; i++) {
      particles[i].targetX = shuffled[i].x;
      particles[i].targetY = shuffled[i].y;
      particles[i].hasTarget = true;
    }
    for (var i = len; i < particles.length; i++) {
      particles[i].targetX = W / 2 + (Math.random() - 0.5) * W * 0.4;
      particles[i].targetY = H / 2 + (Math.random() - 0.5) * H * 0.3;
      particles[i].hasTarget = true;
    }
  }

  // ─── Init ───────────────────────────────────────
  function initParticles() {
    particles = [];
    for (var i = 0; i < 500; i++) particles.push(new Particle(0)); // far
    for (var i = 0; i < 1100; i++) particles.push(new Particle(1)); // medium
    for (var i = 0; i < 250; i++) particles.push(new Particle(2)); // near
  }

  // ─── Main Loop ──────────────────────────────────
  function loop(t) {
    // Motion trail: semi-transparent fill instead of clear
    ctx.globalCompositeOperation = 'source-over';
    ctx.globalAlpha = 1;
    ctx.fillStyle = 'rgba(0, 0, 0, 0.045)';
    ctx.fillRect(0, 0, W, H);

    noiseOffset += 0.0015;

    for (var i = 0; i < particles.length; i++) {
      particles[i].update(t);
      particles[i].draw(ctx);
    }

    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = 'source-over';

    raf = requestAnimationFrame(loop);
  }

  // ─── Resize ─────────────────────────────────────
  function resize() {
    var dpr = window.devicePixelRatio || 1;
    W = window.innerWidth;
    H = window.innerHeight;
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    canvas.style.width = W + 'px';
    canvas.style.height = H + 'px';
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  // ─── Public API ─────────────────────────────────
  return {
    init: function() {
      resize();
      window.addEventListener('resize', resize);
      initNoise();
      textPoints = sampleText('NALLY', Math.min(160, W * 0.18), 'Orbitron, sans-serif');
      initParticles();
      phase = 'drift';
      raf = requestAnimationFrame(loop);
    },

    startConverge: function(callback) {
      phase = 'converge';
      convergeStart = performance.now();
      onPhaseDone = callback || null;
      textPoints = sampleText('NALLY', Math.min(160, W * 0.18), 'Orbitron, sans-serif');
      assignTargets();
    },

    startExplode: function() {
      phase = 'explode';
      explodeStart = performance.now();
      // Fade canvas out after 2s
      canvas.style.transition = 'opacity 1.5s ease';
      canvas.style.opacity = '0';
    },

    setPhase: function(p) { phase = p; },
    getPhase: function() { return phase; },

    destroy: function() {
      if (raf) cancelAnimationFrame(raf);
      window.removeEventListener('resize', resize);
    },

    resize: resize
  };
}
