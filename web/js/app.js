// ─── React hooks (fallback if utils.js not yet loaded) ──
if (typeof useState === 'undefined') {
  var _a = React;
  useState = _a.useState;
  useEffect = _a.useEffect;
  useRef = _a.useRef;
  useCallback = _a.useCallback;
  useMemo = _a.useMemo;
}
var html = html || htm.bind(React.createElement);

// ─── Sound Design (Full Luxury) ─────────────────────
var _audioCtx = null;
function _getAudioCtx() {
  if (!_audioCtx) _audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  return _audioCtx;
}

function playDrone(freq, dur, vol) {
  try {
    var ctx = _getAudioCtx();
    var osc = ctx.createOscillator();
    var gain = ctx.createGain();
    osc.type = 'sine';
    osc.frequency.value = freq || 55;
    gain.gain.setValueAtTime(0, ctx.currentTime);
    gain.gain.linearRampToValueAtTime(vol || 0.03, ctx.currentTime + 1.5);
    gain.gain.linearRampToValueAtTime(0, ctx.currentTime + (dur || 4));
    osc.connect(gain); gain.connect(ctx.destination);
    osc.start(); osc.stop(ctx.currentTime + (dur || 4));
  } catch(e) {}
}

function playHarmonic(freq, dur, vol) {
  try {
    var ctx = _getAudioCtx();
    var osc = ctx.createOscillator();
    var gain = ctx.createGain();
    osc.type = 'triangle';
    osc.frequency.value = freq || 110;
    gain.gain.setValueAtTime(0, ctx.currentTime);
    gain.gain.linearRampToValueAtTime(vol || 0.015, ctx.currentTime + 2);
    gain.gain.linearRampToValueAtTime(0, ctx.currentTime + (dur || 5));
    osc.connect(gain); gain.connect(ctx.destination);
    osc.start(); osc.stop(ctx.currentTime + (dur || 5));
  } catch(e) {}
}

function playWind(dur) {
  try {
    var ctx = _getAudioCtx();
    var bufSize = ctx.sampleRate * (dur || 3);
    var buf = ctx.createBuffer(1, bufSize, ctx.sampleRate);
    var data = buf.getChannelData(0);
    for (var i = 0; i < bufSize; i++) data[i] = (Math.random() * 2 - 1) * 0.3;
    var src = ctx.createBufferSource();
    src.buffer = buf;
    var filter = ctx.createBiquadFilter();
    filter.type = 'lowpass';
    filter.frequency.value = 200;
    filter.Q.value = 1;
    var gain = ctx.createGain();
    gain.gain.setValueAtTime(0, ctx.currentTime);
    gain.gain.linearRampToValueAtTime(0.02, ctx.currentTime + 1);
    gain.gain.linearRampToValueAtTime(0, ctx.currentTime + (dur || 3));
    src.connect(filter); filter.connect(gain); gain.connect(ctx.destination);
    src.start(); src.stop(ctx.currentTime + (dur || 3));
  } catch(e) {}
}

function playClick() {
  try {
    var ctx = _getAudioCtx();
    var osc = ctx.createOscillator();
    var gain = ctx.createGain();
    osc.type = 'sine';
    osc.frequency.value = 1200 + Math.random() * 400;
    gain.gain.setValueAtTime(0.04, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.06);
    osc.connect(gain); gain.connect(ctx.destination);
    osc.start(); osc.stop(ctx.currentTime + 0.06);
  } catch(e) {}
}

function playMetalPing() {
  try {
    var ctx = _getAudioCtx();
    var osc = ctx.createOscillator();
    var gain = ctx.createGain();
    osc.type = 'sine';
    osc.frequency.value = 2400 + Math.random() * 800;
    gain.gain.setValueAtTime(0.035, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.15);
    osc.connect(gain); gain.connect(ctx.destination);
    osc.start(); osc.stop(ctx.currentTime + 0.15);
  } catch(e) {}
}

function playSwell(dur) {
  try {
    var ctx = _getAudioCtx();
    var osc = ctx.createOscillator();
    var gain = ctx.createGain();
    osc.type = 'sine';
    osc.frequency.value = 220;
    osc.frequency.linearRampToValueAtTime(440, ctx.currentTime + (dur || 1.2));
    gain.gain.setValueAtTime(0, ctx.currentTime);
    gain.gain.linearRampToValueAtTime(0.05, ctx.currentTime + (dur || 1.2) * 0.6);
    gain.gain.linearRampToValueAtTime(0, ctx.currentTime + (dur || 1.2));
    osc.connect(gain); gain.connect(ctx.destination);
    osc.start(); osc.stop(ctx.currentTime + (dur || 1.2));
  } catch(e) {}
}

function playSubDrop() {
  try {
    var ctx = _getAudioCtx();
    var osc = ctx.createOscillator();
    var gain = ctx.createGain();
    osc.type = 'sine';
    osc.frequency.setValueAtTime(80, ctx.currentTime);
    osc.frequency.exponentialRampToValueAtTime(20, ctx.currentTime + 0.8);
    gain.gain.setValueAtTime(0.08, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.8);
    osc.connect(gain); gain.connect(ctx.destination);
    osc.start(); osc.stop(ctx.currentTime + 0.8);
  } catch(e) {}
}

function playNoiseBurst(dur) {
  try {
    var ctx = _getAudioCtx();
    var bufSize = ctx.sampleRate * (dur || 0.5);
    var buf = ctx.createBuffer(1, bufSize, ctx.sampleRate);
    var data = buf.getChannelData(0);
    for (var i = 0; i < bufSize; i++) data[i] = (Math.random() * 2 - 1);
    var src = ctx.createBufferSource();
    src.buffer = buf;
    var filter = ctx.createBiquadFilter();
    filter.type = 'highpass';
    filter.frequency.value = 3000;
    var gain = ctx.createGain();
    gain.gain.setValueAtTime(0.04, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + (dur || 0.5));
    src.connect(filter); filter.connect(gain); gain.connect(ctx.destination);
    src.start(); src.stop(ctx.currentTime + (dur || 0.5));
  } catch(e) {}
}

function playChime() {
  try {
    var ctx = _getAudioCtx();
    [523, 659, 784].forEach(function(f, i) {
      var osc = ctx.createOscillator();
      var gain = ctx.createGain();
      osc.type = 'sine';
      osc.frequency.value = f;
      var t = ctx.currentTime + i * 0.12;
      gain.gain.setValueAtTime(0, t);
      gain.gain.linearRampToValueAtTime(0.03, t + 0.05);
      gain.gain.exponentialRampToValueAtTime(0.001, t + 0.5);
      osc.connect(gain); gain.connect(ctx.destination);
      osc.start(t); osc.stop(t + 0.5);
    });
  } catch(e) {}
}

function playWarmChime() {
  try {
    var ctx = _getAudioCtx();
    [523, 659, 784, 1047].forEach(function(f, i) {
      var osc = ctx.createOscillator();
      var gain = ctx.createGain();
      osc.type = i < 3 ? 'sine' : 'triangle';
      osc.frequency.value = f;
      var t = ctx.currentTime + i * 0.1;
      var vol = i < 3 ? 0.025 : 0.012;
      gain.gain.setValueAtTime(0, t);
      gain.gain.linearRampToValueAtTime(vol, t + 0.04);
      gain.gain.exponentialRampToValueAtTime(0.001, t + 1.2);
      osc.connect(gain); gain.connect(ctx.destination);
      osc.start(t); osc.stop(t + 1.2);
    });
  } catch(e) {}
}

// ─── Services Panel (MCP OAuth) ─────────────────────
function ServicesPanel(props) {
  var visible = props.visible;
  var onClose = props.onClose;
  var services = props.services;
  var onConnect = props.onConnect;
  var onDisconnect = props.onDisconnect;

  if (!visible) return null;

  var serviceIcons = {
    github: { icon: 'Github', color: '#E4E2DC' },
    fetch: { icon: 'Globe', color: '#3ECFB8' },
    filesystem: { icon: 'HardDrive', color: '#D4944C' },
  };

  return html`
    <div class="approval-overlay" onClick=${function(e) { if (e.target === e.currentTarget) onClose(); }}>
      <div style=${{
        position: 'absolute', right: '16px', top: '60px',
        width: '320px', maxHeight: '70vh',
        background: 'var(--surface)', border: '1px solid var(--border)',
        borderRadius: '16px', padding: '20px',
        boxShadow: '0 20px 60px rgba(0,0,0,0.5)',
        zIndex: 1000, overflow: 'auto',
      }}>
        <div style=${{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
          <div style=${{ fontSize: '14px', fontWeight: 600, color: 'var(--text)', letterSpacing: '2px', fontFamily: 'var(--space)' }}>SERVICES</div>
          <button onClick=${onClose} style=${{ background: 'none', border: 'none', color: 'var(--text-faint)', cursor: 'pointer', padding: '4px' }}>
            <${Li} name="X" size=${16} />
          </button>
        </div>
        <div style=${{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          ${services.map(function(s) {
            var cfg = serviceIcons[s.name] || { icon: 'Plug', color: 'var(--iris)' };
            return html`
              <div key=${s.name} style=${{
                display: 'flex', alignItems: 'center', gap: '12px',
                padding: '12px', borderRadius: '12px',
                background: 'rgba(255,255,255,0.03)',
                border: '1px solid var(--border)',
                cursor: 'pointer', transition: 'all 0.2s',
              }}
              onClick=${function() { s.connected ? onDisconnect(s.name) : onConnect(s.name); }}
              onMouseEnter=${function(e) { e.currentTarget.style.borderColor = 'var(--iris)'; }}
              onMouseLeave=${function(e) { e.currentTarget.style.borderColor = 'var(--border)'; }}
              >
                <div style=${{
                  width: '36px', height: '36px', borderRadius: '10px',
                  background: s.connected ? 'rgba(62,207,184,0.12)' : 'rgba(255,255,255,0.05)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
                }}>
                  <${Li} name=${cfg.icon} size=${18} color=${s.connected ? '#3ECFB8' : cfg.color} />
                </div>
                <div style=${{ flex: 1, minWidth: 0 }}>
                  <div style=${{ fontSize: '13px', fontWeight: 500, color: 'var(--text)', textTransform: 'capitalize' }}>${s.name}</div>
                  <div style=${{ fontSize: '11px', color: 'var(--text-faint)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>${s.description || s.transport}</div>
                </div>
                <div style=${{
                  fontSize: '10px', padding: '3px 8px', borderRadius: '6px',
                  background: s.connected ? 'rgba(62,207,184,0.15)' : 'rgba(255,255,255,0.06)',
                  color: s.connected ? '#3ECFB8' : 'var(--text-faint)',
                  fontFamily: 'var(--mono)', letterSpacing: '1px',
                }}>
                  ${s.connected ? 'ON' : 'OFF'}
                </div>
              </div>
            `;
          })}
        </div>
      </div>
    </div>
  `;
}

// ─── Approval Modal ─────────────────────────────────
function ApprovalModal(props) {
  var approval = props.approval;
  var onApprove = props.onApprove;
  var onDeny = props.onDeny;

  if (!approval) return null;

  var isDestructive = approval.permission === 'destructive';

  return html`
    <div class="approval-overlay" onClick=${function(e) { if (e.target === e.currentTarget) onDeny(); }}>
      <div class="approval-card">
        <div style=${{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '16px' }}>
          <div style=${{
            width: '40px', height: '40px', borderRadius: '12px',
            background: isDestructive ? 'rgba(248,113,113,0.12)' : 'rgba(251,191,36,0.12)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <${Li} name="Shield" size=${20} color=${isDestructive ? '#F87171' : '#FBBF24'} />
          </div>
          <div>
            <div style=${{ fontSize: '16px', fontWeight: 600, color: 'var(--text)' }}>Confirm Action</div>
            <div style=${{ fontSize: '11px', color: 'var(--text-dim)', fontFamily: 'var(--mono)' }}>${approval.permission} permission</div>
          </div>
        </div>
        <div style=${{ background: 'rgba(0,0,0,0.3)', borderRadius: '10px', padding: '12px 14px', marginBottom: '20px', border: '1px solid var(--border)' }}>
          <div style=${{ fontSize: '12px', color: 'rgba(124,106,239,0.7)', fontFamily: 'var(--mono)', marginBottom: '6px' }}>${approval.name}</div>
          <div style=${{ fontSize: '11px', color: 'var(--text-dim)', fontFamily: 'var(--mono)', wordBreak: 'break-all', maxHeight: '80px', overflow: 'auto' }}>${JSON.stringify(approval.args, null, 2)}</div>
        </div>
        ${approval.diff ? html`
          <div style=${{ background: 'rgba(0,0,0,0.4)', borderRadius: '10px', padding: '12px 14px', marginBottom: '20px', border: '1px solid var(--border)', maxHeight: '200px', overflow: 'auto' }}>
            <div style=${{ fontSize: '11px', color: 'var(--text-dim)', fontFamily: 'var(--mono)', marginBottom: '6px' }}>Changes:</div>
            <pre style=${{ margin: 0, fontSize: '11px', fontFamily: 'var(--mono)', lineHeight: '1.5', whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>${
              approval.diff.split('\n').map(function(line) {
                if (line.startsWith('+') && !line.startsWith('+++')) {
                  return html`<div style=${{ color: '#4ADE80', background: 'rgba(74,222,128,0.08)' }}>${line}</div>`;
                }
                if (line.startsWith('-') && !line.startsWith('---')) {
                  return html`<div style=${{ color: '#F87171', background: 'rgba(248,113,113,0.08)' }}>${line}</div>`;
                }
                if (line.startsWith('@@')) {
                  return html`<div style=${{ color: 'var(--text-dim)', fontStyle: 'italic' }}>${line}</div>`;
                }
                return html`<div>${line}</div>`;
              })
            }</pre>
          </div>
        ` : ''}
        <div style=${{ display: 'flex', gap: '10px' }}>
          <button onClick=${onDeny} style=${{ flex: 1, padding: '11px', borderRadius: '10px', border: '1px solid var(--border)', background: 'rgba(255,255,255,0.04)', color: 'var(--text-dim)', cursor: 'pointer', fontSize: '13px', fontWeight: 500, transition: 'all 0.15s' }}>Deny</button>
          <button onClick=${onApprove} style=${{ flex: 1, padding: '11px', borderRadius: '10px', border: 'none', background: 'var(--iris)', color: '#fff', cursor: 'pointer', fontSize: '13px', fontWeight: 600, transition: 'all 0.15s' }}>Allow</button>
        </div>
      </div>
    </div>
  `;
}

// ─── Main App ───────────────────────────────────────
function App() {
  var _msgs = useState(function() { return lsload('messages', []); });
  var messages = _msgs[0], setMessages = _msgs[1];
  var _thinking = useState(false);
  var thinking = _thinking[0], setThinking = _thinking[1];
  var _tool = useState('');
  var activeTool = _tool[0], setActiveTool = _tool[1];
  var _conn = useState(false);
  var connected = _conn[0], setConnected = _conn[1];
  var _cards = useState([]);
  var cards = _cards[0], setCards = _cards[1];
  var _approval = useState(null);
  var pendingApproval = _approval[0], setPendingApproval = _approval[1];
  var _tasks = useState(function() { return lsload('tasks', []); });
  var tasks = _tasks[0], setTasks = _tasks[1];
  var _notes = useState(function() { return lsload('notes', ''); });
  var notes = _notes[0], setNotes = _notes[1];
  var _music = useState({ track: { title: 'No track', artist: '' }, playing: false, progress: 0 });
  var music = _music[0], setMusic = _music[1];

  // ─── MCP Services State ───────────────────────────
  var _services = useState([]);
  var services = _services[0], setServices = _services[1];
  var _servicesVisible = useState(false);
  var servicesVisible = _servicesVisible[0], setServicesVisible = _servicesVisible[1];

  // ─── Cinematic Phase State ──────────────────────
  // phase 0: static (canvas noise, scanlines)
  // phase 1: resolve (chars lock to text, noise thins)
  // phase 2: stable (text fully formed, holographic)
  // phase 3: ready (interactive)
  var _phase = useState(0);
  var phase = _phase[0], setPhase = _phase[1];
  var _orbVisible = useState(false);
  var orbVisible = _orbVisible[0], setOrbVisible = _orbVisible[1];
  var _inputVisible = useState(false);
  var inputVisible = _inputVisible[0], setInputVisible = _inputVisible[1];
  var _glitchActive = useState(false);
  var glitchActive = _glitchActive[0], setGlitchActive = _glitchActive[1];

  // Cinema engine ref
  var cinemaRef = useRef(null);
  var typewriterRef = useRef(null);

  useEffect(function() { lssave('messages', messages); }, [messages]);
  useEffect(function() { lssave('tasks', tasks); }, [tasks]);
  useEffect(function() { lssave('notes', notes); }, [notes]);

  // ─── Fetch MCP services on connect ───────────────
  useEffect(function() {
    if (!connected) return;
    fetch('/api/mcp/services', { headers: { 'Authorization': 'Bearer ' + (window._nallyToken || '') } })
      .then(function(r) { return r.ok ? r.json() : null; })
      .then(function(data) { if (data && data.services) setServices(data.services); })
      .catch(function() {});
  }, [connected]);

  function handleServiceConnect(name) {
    fetch('/api/mcp/connect/' + name, { method: 'POST', headers: { 'Authorization': 'Bearer ' + (window._nallyToken || '') } })
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.auth_url) {
          window.location.href = data.auth_url;
        } else {
          // Refresh services list
          return fetch('/api/mcp/services', { headers: { 'Authorization': 'Bearer ' + (window._nallyToken || '') } });
        }
      })
      .then(function(r) { return r ? r.json() : null; })
      .then(function(data) { if (data && data.services) setServices(data.services); })
      .catch(function() {});
  }

  function handleServiceDisconnect(name) {
    fetch('/api/mcp/disconnect/' + name, { method: 'POST', headers: { 'Authorization': 'Bearer ' + (window._nallyToken || '') } })
      .then(function() {
        return fetch('/api/mcp/services', { headers: { 'Authorization': 'Bearer ' + (window._nallyToken || '') } });
      })
      .then(function(r) { return r.json(); })
      .then(function(data) { if (data && data.services) setServices(data.services); })
      .catch(function() {});
  }

  // Voice
  var voice = useVoiceInput(
    function(text) { handleSend(text); },
    function() {}
  );

  // ─── Cinematic Auto-Play Sequence (4.0s) ───────
  // Static (0-0.5s) → Resolve (0.5-1.5s) → Stable (1.5-2.6s) → Glitch (2.6-2.9s) → Settle (2.9-4.0s)
  useEffect(function() {
    // Skip entirely for reduced-motion preference
    var prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (prefersReduced) {
      setPhase(3);
      setOrbVisible(true);
      setInputVisible(true);
      return function() {};
    }

    var isMobile = window.innerWidth < 768;
    var timers = [];

    // Start AudioContext on first user interaction (browser policy)
    function unlockAudio() {
      if (_audioCtx && _audioCtx.state === 'suspended') _audioCtx.resume();
      document.removeEventListener('click', unlockAudio);
      document.removeEventListener('touchstart', unlockAudio);
    }
    document.addEventListener('click', unlockAudio);
    document.addEventListener('touchstart', unlockAudio);

    // Init canvas noise system
    var canvas = document.getElementById('cinema-canvas');
    if (canvas && typeof CinemaEngine !== 'undefined') {
      cinemaRef.current = CinemaEngine('cinema-canvas');
      cinemaRef.current.init();
    }

    // Act 1: Static (0-0.5s) — pure noise, silence
    // (canvas auto-fills with noise on init)

    // Act 2: Resolve (0.5s) — noise thins, chars lock to text
    timers.push(setTimeout(function() {
      setPhase(1);
      if (cinemaRef.current) cinemaRef.current.startResolve();
      // Digital hum + data clicks
      playDrone(80, 3, 0.02);
      if (!isMobile) playHarmonic(160, 2, 0.008);
    }, 500));

    // Resolve: swell build (1.2s)
    timers.push(setTimeout(function() {
      playSwell(0.8);
    }, 1200));

    // Act 3: Stable (1.5s) — text fully formed, holographic glow
    timers.push(setTimeout(function() {
      setPhase(2);
      if (cinemaRef.current) cinemaRef.current.startStable();
    }, 1500));

    // Act 4: Glitch (2.6s) — dramatic distortion burst
    timers.push(setTimeout(function() {
      setGlitchActive(true);
      if (cinemaRef.current) cinemaRef.current.startGlitch();
      playSubDrop();
      playNoiseBurst(0.3);
      // Screen shake
      var phaseEl = document.querySelector('.luxury-phase');
      if (phaseEl) {
        phaseEl.classList.add('erupt');
        setTimeout(function() { phaseEl.classList.remove('erupt'); }, 400);
      }
    }, 2600));

    // Settle (2.9s) — glitch resolves, text returns clean
    timers.push(setTimeout(function() {
      setGlitchActive(false);
      if (cinemaRef.current) cinemaRef.current.startSettle();
    }, 2900));

    // Orb appears (3.2s)
    timers.push(setTimeout(function() {
      setOrbVisible(true);
      playWarmChime();
    }, 3200));

    // Input (3.5s)
    timers.push(setTimeout(function() {
      setInputVisible(true);
    }, 3500));

    // Ready + ambient (4.0s)
    timers.push(setTimeout(function() {
      setPhase(3);
      if (cinemaRef.current) cinemaRef.current.startAmbient();
    }, 4000));

    return function() {
      timers.forEach(clearTimeout);
      document.removeEventListener('click', unlockAudio);
      document.removeEventListener('touchstart', unlockAudio);
      if (cinemaRef.current) cinemaRef.current.destroy();
    };
  }, []);

  // Skip cinematic — Space, Enter, or click only (with flash cut)
  useEffect(function() {
    function skipToReady() {
      // Flash-to-white-then-black (150ms film cut)
      var flash = document.createElement('div');
      flash.className = 'skip-flash';
      document.body.appendChild(flash);
      setTimeout(function() { flash.remove(); }, 200);

      setPhase(3);
      setGlitchActive(false);
      setOrbVisible(true);
      setInputVisible(true);
      if (cinemaRef.current) {
        cinemaRef.current.startGlitch();
        setTimeout(function() {
          if (cinemaRef.current) cinemaRef.current.startAmbient();
        }, 700);
      }
      playSubDrop();
      playWarmChime();
    }

    function handleKey(e) {
      if (phase < 3 && (e.key === ' ' || e.key === 'Enter')) {
        e.preventDefault();
        skipToReady();
      }
    }

    function handleClick(e) {
      if (phase < 3 && e.target.tagName !== 'BUTTON' && e.target.tagName !== 'INPUT') {
        skipToReady();
      }
    }

    window.addEventListener('keydown', handleKey);
    window.addEventListener('click', handleClick);
    return function() {
      window.removeEventListener('keydown', handleKey);
      window.removeEventListener('click', handleClick);
    };
  }, [phase]);

  function handleKeywordDetected(cleanedText) {
    if (phase < 3) {
      var flash = document.createElement('div');
      flash.className = 'skip-flash';
      document.body.appendChild(flash);
      setTimeout(function() { flash.remove(); }, 200);

      setPhase(3);
      setGlitchActive(false);
      setOrbVisible(true);
      setInputVisible(true);
      if (cinemaRef.current) {
        cinemaRef.current.startGlitch();
        setTimeout(function() {
          if (cinemaRef.current) cinemaRef.current.startAmbient();
        }, 700);
      }
      playSubDrop();
      playWarmChime();
    }
    if (cleanedText && cleanedText.length > 2) {
      setTimeout(function() { handleSend(cleanedText); }, 400);
    }
  }

  useEffect(function() {
    if (voice.supported) {
      voice.startKeywordDetection(handleKeywordDetected);
    }
    return function() { voice.stopKeywordDetection(); };
  }, []);

  // Health check
  useEffect(function() {
    fetch(BACKEND + '/', { method: 'GET' })
      .then(function(r) { if (r.ok) setConnected(true); })
      .catch(function() {});
  }, []);

  // Orb state
  var orbState = 'idle';
  if (thinking) orbState = 'thinking';
  else if (voice.listening) orbState = 'listening';
  else if (messages.length > 0 && messages[messages.length - 1].sender === 'nally' && messages[messages.length - 1].isTyping) orbState = 'speaking';

  // Responsive orb size
  var _orbSizeState = useState(function() { return window.innerWidth <= 480 ? 130 : window.innerWidth <= 768 ? 160 : 200; });
  var orbSize = _orbSizeState[0], setOrbSize = _orbSizeState[1];

  useEffect(function() {
    function onResize() {
      setOrbSize(window.innerWidth <= 480 ? 130 : window.innerWidth <= 768 ? 160 : 200);
    }
    window.addEventListener('resize', onResize);
    return function() { window.removeEventListener('resize', onResize); };
  }, []);

  // SSE event handlers
  useEffect(function() {
    function onStatus(d) {
      if (d.status === 'thinking') setThinking(true);
      else if (d.status === 'idle') { setThinking(false); setActiveTool(''); }
    }

    function onToolCall(d) {
      setActiveTool(d.name);
      beep(1200, 0.02, 'square');
      setMessages(function(p) { return p.concat([{ id: 'tc-' + Date.now(), type: 'tool_call', name: d.name }]); });
    }

    function onToolResult(d) {
      setActiveTool('');
      beep(d.success ? 800 : 300, 0.03, 'sine');
      setMessages(function(p) {
        return p.map(function(m) {
          return (m.type === 'tool_call' && m.name === d.name && m.duration_ms == null)
            ? Object.assign({}, m, { result: d.result, duration_ms: d.duration_ms, success: d.success })
            : m;
        });
      });
    }

    function onResponse(d) {
      var text = d.text || d.response || '';
      var id = 'n-' + Date.now();
      var s = stamp();
      haptic(8);
      if (typewriterRef.current) clearInterval(typewriterRef.current);
      setMessages(function(p) { return p.concat([{ id: id, sender: 'nally', text: '', stamp: s, isTyping: true }]); });
      var i = 0;
      typewriterRef.current = setInterval(function() {
        setMessages(function(p) {
          return p.map(function(m) {
            return m.id === id ? Object.assign({}, m, { text: text.substring(0, i + 1), isTyping: i < text.length }) : m;
          });
        });
        if (i % 3 === 0) beep(1550, 0.004, 'triangle');
        i++;
        if (i >= text.length) { clearInterval(typewriterRef.current); typewriterRef.current = null; }
      }, 15);
    }

    var _streamId = null;
    var _streamText = '';

    function onStreamChunk(d) {
      var chunk = d.text || '';
      if (!_streamId) {
        _streamId = 'sc-' + Date.now();
        _streamText = '';
        var s = stamp();
        setMessages(function(p) { return p.concat([{ id: _streamId, sender: 'nally', text: '', stamp: s, isTyping: true }]); });
      }
      _streamText += chunk;
      var snap = _streamText;
      var sid = _streamId;
      setMessages(function(p) {
        return p.map(function(m) {
          return m.id === sid ? Object.assign({}, m, { text: snap, isTyping: true }) : m;
        });
      });
      beep(1550, 0.004, 'triangle');
    }

    function onStreamDone() {
      var sid = _streamId;
      if (sid) {
        setMessages(function(p) {
          return p.map(function(m) {
            return m.id === sid ? Object.assign({}, m, { isTyping: false }) : m;
          });
        });
      }
      _streamId = null;
      _streamText = '';
    }

    function onApprovalRequest(d) {
      beep(600, 0.08, 'sine');
      setPendingApproval(d);
    }

    on('status', onStatus);
    on('tool_call', onToolCall);
    on('tool_result', onToolResult);
    on('response', onResponse);
    on('stream_chunk', onStreamChunk);
    on('stream_done', onStreamDone);
    on('approval_request', onApprovalRequest);
    on('confirmation_required', onApprovalRequest);

    return function() {
      if (typewriterRef.current) { clearInterval(typewriterRef.current); typewriterRef.current = null; }
      off('status', onStatus);
      off('tool_call', onToolCall);
      off('tool_result', onToolResult);
      off('response', onResponse);
      off('stream_chunk', onStreamChunk);
      off('stream_done', onStreamDone);
      off('approval_request', onApprovalRequest);
      off('confirmation_required', onApprovalRequest);
    };
  }, []);

  // ─── Handlers ────────────────────────────────────
  function handleSend(text) {
    beep(425, 0.06, 'sine');
    haptic(10);
    setMessages(function(p) { return p.concat([{ id: 'u-' + Date.now(), sender: 'user', text: text, stamp: stamp() }]); });
    sendMsg(text);
  }

  function handleRetry() {
    var lastUser = null;
    for (var i = messages.length - 1; i >= 0; i--) {
      if (messages[i].sender === 'user') { lastUser = messages[i]; break; }
    }
    if (lastUser) {
      beep(425, 0.06, 'sine');
      sendMsg(lastUser.text);
    }
  }

  function handleClearChat() {
    setMessages([]);
    setCards([]);
    lssave('messages', []);
  }

  function handleDismissCard(id) {
    setCards(function(p) { return p.filter(function(c) { return c.id !== id; }); });
  }

  function handleApproval(approved) {
    if (!pendingApproval) return;
    httpPost('/api/approval', { tool_call_id: pendingApproval.tool_call_id, approved: approved }).catch(function() {});
    setPendingApproval(null);
    beep(approved ? 800 : 300, 0.05, 'sine');
  }

  function handleToggleTask(id) {
    setTasks(function(p) { return p.map(function(t) { return t.id === id ? Object.assign({}, t, { done: !t.done }) : t; }); });
  }
  function handleAddTask(text) {
    setTasks(function(p) { return p.concat([{ id: 't-' + Date.now(), text: text, done: false }]); });
    beep(800, 0.03, 'sine');
  }
  function handleRemoveTask(id) {
    setTasks(function(p) { return p.filter(function(t) { return t.id !== id; }); });
  }

  var hasConversation = messages.length > 0 || cards.length > 0;
  var isActive = phase >= 3;
  var showCinematic = phase < 3;
  var showOrb = orbVisible || phase >= 3;

  // Identity letters
  var identityLetters = ['N', 'A', 'L', 'L', 'Y'];

  return html`
    <div style=${{ height: '100vh', display: 'flex', flexDirection: 'column', background: '#000', position: 'relative', overflow: 'hidden' }}>

      ${!connected && isActive && html`
        <div style=${{ position: 'fixed', top: '16px', left: '50%', transform: 'translateX(-50%)', zIndex: 100, padding: '8px 16px', borderRadius: 'var(--radius-pill)', background: 'rgba(127,29,29,0.5)', border: '1px solid rgba(239,68,68,0.3)', color: '#FCA5A5', fontSize: '11px', fontFamily: 'var(--mono)' }}>Backend offline</div>
      `}

      <main style=${{ flex: 1, display: 'flex', flexDirection: 'column', position: 'relative', zIndex: 10, overflow: 'hidden' }}>

        ${showCinematic && html`
          <div class="luxury-phase">
            <canvas id="cinema-canvas" style=${{ position: 'absolute', inset: 0, zIndex: 2, pointerEvents: 'none' }} />
            <div class="cin-vignette" />

            ${phase >= 1 && html`
              <div class=${'holo-text' + (glitchActive ? ' glitch' : '')} style=${{ zIndex: 15 }}>
                ${identityLetters.map(function(ch, i) {
                  return html`<span key=${i} class="holo-letter" style=${{ '--letter-delay': (i * 0.2) + 's' }}>${ch}</span>`;
                })}
              </div>
            `}
          </div>
        `}

        ${!showCinematic && html`
          <canvas id="cinema-canvas" style=${{ position: 'absolute', inset: 0, zIndex: 1, pointerEvents: 'none' }} />
        `}

        ${isActive && !hasConversation && html`
          <div style=${{ position: 'absolute', bottom: '70px', left: 0, right: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '12px', zIndex: 20 }}>
            <div style=${{ opacity: showOrb ? 1 : 0, transition: 'opacity 1s ease', transform: showOrb ? 'scale(1)' : 'scale(0.8)', filter: showOrb ? 'blur(0px)' : 'blur(20px)' }}>
              <${Orb} state=${orbState} size=${orbSize} activated=${true} onClick=${function() {}} />
            </div>
            <p style=${{ fontSize: '12px', fontFamily: 'var(--mono)', letterSpacing: '3px', textTransform: 'uppercase', color: 'var(--text-faint)', animation: 'pulse 3s ease-in-out infinite', whiteSpace: 'nowrap', opacity: inputVisible ? 1 : 0, transition: 'opacity 0.8s ease' }}>
              ${voice.listening ? 'Listening...' : thinking ? 'Thinking...' : connected ? 'Ask me anything' : 'Connecting...'}
            </p>
          </div>
        `}

        ${isActive && hasConversation && html`
          <div style=${{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
            <div style=${{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 16px', flexShrink: 0, borderBottom: '1px solid var(--border)' }}>
              <div style=${{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <${Orb} state=${orbState} size=${36} activated=${false} onClick=${function() {}} />
                <div>
                  <div style=${{ fontSize: '14px', fontWeight: 600, color: 'var(--text)', letterSpacing: '2px' }}>NALLY</div>
                  <div style=${{ fontSize: '10px', color: 'var(--text-faint)', fontFamily: 'var(--mono)' }}>
                    ${thinking ? (activeTool ? 'Using ' + activeTool : 'Thinking...') : connected ? 'Ready' : 'Offline'}
                  </div>
                </div>
              </div>
              <div style=${{ display: 'flex', gap: '6px' }}>
                <button onClick=${function() { setServicesVisible(function(v) { return !v; }); }} style=${{ width: '32px', height: '32px', borderRadius: '8px', border: '1px solid var(--border)', background: servicesVisible ? 'rgba(124,106,239,0.12)' : 'rgba(255,255,255,0.03)', color: servicesVisible ? 'var(--iris)' : 'var(--text-faint)', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', transition: 'all 0.2s' }} title="Services">
                  <${Li} name="Plug" size=${15} color=${servicesVisible ? 'var(--iris)' : 'var(--text-faint)'} />
                </button>
                <button onClick=${handleClearChat} style=${{ width: '32px', height: '32px', borderRadius: '8px', border: '1px solid var(--border)', background: 'rgba(255,255,255,0.03)', color: 'var(--text-faint)', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', transition: 'all 0.2s' }} title="Clear chat">
                  <${Li} name="Trash2" size=${15} color="var(--text-faint)" />
                </button>
              </div>
            </div>
            <${ChatHistory} messages=${messages} thinking=${thinking} activeTool=${activeTool} onRetry=${handleRetry} cards=${cards} onDismissCard=${handleDismissCard} />
          </div>
        `}

        ${isActive && html`
          <div class=${inputVisible ? 'input-entrance' : ''} style=${{ flexShrink: 0, opacity: inputVisible ? 1 : 0 }}>
            <${InputBar} onSend=${handleSend} listening=${voice.listening} onMicToggle=${voice.toggle} voiceTranscript=${voice.transcript} />
          </div>
        `}
      </main>

      <${ApprovalModal} approval=${pendingApproval} onApprove=${function() { handleApproval(true); }} onDeny=${function() { handleApproval(false); }} />
      <${ServicesPanel} visible=${servicesVisible} onClose=${function() { setServicesVisible(false); }} services=${services} onConnect=${handleServiceConnect} onDisconnect=${handleServiceDisconnect} />
    </div>
  `;
}

// ─── Error Boundary ─────────────────────────────────
class ErrorBoundary extends React.Component {
  constructor(props) { super(props); this.state = { error: null }; }
  componentDidCatch(err) { this.setState({ error: err }); }
  render() {
    if (this.state.error) {
      return React.createElement('div', { style: { position: 'fixed', inset: 0, zIndex: 99999, background: '#0a0a0a', color: '#ff4444', fontFamily: 'monospace', padding: '40px', overflow: 'auto', fontSize: '14px' } },
        React.createElement('h2', null, 'Nally Runtime Error'),
        React.createElement('pre', { style: { whiteSpace: 'pre-wrap', marginTop: '16px', color: '#ff8888' } }, String(this.state.error)),
        React.createElement('pre', { style: { whiteSpace: 'pre-wrap', marginTop: '8px', color: '#666', fontSize: '12px' } }, this.state.error && this.state.error.stack || '')
      );
    }
    return this.props.children;
  }
}

ReactDOM.createRoot(document.getElementById('root')).render(
  React.createElement(ErrorBoundary, null, React.createElement(App))
);
