// ─── Cinema Engine v6 — WebGL + Canvas 2D Fallback ──
// GPU-accelerated noise, text-locking, glitch distortion, ambient particles
// WebGL for performance, Canvas 2D for compatibility

function CinemaEngine(canvasId) {
  var canvas = document.getElementById(canvasId);
  if (!canvas) return null;

  // ─── Try WebGL ─────────────────────────────────
  var gl = canvas.getContext('webgl', { alpha: false, antialias: false }) ||
           canvas.getContext('experimental-webgl', { alpha: false, antialias: false });

  if (gl) {
    return new WebGLCinema(canvas, gl);
  }

  // ─── Fallback: Canvas 2D ───────────────────────
  return new Canvas2DCinema(canvas);
}

// ═══════════════════════════════════════════════════
// WebGL Renderer
// ═══════════════════════════════════════════════════
function WebGLCinema(canvas, gl) {
  var W = 0, H = 0;
  var phase = 'idle';
  var phaseStart = 0;
  var raf = null;
  var startTime = performance.now();
  var frameCount = 0;

  // Cursor state
  var cursorX = -1000, cursorY = -1000;
  var cursorListenerActive = false;

  // Text mask
  var textMaskCanvas = document.createElement('canvas');
  var textMaskCtx = textMaskCanvas.getContext('2d');
  var textMaskTexture = null;

  // ─── Shaders ───────────────────────────────────
  var VERT_SRC = [
    'attribute vec2 a_pos;',
    'void main() { gl_Position = vec4(a_pos, 0.0, 1.0); }'
  ].join('\n');

  var FRAG_SRC = [
    'precision mediump float;',
    'uniform float u_time;',
    'uniform vec2 u_resolution;',
    'uniform float u_phase;',       // 0=static, 1=resolve, 2=stable, 3=glitch, 4=settle, 5=ambient
    'uniform float u_resolve;',     // 0→1 during resolve
    'uniform float u_glitch;',      // 0→1→0 during glitch
    'uniform vec2 u_cursor;',
    'uniform sampler2D u_textMask;',
    '',
    'float hash(vec2 p) {',
    '  return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);',
    '}',
    '',
    'float noise(vec2 p) {',
    '  vec2 i = floor(p);',
    '  vec2 f = fract(p);',
    '  f = f * f * (3.0 - 2.0 * f);',
    '  float a = hash(i);',
    '  float b = hash(i + vec2(1.0, 0.0));',
    '  float c = hash(i + vec2(0.0, 1.0));',
    '  float d = hash(i + vec2(1.0, 1.0));',
    '  return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);',
    '}',
    '',
    'void main() {',
    '  vec2 uv = gl_FragCoord.xy / u_resolution;',
    '',
    '  // Glitch: UV distortion',
    '  if (u_glitch > 0.01) {',
    '    float slice = step(0.85, fract(uv.y * 12.0 + u_time * 2.0));',
    '    float offset = slice * u_glitch * 0.12 * sin(u_time * 50.0);',
    '    uv.x += offset;',
    '    uv.y += slice * u_glitch * 0.02 * cos(u_time * 30.0);',
    '  }',
    '',
    '  // Grid for noise characters',
    '  vec2 grid = floor(uv * vec2(50.0, 25.0));',
    '  float charRand = hash(grid);',
    '',
    '  // Noise character visibility',
    '  float noiseVis = 0.0;',
    '  if (u_phase < 0.5) {',
    '    // Static: full noise',
    '    noiseVis = step(0.3, charRand);',
    '  } else if (u_phase < 1.5) {',
    '    // Resolve: noise thins based on u_resolve',
    '    float threshold = 0.3 + u_resolve * 0.4;',
    '    noiseVis = step(threshold, charRand) * (1.0 - u_resolve * 0.6);',
    '  } else if (u_phase < 2.5) {',
    '    // Stable: minimal noise',
    '    noiseVis = step(0.92, charRand) * 0.3;',
    '  } else if (u_phase < 3.5) {',
    '    // Glitch: noise burst',
    '    noiseVis = step(0.6, charRand) * u_glitch * 0.5;',
    '  } else if (u_phase < 4.5) {',
    '    // Settle: fading noise',
    '    noiseVis = step(0.95, charRand) * 0.15;',
    '  } else {',
    '    // Ambient: faint scattered chars',
    '    noiseVis = step(0.97, charRand) * 0.2;',
    '    // Cursor brightness boost',
    '    float cdist = length((gl_FragCoord.xy - u_cursor) / u_resolution);',
    '    noiseVis *= 1.0 + (1.0 - smoothstep(0.0, 0.15, cdist)) * 2.0;',
    '  }',
    '',
    '  // Text mask',
    '  float mask = texture2D(u_textMask, uv).r;',
    '',
    '  // Text visibility based on phase',
    '  float textVis = 0.0;',
    '  if (u_phase > 0.5 && u_phase < 3.5) {',
    '    // Resolve: text fades in with u_resolve',
    '    textVis = mask * u_resolve;',
    '  } else if (u_phase >= 3.5 && u_phase < 4.5) {',
    '    // Settle: text visible',
    '    textVis = mask;',
    '  } else if (u_phase >= 4.5) {',
    '    // Ambient: text faded',
    '    textVis = mask * 0.3;',
    '  }',
    '',
    '  // Compose',
    '  float noiseColor = noiseVis * (0.5 + charRand * 0.3);',
    '  float textColor = textVis * 0.9;',
    '  float val = max(noiseColor, textColor);',
    '',
    '  // Holographic tint',
    '  vec3 color = vec3(val);',
    '  if (textVis > 0.1) {',
    '    color += vec3(0.05, 0.08, 0.15) * textVis; // subtle blue tint',
    '  }',
    '',
    '  // Glitch RGB split on text',
    '  if (u_glitch > 0.1 && textVis > 0.1) {',
    '    float splitR = texture2D(u_textMask, uv + vec2(u_glitch * 0.01, 0.0)).r;',
    '    float splitB = texture2D(u_textMask, uv - vec2(u_glitch * 0.01, 0.0)).r;',
    '    color.r = max(color.r, splitR * u_glitch * 0.8);',
    '    color.b = max(color.b, splitB * u_glitch * 0.6);',
    '  }',
    '',
    '  // Scanlines',
    '  float scanline = 0.95 + 0.05 * sin(gl_FragCoord.y * 2.0);',
    '  val *= scanline;',
    '',
    '  // Sweep line',
    '  float sweepY = fract(u_time * 0.15) * 1.2 - 0.1;',
    '  float sweep = 1.0 - smoothstep(0.0, 0.015, abs(uv.y - sweepY));',
    '  if (u_phase < 2.5) {',
    '    color += vec3(0.3, 0.25, 0.5) * sweep * 0.4;',
    '  }',
    '',
    '  // Vignette',
    '  float vig = 1.0 - smoothstep(0.3, 1.0, length(uv - 0.5) * 1.4);',
    '  color *= vig;',
    '',
    '  gl_FragColor = vec4(color * val, 1.0);',
    '}'
  ].join('\n');

  // ─── Ambient Particle Shader ───────────────────
  var AMBIENT_VERT_SRC = [
    'attribute vec2 a_pos;',
    'attribute float a_alpha;',
    'attribute float a_size;',
    'uniform vec2 u_resolution;',
    'varying float v_alpha;',
    'void main() {',
    '  vec2 clip = (a_pos / u_resolution) * 2.0 - 1.0;',
    '  clip.y = -clip.y;',
    '  gl_Position = vec4(clip, 0.0, 1.0);',
    '  gl_PointSize = a_size;',
    '  v_alpha = a_alpha;',
    '}'
  ].join('\n');

  var AMBIENT_FRAG_SRC = [
    'precision mediump float;',
    'varying float v_alpha;',
    'void main() {',
    '  float d = length(gl_PointCoord - 0.5);',
    '  if (d > 0.5) discard;',
    '  float a = v_alpha * (1.0 - d * 2.0);',
    '  gl_FragColor = vec4(0.5, 0.6, 0.8, a);',
    '}'
  ].join('\n');

  // ─── Compile Helper ────────────────────────────
  function compileShader(src, type) {
    var s = gl.createShader(type);
    gl.shaderSource(s, src);
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
      console.error('Shader error:', gl.getShaderInfoLog(s));
      gl.deleteShader(s);
      return null;
    }
    return s;
  }

  function createProgram(vertSrc, fragSrc) {
    var vs = compileShader(vertSrc, gl.VERTEX_SHADER);
    var fs = compileShader(fragSrc, gl.FRAGMENT_SHADER);
    var p = gl.createProgram();
    gl.attachShader(p, vs);
    gl.attachShader(p, fs);
    gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) {
      console.error('Program error:', gl.getProgramInfoLog(p));
      return null;
    }
    return p;
  }

  // ─── Init Programs ─────────────────────────────
  var mainProg = createProgram(VERT_SRC, FRAG_SRC);
  var mainLocs = {
    a_pos: gl.getAttribLocation(mainProg, 'a_pos'),
    u_time: gl.getUniformLocation(mainProg, 'u_time'),
    u_resolution: gl.getUniformLocation(mainProg, 'u_resolution'),
    u_phase: gl.getUniformLocation(mainProg, 'u_phase'),
    u_resolve: gl.getUniformLocation(mainProg, 'u_resolve'),
    u_glitch: gl.getUniformLocation(mainProg, 'u_glitch'),
    u_cursor: gl.getUniformLocation(mainProg, 'u_cursor'),
    u_textMask: gl.getUniformLocation(mainProg, 'u_textMask')
  };

  var ambientProg = createProgram(AMBIENT_VERT_SRC, AMBIENT_FRAG_SRC);
  var ambientLocs = {
    a_pos: gl.getAttribLocation(ambientProg, 'a_pos'),
    a_alpha: gl.getAttribLocation(ambientProg, 'a_alpha'),
    a_size: gl.getAttribLocation(ambientProg, 'a_size'),
    u_resolution: gl.getUniformLocation(ambientProg, 'u_resolution')
  };

  // ─── Fullscreen Quad ───────────────────────────
  var quadBuf = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, quadBuf);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([
    -1, -1,  1, -1,  -1, 1,
    -1,  1,  1, -1,   1, 1
  ]), gl.STATIC_DRAW);

  // ─── Text Mask Texture ─────────────────────────
  function updateTextMask() {
    textMaskCanvas.width = W;
    textMaskCanvas.height = H;
    textMaskCtx.fillStyle = '#000';
    textMaskCtx.fillRect(0, 0, W, H);
    textMaskCtx.fillStyle = '#fff';
    var fontSize = Math.min(240, W * 0.25);
    textMaskCtx.font = '900 ' + fontSize + 'px "Space Grotesk", sans-serif';
    textMaskCtx.textAlign = 'center';
    textMaskCtx.textBaseline = 'middle';
    textMaskCtx.fillText('NALLY', W / 2, H / 2);

    if (!textMaskTexture) {
      textMaskTexture = gl.createTexture();
    }
    gl.bindTexture(gl.TEXTURE_2D, textMaskTexture);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, textMaskCanvas);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  }

  // ─── Ambient Particles ─────────────────────────
  var ambientParticles = [];
  var ambientBuf = null;

  function initAmbientParticles() {
    ambientParticles = [];
    var count = isMobile ? 20 : 35;
    for (var i = 0; i < count; i++) {
      ambientParticles.push({
        x: Math.random() * W,
        y: Math.random() * H,
        vx: 0,
        vy: 0,
        alpha: 0.1 + Math.random() * 0.08,
        size: 2 + Math.random() * 3,
        flickerT: Math.random() * 100,
        flickerSpeed: 0.02 + Math.random() * 0.04
      });
    }
    // Create buffer
    ambientBuf = gl.createBuffer();
  }

  function updateAmbientParticles() {
    for (var i = 0; i < ambientParticles.length; i++) {
      var p = ambientParticles[i];
      p.flickerT += p.flickerSpeed;

      // Cursor repulsion
      if (cursorX > 0 && cursorY > 0) {
        var dx = p.x - cursorX;
        var dy = p.y - cursorY;
        var dist = Math.sqrt(dx * dx + dy * dy) || 1;
        if (dist < 120) {
          var repel = (1 - dist / 120) * 1.0;
          p.vx += (dx / dist) * repel;
          p.vy += (dy / dist) * repel;
        }
      }

      // Gentle drift
      p.vx += (Math.random() - 0.5) * 0.02;
      p.vy += (Math.random() - 0.5) * 0.02;
      p.vx *= 0.97;
      p.vy *= 0.97;
      p.x += p.vx;
      p.y += p.vy;

      // Wrap
      if (p.x < -20) p.x = W + 20;
      if (p.x > W + 20) p.x = -20;
      if (p.y < -20) p.y = H + 20;
      if (p.y > H + 20) p.y = -20;
    }
  }

  function drawAmbientParticles() {
    if (ambientParticles.length === 0) return;
    updateAmbientParticles();

    var data = new Float32Array(ambientParticles.length * 4);
    for (var i = 0; i < ambientParticles.length; i++) {
      var p = ambientParticles[i];
      var a = p.alpha * (0.7 + Math.sin(p.flickerT) * 0.3);
      data[i * 4 + 0] = p.x;
      data[i * 4 + 1] = p.y;
      data[i * 4 + 2] = a;
      data[i * 4 + 3] = p.size;
    }

    gl.useProgram(ambientProg);
    gl.bindBuffer(gl.ARRAY_BUFFER, ambientBuf);
    gl.bufferData(gl.ARRAY_BUFFER, data, gl.DYNAMIC_DRAW);

    gl.enableVertexAttribArray(ambientLocs.a_pos);
    gl.vertexAttribPointer(ambientLocs.a_pos, 2, gl.FLOAT, false, 16, 0);
    gl.enableVertexAttribArray(ambientLocs.a_alpha);
    gl.vertexAttribPointer(ambientLocs.a_alpha, 1, gl.FLOAT, false, 16, 8);
    gl.enableVertexAttribArray(ambientLocs.a_size);
    gl.vertexAttribPointer(ambientLocs.a_size, 1, gl.FLOAT, false, 16, 12);

    gl.uniform2f(ambientLocs.u_resolution, W, H);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE);
    gl.drawArrays(gl.POINTS, 0, ambientParticles.length);
    gl.disable(gl.BLEND);
  }

  // ─── Device Detection ──────────────────────────
  var isMobile = window.innerWidth < 768;

  // ─── Phase Timing ──────────────────────────────
  var phaseTimers = {
    static: 500,     // 0→0.5s
    resolve: 1500,   // 0.5→1.5s
    stable: 2600,    // 1.5→2.6s
    glitch: 2900,    // 2.6→2.9s
    settle: 3200,    // 2.9→3.2s
    ambient: 4000    // 3.2→4.0s+
  };

  function getPhaseFloat() {
    var p = phase;
    if (p === 'static') return 0;
    if (p === 'resolve') return 1;
    if (p === 'stable') return 2;
    if (p === 'glitch') return 3;
    if (p === 'settle') return 4;
    if (p === 'ambient') return 5;
    return 0;
  }

  function getResolveProgress() {
    if (phase !== 'resolve') return phase === 'stable' || phase === 'settle' || phase === 'ambient' ? 1.0 : 0.0;
    var elapsed = performance.now() - phaseStart;
    return Math.min(1, elapsed / 1000);
  }

  function getGlitchIntensity() {
    if (phase !== 'glitch') return 0;
    var elapsed = performance.now() - phaseStart;
    var t = Math.min(1, elapsed / 300);
    // Spike then fade
    return t < 0.3 ? t / 0.3 : 1 - (t - 0.3) / 0.7;
  }

  // ─── Render Loop ───────────────────────────────
  function render() {
    var t = (performance.now() - startTime) * 0.001;

    gl.viewport(0, 0, W, H);
    gl.clearColor(0, 0, 0, 1);
    gl.clear(gl.COLOR_BUFFER_BIT);

    // Draw main noise + text shader
    gl.useProgram(mainProg);
    gl.bindBuffer(gl.ARRAY_BUFFER, quadBuf);
    gl.enableVertexAttribArray(mainLocs.a_pos);
    gl.vertexAttribPointer(mainLocs.a_pos, 2, gl.FLOAT, false, 0, 0);

    gl.uniform1f(mainLocs.u_time, t);
    gl.uniform2f(mainLocs.u_resolution, W, H);
    gl.uniform1f(mainLocs.u_phase, getPhaseFloat());
    gl.uniform1f(mainLocs.u_resolve, getResolveProgress());
    gl.uniform1f(mainLocs.u_glitch, getGlitchIntensity());
    gl.uniform2f(mainLocs.u_cursor, cursorX, H - cursorY);

    // Bind text mask texture
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, textMaskTexture);
    gl.uniform1i(mainLocs.u_textMask, 0);

    gl.drawArrays(gl.TRIANGLES, 0, 6);

    // Draw ambient particles (post-cinematic)
    if (phase === 'ambient') {
      drawAmbientParticles();
    }

    frameCount++;
    raf = requestAnimationFrame(render);
  }

  // ─── Resize ────────────────────────────────────
  function resize() {
    var dpr = Math.min(window.devicePixelRatio || 1, 2);
    W = window.innerWidth;
    H = window.innerHeight;
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    canvas.style.width = W + 'px';
    canvas.style.height = H + 'px';
    gl.viewport(0, 0, W * dpr, H * dpr);
    // Update resolution uniform for correct aspect ratio
    // Shader uses gl_FragCoord which is in device pixels
    // But our text mask is in CSS pixels — need to scale
    updateTextMask();
  }

  // ─── Cursor ────────────────────────────────────
  function onCursorMove(e) { cursorX = e.clientX; cursorY = e.clientY; }
  function onCursorLeave() { cursorX = -1000; cursorY = -1000; }

  // ─── Public API ────────────────────────────────
  return {
    init: function() {
      resize();
      window.addEventListener('resize', resize);
      updateTextMask();
      phase = 'static';
      phaseStart = performance.now();
      startTime = performance.now();
      raf = requestAnimationFrame(render);
    },

    startResolve: function() {
      phase = 'resolve';
      phaseStart = performance.now();
    },

    startStable: function() {
      phase = 'stable';
      phaseStart = performance.now();
    },

    startGlitch: function() {
      phase = 'glitch';
      phaseStart = performance.now();
      canvas.style.transition = 'opacity 0.5s ease';
      canvas.style.opacity = '0';
    },

    startSettle: function() {
      phase = 'settle';
      phaseStart = performance.now();
    },

    startAmbient: function() {
      phase = 'ambient';
      phaseStart = performance.now();
      canvas.style.transition = 'opacity 0.3s ease';
      canvas.style.opacity = '1';
      initAmbientParticles();
      if (!cursorListenerActive) {
        window.addEventListener('mousemove', onCursorMove);
        window.addEventListener('mouseleave', onCursorLeave);
        cursorListenerActive = true;
      }
    },

    setPhase: function(p) { phase = p; },
    getPhase: function() { return phase; },

    destroy: function() {
      if (raf) cancelAnimationFrame(raf);
      window.removeEventListener('resize', resize);
      if (cursorListenerActive) {
        window.removeEventListener('mousemove', onCursorMove);
        window.removeEventListener('mouseleave', onCursorLeave);
      }
    },

    resize: resize
  };
}

// ═══════════════════════════════════════════════════
// Canvas 2D Fallback
// ═══════════════════════════════════════════════════
function Canvas2DCinema(canvas) {
  var ctx = canvas.getContext('2d');
  var W = 0, H = 0;
  var phase = 'idle';
  var phaseStart = 0;
  var raf = null;
  var frameCount = 0;

  var CHARS = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ@#$%&*!?<>{}[]|/\\';
  var isMobile = window.innerWidth < 768;
  var isLowEnd = (navigator.hardwareConcurrency || 8) <= 4 ||
                 (navigator.deviceMemory || 8) <= 4;

  var DENSITY_STATIC = isLowEnd ? 60 : isMobile ? 100 : 180;
  var DENSITY_RESOLVE = isLowEnd ? 30 : isMobile ? 50 : 80;
  var DENSITY_AMBIENT = isLowEnd ? 8 : isMobile ? 12 : 20;

  var textPoints = [];
  var textFontSize = 0;
  var scanlineY = -20;
  var scanlineSpeed = isMobile ? 4 : 6;

  var ambientChars = [];
  var cursorX = -1000, cursorY = -1000;
  var cursorListenerActive = false;

  function sampleTextLayout() {
    var fontSize = Math.min(240, W * 0.25);
    textFontSize = fontSize;
    var oc = document.createElement('canvas');
    var octx = oc.getContext('2d');
    oc.width = W; oc.height = H;
    octx.fillStyle = '#000'; octx.fillRect(0, 0, W, H);
    octx.fillStyle = '#fff';
    octx.font = '900 ' + fontSize + 'px "Space Grotesk", sans-serif';
    octx.textAlign = 'center'; octx.textBaseline = 'middle';
    octx.fillText('NALLY', W / 2, H / 2);
    var imgData = octx.getImageData(0, 0, W, H).data;
    var step = Math.max(4, Math.floor(5 * (fontSize / 80)));
    var pts = [];
    var word = 'NALLY';
    var letterWidth = fontSize * 0.65;
    var startX = W / 2 - (letterWidth * 5) / 2 + letterWidth / 2;
    for (var y = 0; y < H; y += step) {
      for (var x = 0; x < W; x += step) {
        if (imgData[(y * W + x) * 4 + 3] > 128) {
          var charIdx = Math.floor((x - (startX - letterWidth / 2)) / letterWidth);
          charIdx = Math.max(0, Math.min(4, charIdx));
          pts.push({
            x: x, y: y, char: word[charIdx], letterIdx: charIdx,
            locked: false, lockT: 0,
            flickerChar: CHARS[Math.floor(Math.random() * CHARS.length)]
          });
        }
      }
    }
    textPoints = pts;
  }

  function initAmbient() {
    ambientChars = [];
    for (var i = 0; i < DENSITY_AMBIENT; i++) {
      ambientChars.push({
        x: Math.random() * W, y: Math.random() * H,
        char: CHARS[Math.floor(Math.random() * CHARS.length)],
        alpha: 0.03 + Math.random() * 0.08,
        vx: 0, vy: 0, flickerT: Math.random() * 100,
        flickerSpeed: 0.02 + Math.random() * 0.04
      });
    }
  }

  function draw(t) {
    ctx.globalCompositeOperation = 'source-over';
    ctx.globalAlpha = 1;
    if (phase === 'ambient') ctx.fillStyle = 'rgba(0,0,0,0.12)';
    else if (phase === 'static') ctx.fillStyle = 'rgba(0,0,0,0.85)';
    else ctx.fillStyle = 'rgba(0,0,0,0.7)';
    ctx.fillRect(0, 0, W, H);

    scanlineY += scanlineSpeed;
    if (scanlineY > H + 20) scanlineY = -20;
    frameCount++;

    if (phase === 'static') {
      drawNoiseChars(DENSITY_STATIC, 1.0);
      drawScanlines(0.15);
      drawSweepLine(0.6);
    } else if (phase === 'resolve') {
      var elapsed = t - phaseStart;
      var progress = Math.min(1, elapsed / 1500);
      var bgDensity = Math.floor(DENSITY_RESOLVE * (1 - progress * 0.6));
      drawNoiseChars(bgDensity, 0.5 * (1 - progress));
      drawTextChars(progress, progress);
      drawScanlines(0.1 * (1 - progress * 0.5));
      drawSweepLine(0.4 * (1 - progress));
    } else if (phase === 'stable') {
      drawTextChars(1.0, 1.0);
      drawScanlines(0.05);
    } else if (phase === 'glitch') {
      drawNoiseChars(40, 0.4);
      drawScanlines(0.25);
    } else if (phase === 'settle') {
      drawTextChars(1.0, 1.0);
      drawScanlines(0.03);
    } else if (phase === 'ambient') {
      drawAmbientChars();
      drawScanlines(0.02);
    }

    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = 'source-over';
    raf = requestAnimationFrame(function() { draw(performance.now()); });
  }

  function drawNoiseChars(count, alpha) {
    ctx.globalAlpha = alpha;
    var fontSize = Math.max(10, Math.min(16, W * 0.012));
    ctx.font = fontSize + 'px "SF Mono", "Fira Code", monospace';
    ctx.textAlign = 'left'; ctx.textBaseline = 'top';
    for (var i = 0; i < count; i++) {
      var x = Math.random() * W;
      var y = Math.random() * H;
      var ch = CHARS[Math.floor(Math.random() * CHARS.length)];
      ctx.fillStyle = 'hsl(' + (180 + Math.random() * 40) + ',' + (10 + Math.random() * 20) + '%,' + (40 + Math.random() * 30) + '%)';
      ctx.fillText(ch, x, y);
    }
  }

  function drawTextChars(lockChance, overallAlpha) {
    var fontSize = Math.max(10, Math.min(16, W * 0.012));
    ctx.font = fontSize + 'px "SF Mono", "Fira Code", monospace';
    ctx.textAlign = 'left'; ctx.textBaseline = 'top';
    var elapsed = performance.now() - phaseStart;
    var lettersLocked = Math.min(5, Math.floor(elapsed / 200));
    for (var i = 0; i < textPoints.length; i++) {
      var pt = textPoints[i];
      if (!pt.locked && pt.letterIdx <= lettersLocked) pt.locked = true;
      var showChar, alpha;
      if (pt.locked) {
        showChar = pt.char;
        alpha = overallAlpha * (0.6 + Math.random() * 0.3);
        ctx.fillStyle = 'rgba(200,220,255,' + alpha + ')';
      } else {
        showChar = Math.random() < 0.3 ? pt.char : pt.flickerChar;
        alpha = overallAlpha * (0.2 + Math.random() * 0.3);
        ctx.fillStyle = 'rgba(150,170,200,' + alpha + ')';
        if (Math.random() < 0.1) pt.flickerChar = CHARS[Math.floor(Math.random() * CHARS.length)];
      }
      ctx.fillText(showChar, pt.x, pt.y);
    }
  }

  function drawScanlines(alpha) {
    ctx.globalAlpha = alpha;
    ctx.fillStyle = 'rgba(0,0,0,0.6)';
    for (var y = 0; y < H; y += 3) ctx.fillRect(0, y, W, 1);
  }

  function drawSweepLine(alpha) {
    ctx.globalAlpha = alpha;
    var grad = ctx.createLinearGradient(0, scanlineY - 10, 0, scanlineY + 10);
    grad.addColorStop(0, 'rgba(124,106,239,0)');
    grad.addColorStop(0.5, 'rgba(124,106,239,0.6)');
    grad.addColorStop(1, 'rgba(124,106,239,0)');
    ctx.fillStyle = grad;
    ctx.fillRect(0, scanlineY - 10, W, 20);
  }

  function drawAmbientChars() {
    var fontSize = Math.max(10, Math.min(14, W * 0.01));
    ctx.font = fontSize + 'px "SF Mono", "Fira Code", monospace';
    ctx.textAlign = 'left'; ctx.textBaseline = 'top';
    for (var i = 0; i < ambientChars.length; i++) {
      var ac = ambientChars[i];
      ac.flickerT += ac.flickerSpeed;
      var flick = Math.sin(ac.flickerT) * 0.5 + 0.5;
      var a = ac.alpha * (0.5 + flick * 0.5);
      if (cursorX > 0) {
        var dx = ac.x - cursorX, dy = ac.y - cursorY;
        var dist = Math.sqrt(dx * dx + dy * dy) || 1;
        if (dist < 120) { var r = (1 - dist / 120) * 1.2; ac.vx += (dx / dist) * r; ac.vy += (dy / dist) * r; a *= 1.5; }
      }
      ac.vx *= 0.95; ac.vy *= 0.95; ac.x += ac.vx; ac.y += ac.vy;
      if (ac.x < -20) ac.x = W + 20; if (ac.x > W + 20) ac.x = -20;
      if (ac.y < -20) ac.y = H + 20; if (ac.y > H + 20) ac.y = -20;
      if (Math.random() < 0.02) ac.char = CHARS[Math.floor(Math.random() * CHARS.length)];
      ctx.globalAlpha = a;
      ctx.fillStyle = 'rgba(124,200,239,0.8)';
      ctx.fillText(ac.char, ac.x, ac.y);
    }
  }

  function resize() {
    var dpr = isLowEnd || isMobile ? 1 : Math.min(window.devicePixelRatio || 1, 2);
    W = window.innerWidth; H = window.innerHeight;
    canvas.width = W * dpr; canvas.height = H * dpr;
    canvas.style.width = W + 'px'; canvas.style.height = H + 'px';
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    if (phase !== 'idle') sampleTextLayout();
  }

  function onCursorMove(e) { cursorX = e.clientX; cursorY = e.clientY; }
  function onCursorLeave() { cursorX = -1000; cursorY = -1000; }

  return {
    init: function() {
      resize(); window.addEventListener('resize', resize);
      phase = 'static'; phaseStart = performance.now();
      scanlineY = -20; scanlineSpeed = isMobile ? 4 : 6;
      sampleTextLayout();
      raf = requestAnimationFrame(function() { draw(performance.now()); });
    },
    startResolve: function() {
      phase = 'resolve'; phaseStart = performance.now();
      for (var i = 0; i < textPoints.length; i++) { textPoints[i].locked = false; textPoints[i].lockT = 0; }
    },
    startStable: function() {
      phase = 'stable'; phaseStart = performance.now();
      for (var i = 0; i < textPoints.length; i++) textPoints[i].locked = true;
    },
    startGlitch: function() {
      phase = 'glitch'; phaseStart = performance.now();
      canvas.style.transition = 'opacity 0.5s ease'; canvas.style.opacity = '0';
    },
    startSettle: function() { phase = 'settle'; phaseStart = performance.now(); },
    startAmbient: function() {
      phase = 'ambient'; phaseStart = performance.now();
      canvas.style.transition = 'opacity 0.3s ease'; canvas.style.opacity = '1';
      initAmbient();
      if (!cursorListenerActive) {
        window.addEventListener('mousemove', onCursorMove);
        window.addEventListener('mouseleave', onCursorLeave);
        cursorListenerActive = true;
      }
    },
    setPhase: function(p) { phase = p; },
    getPhase: function() { return phase; },
    destroy: function() {
      if (raf) cancelAnimationFrame(raf);
      window.removeEventListener('resize', resize);
      if (cursorListenerActive) { window.removeEventListener('mousemove', onCursorMove); window.removeEventListener('mouseleave', onCursorLeave); }
    },
    resize: resize
  };
}
