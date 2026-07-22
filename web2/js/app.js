var _a = React, useState = _a.useState, useEffect = _a.useEffect, useRef = _a.useRef, useCallback = _a.useCallback;
var html = htm.bind(React.createElement);

var BACKEND = window.location.origin;
var _connected = false;
var _sseAbort = null;
var _accessToken = '';

function _authHeaders() {
  var h = { 'Content-Type': 'application/json' };
  if (_accessToken) h['Authorization'] = 'Bearer ' + _accessToken;
  return h;
}

// --- Token from localStorage ---
function _getStoredToken() {
  try { return localStorage.getItem('nally-access-token') || ''; } catch(e) { return ''; }
}
function _setStoredToken(t) {
  try { localStorage.setItem('nally-access-token', t); } catch(e) {}
}
function _clearStoredToken() {
  try { localStorage.removeItem('nally-access-token'); } catch(e) {}
}

_accessToken = _getStoredToken();

function _showLoginPrompt(onDone) {
  var overlay = document.createElement('div');
  overlay.id = 'nally-login-overlay';
  overlay.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.85);z-index:99999;display:flex;align-items:center;justify-content:center;';
  var box = document.createElement('div');
  box.style.cssText = 'background:#111;border:1px solid rgba(255,255,255,0.1);border-radius:12px;padding:32px;width:340px;text-align:center;';
  var h = document.createElement('div');
  h.textContent = 'Enter Access Token';
  h.style.cssText = 'color:rgba(255,255,255,0.8);font-size:15px;font-weight:600;margin-bottom:20px;font-family:system-ui;';
  var inp = document.createElement('input');
  inp.type = 'password';
  inp.placeholder = 'NALLY_ACCESS_TOKEN';
  inp.style.cssText = 'width:100%;padding:10px 12px;border-radius:8px;border:1px solid rgba(255,255,255,0.1);background:rgba(255,255,255,0.05);color:#fff;font-size:14px;font-family:monospace;outline:none;box-sizing:border-box;';
  var btn = document.createElement('button');
  btn.textContent = 'Connect';
  btn.style.cssText = 'width:100%;padding:10px;border-radius:8px;border:none;background:rgba(0,212,255,0.15);color:rgba(0,212,255,0.9);font-size:14px;font-weight:600;margin-top:12px;cursor:pointer;font-family:system-ui;';
  function submit() {
    var val = inp.value.trim();
    if (!val) return;
    _setStoredToken(val);
    _accessToken = val;
    overlay.remove();
    if (onDone) onDone();
  }
  btn.addEventListener('click', submit);
  inp.addEventListener('keydown', function(e) { if (e.key === 'Enter') submit(); });
  box.appendChild(h); box.appendChild(inp); box.appendChild(btn);
  overlay.appendChild(box);
  document.body.appendChild(overlay);
  inp.focus();
}

if (!_accessToken) {
  _showLoginPrompt(function() {});
}

function _handle401() {
  _clearStoredToken();
  _accessToken = '';
  _showLoginPrompt(function() {});
}

function initSocket(onConnect, onDisconnect) {
  console.log('[NALLY] initSocket called (SSE mode)');
  _connected = true;
  onConnect();
  return null;
}

var _sendMsgCallbacks = [];

function sendMsg(msg, handlers) {
  if (_sseAbort) { _sseAbort.abort(); _sseAbort = null; }
  var ctrl = new AbortController();
  _sseAbort = ctrl;
  _connected = true;

  fetch(BACKEND + '/api/chat', {
    method: 'POST',
    headers: _authHeaders(),
    body: JSON.stringify({ message: msg }),
    signal: ctrl.signal
  }).then(function(response) {
    if (response.status === 401) { _handle401(); return; }
    if (!response.ok) throw new Error('HTTP ' + response.status);
    var reader = response.body.getReader();
    var decoder = new TextDecoder();
    var buffer = '';

    function readChunk() {
      return reader.read().then(function(result) {
        if (result.done) return;
        buffer += decoder.decode(result.value, { stream: true });
        var lines = buffer.split('\n');
        buffer = lines.pop();
        for (var i = 0; i < lines.length; i++) {
          var line = lines[i].trim();
          if (!line.startsWith('data: ')) continue;
          var data = line.slice(6);
          if (data === '[DONE]') {
            if (handlers && handlers.onDone) handlers.onDone();
            return;
          }
          try {
            var event = JSON.parse(data);
            if (handlers && handlers.onEvent) handlers.onEvent(event);
          } catch(e) {}
        }
        return readChunk();
      });
    }
    return readChunk();
  }).catch(function(e) {
    if (e.name === 'AbortError') return;
    console.error('[NALLY] SSE error:', e);
    if (handlers && handlers.onError) handlers.onError(e);
  });
}

function beep(freq, dur, type) {
  try {
    var ctx = new (window.AudioContext || window.webkitAudioContext)();
    var o = ctx.createOscillator();
    var g = ctx.createGain();
    o.type = type || 'sine';
    o.frequency.value = freq || 520;
    g.gain.setValueAtTime(0.015, ctx.currentTime);
    g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + (dur || 0.08));
    o.connect(g); g.connect(ctx.destination);
    o.start(); o.stop(ctx.currentTime + (dur || 0.08));
  } catch(e) {}
}

function stamp() {
  return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

// ─── LocalStorage Helpers ─────────────────────────────
function lsload(key, fallback) {
  try { var v = localStorage.getItem('nally-' + key); return v !== null ? JSON.parse(v) : fallback; } catch(e) { return fallback; }
}
function lssave(key, val) {
  try { localStorage.setItem('nally-' + key, JSON.stringify(val)); } catch(e) {}
}

// ─── Lucide Icon Helpers ──────────────────────────────
// ico() returns SVG string for innerHTML usage
function ico(name, sz, col) {
  var data = lucide && lucide.icons && lucide.icons[name];
  if (!data) return '';
  var inner = data.map(function(e) {
    var tag = e[0], attrs = e[1] || {}, out = '';
    for (var k in attrs) out += ' ' + k + '="' + attrs[k] + '"';
    return '<' + tag + out + '/>';
  }).join('');
  return '<svg xmlns="http://www.w3.org/2000/svg" width="' + (sz||20) + '" height="' + (sz||20) + '" viewBox="0 0 24 24" fill="none" stroke="' + (col||'currentColor') + '" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' + inner + '</svg>';
}
// Li() renders as a React component (no dangerouslySetInnerHTML)
function Li(props) {
  var data = lucide && lucide.icons && lucide.icons[props.name];
  if (!data) return null;
  var sz = props.size || 20;
  var col = props.color || 'currentColor';
  var children = data.map(function(e, i) {
    var tag = e[0], attrs = e[1] || {};
    var cleanAttrs = {};
    for (var k in attrs) cleanAttrs[k] = attrs[k];
    return React.createElement(tag, Object.assign({ key: i }, cleanAttrs));
  });
  return React.createElement('svg', {
    xmlns: 'http://www.w3.org/2000/svg',
    width: sz, height: sz, viewBox: '0 0 24 24',
    fill: 'none', stroke: col, strokeWidth: '2',
    strokeLinecap: 'round', strokeLinejoin: 'round',
    style: { display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }
  }, children);
}

function copyCode(btn) {
  var pre = btn.parentElement.querySelector('code');
  if (pre) {
    navigator.clipboard.writeText(pre.textContent).then(function() {
      btn.innerHTML = ico('Check', 12, '#34D399');
      setTimeout(function() { btn.innerHTML = ico('Copy', 12, 'rgba(255,255,255,0.4)'); }, 1200);
      beep(1200, 0.03, 'sine');
    });
  }
}

function escapeHtml(str) {
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function md(text) {
  if (!text) return '';
  var s = escapeHtml(text);
  s = s.replace(/```(\w*)\n([\s\S]*?)```/g, function(_, lang, code) {
    return '<div class="code-block" style="position:relative;background:rgba(0,0,0,0.5);border:1px solid rgba(0,212,255,0.15);border-radius:10px;padding:12px 12px 12px 14px;overflow-x:auto;margin:8px 0"><button class="copy-btn" onclick="copyCode(this)" title="Copy" style="position:absolute;top:6px;right:6px;width:28px;height:28px;border-radius:6px;border:none;background:rgba(255,255,255,0.08);color:rgba(255,255,255,0.4);cursor:pointer;opacity:0;transition:all 0.2s;display:flex;align-items:center;justify-content:center">' + ico('Copy', 12, 'rgba(255,255,255,0.4)') + '</button>' + (lang ? '<div style="font-size:10px;color:rgba(0,212,255,0.4);font-family:monospace;margin-bottom:6px">' + lang + '</div>' : '') + '<code style="color:#67E8F9;font-size:12px;font-family:monospace;white-space:pre">' + code + '</code></div>';
  });
  s = s.replace(/`([^`]+)`/g, '<code style="background:rgba(0,0,0,0.4);padding:2px 6px;border-radius:4px;color:#67E8F9;font-size:12px;font-family:monospace">$1</code>');
  s = s.replace(/\*\*(.+?)\*\*/g, '<strong style="color:#F1F5F9">$1</strong>');
  s = s.replace(/\*(.+?)\*/g, '<em>$1</em>');
  s = s.replace(/^### (.+)$/gm, '<div style="font-size:15px;font-weight:600;color:#E2E8F0;margin:12px 0 4px">$1</div>');
  s = s.replace(/^## (.+)$/gm, '<div style="font-size:17px;font-weight:700;color:#F1F5F9;margin:14px 0 6px">$1</div>');
  s = s.replace(/^# (.+)$/gm, '<div style="font-size:20px;font-weight:700;color:#fff;margin:16px 0 8px">$1</div>');
  s = s.replace(/^- (.+)$/gm, '<div style="margin-left:16px">• $1</div>');
  s = s.replace(/^> (.+)$/gm, '<div style="border-left:3px solid rgba(0,212,255,0.3);padding-left:12px;color:rgba(255,255,255,0.5);margin:4px 0">$1</div>');
  s = s.replace(/\n/g, '<br/>');
  return s;
}

// ─── Orb (original JarvisCore with 3D mouse tracking) ──
function Orb(props) {
  var ref = useRef(null);
  var mouse = useRef({ x: 0, y: 0 });
  var hovering = useRef(false);
  var forceUpdate = useState(0)[1];

  useEffect(function() {
    function handler(e) {
      if (!ref.current) return;
      var rect = ref.current.getBoundingClientRect();
      var cx = rect.left + rect.width / 2;
      var cy = rect.top + rect.height / 2;
      var dist = Math.hypot(e.clientX - cx, e.clientY - cy);
      if (dist < rect.width / 2 + 200) {
        mouse.current = { x: (e.clientX - cx) / (rect.width / 2 + 200), y: (e.clientY - cy) / (rect.height / 2 + 200) };
        hovering.current = true;
      } else {
        hovering.current = false;
      }
      forceUpdate(function(n) { return n + 1; });
    }
    window.addEventListener('mousemove', handler);
    return function() { window.removeEventListener('mousemove', handler); };
  }, []);

  var h = hovering.current;
  var m = mouse.current;
  var transform = h
    ? 'perspective(1200px) rotateX(' + (-m.y * 40) + 'deg) rotateY(' + (m.x * 40) + 'deg)'
    : 'perspective(1200px) rotateX(0deg) rotateY(0deg)';

  var isActive = props.active;
  var isSpeaking = false;
  var isListening = false;

  var glowStyle = {
    position: 'absolute',
    width: '280px', height: '280px',
    borderRadius: '50%',
    background: 'rgba(0,212,255,0.1)',
    filter: 'blur(70px)',
    pointerEvents: 'none',
    transition: 'all 1s',
    transform: isSpeaking ? 'scale(1.1)' : isListening ? 'scale(1.05)' : isActive ? 'scale(1)' : 'scale(0.9)',
    opacity: isSpeaking ? 0.7 : isListening ? 0.8 : isActive ? 0.5 : 0.3,
  };

  return html`
    <div ref=${ref} onClick=${props.onClick} style=${{ position: 'relative', width: '340px', height: '340px', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', userSelect: 'none', zIndex: 50 }}>
      <div style=${{ transform: transform, transformStyle: 'preserve-3d', transition: 'transform 0.5s', position: 'relative', width: '100%', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div class="orb-ambient" style=${glowStyle} />
        <svg viewBox="0 0 500 500" style=${{ width: '100%', height: '100%', filter: 'drop-shadow(0 0 25px rgba(0,212,255,0.4))' }}>
          <defs>
            <filter id="g1" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="12" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
            <filter id="g2" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
            <filter id="tg" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
          </defs>
          <circle cx="250" cy="250" r="140" fill="#00e5ff" fillOpacity="0.05" />
          <circle cx="250" cy="250" r="150" fill="none" stroke="#00e5ff" strokeWidth="10" filter="url(#g1)" class="orb-ring-ccw" strokeDasharray="940 2" style=${{ transformOrigin: '250px 250px' }} />
          <circle cx="250" cy="250" r="125" fill="none" stroke="#ffffff" strokeWidth="5" filter="url(#g2)" class="orb-reactor orb-ring-cw" strokeDasharray="780 5" style=${{ transformOrigin: '250px 250px' }} />
          <text x="250" y="262" textAnchor="middle" fill="#ffffff" filter="url(#tg)" class="orb-reactor" style=${{ fontFamily: 'Orbitron,sans-serif', fontSize: '46px', fontWeight: 700, letterSpacing: '6px', textTransform: 'uppercase', userSelect: 'none', transformOrigin: '250px 250px' }}>NALLY</text>
        </svg>
        <span style=${{ position: 'absolute', top: 0, left: '50%', transform: 'translateX(-50%)', width: '16px', height: '2px', background: 'rgba(0,212,255,0.8)', borderRadius: '2px' }} />
        <span style=${{ position: 'absolute', bottom: 0, left: '50%', transform: 'translateX(-50%)', width: '16px', height: '2px', background: 'rgba(0,212,255,0.8)', borderRadius: '2px' }} />
        <span style=${{ position: 'absolute', left: 0, top: '50%', transform: 'translateY(-50%)', width: '2px', height: '16px', background: 'rgba(0,212,255,0.8)', borderRadius: '2px' }} />
        <span style=${{ position: 'absolute', right: 0, top: '50%', transform: 'translateY(-50%)', width: '2px', height: '16px', background: 'rgba(0,212,255,0.8)', borderRadius: '2px' }} />
      </div>
    </div>
  `;
}

// ─── Chat Message ─────────────────────────────────────
function MsgBubble(props) {
  var m = props.msg;
  var isUser = m.sender === 'user';
  var onRetry = props.onRetry;

  if (m.type === 'tool_call') {
    var tcColor = m.success === false ? '#F87171' : '#34D399';
    var tcIcon = m.success === false ? html`<${Li} name="XCircle" size=${12} color="#F87171" />` : html`<${Li} name="Loader" size=${12} color="#34D399" />`;
    return html`
      <div style=${{ display: 'flex', justifyContent: 'flex-start', padding: '2px 0', animation: 'fadeIn 0.2s ease-out' }}>
        <div style=${{ display: 'flex', alignItems: 'center', gap: '8px', padding: '6px 14px', borderRadius: '999px', background: 'rgba(0,212,255,0.06)', backdropFilter: 'blur(8px)', border: '1px solid rgba(0,212,255,0.1)' }}>
          ${tcIcon}
          <span style=${{ fontSize: '11px', fontFamily: 'monospace', color: 'rgba(52,211,153,0.7)' }}>${m.name}</span>
          ${m.duration_ms != null && html`<span style=${{ fontSize: '10px', color: 'rgba(255,255,255,0.2)', fontFamily: 'monospace' }}>${m.duration_ms}ms</span>`}
        </div>
      </div>
    `;
  }

  function copyMsg() {
    navigator.clipboard.writeText(m.text).then(function() { beep(1200, 0.03, 'sine'); });
  }

  return html`
    <div class="msg-wrap" style=${{ alignSelf: isUser ? 'flex-end' : 'flex-start', maxWidth: '80%', animation: 'fadeIn 0.2s ease-out', padding: '2px 0' }}>
      <div style=${{
        padding: '14px 18px', borderRadius: '20px', fontSize: '14px', lineHeight: '1.65',
        background: isUser ? 'rgba(0,212,255,0.08)' : 'rgba(255,255,255,0.05)',
        backdropFilter: 'blur(16px)', WebkitBackdropFilter: 'blur(16px)',
        border: '1px solid ' + (isUser ? 'rgba(0,212,255,0.1)' : 'rgba(255,255,255,0.06)'),
        borderBottomRightRadius: isUser ? '6px' : '20px',
        borderBottomLeftRadius: isUser ? '20px' : '6px',
        boxShadow: '0 2px 12px rgba(0,0,0,0.15)',
        overflowWrap: 'break-word', wordBreak: 'break-word',
      }}>
        ${isUser
          ? html`<div dangerouslySetInnerHTML=${{ __html: m.text.replace(/</g, '&lt;').replace(/\n/g, '<br/>') }} />`
          : html`<div dangerouslySetInnerHTML=${{ __html: md(m.text) }} />`
        }
        ${m.isTyping && html`<span style=${{ display: 'inline-block', width: '2px', height: '15px', background: 'rgba(0,212,255,0.5)', animation: 'pulse 1s infinite', verticalAlign: 'middle', marginLeft: '2px', borderRadius: '1px' }} />`}
      </div>
      <div class="msg-actions" style=${{ display: 'flex', gap: '4px', marginTop: '4px', justifyContent: isUser ? 'flex-end' : 'flex-start' }}>
        <button onclick=${copyMsg} style=${{ width: '26px', height: '26px', borderRadius: '8px', border: 'none', background: 'rgba(255,255,255,0.05)', color: 'rgba(255,255,255,0.3)', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', transition: 'all 0.2s' }} title="Copy"><${Li} name="Copy" size=${13} color="rgba(255,255,255,0.35)" /></button>
        ${!isUser && onRetry && html`<button onclick=${function() { onRetry(m.text); }} style=${{ width: '26px', height: '26px', borderRadius: '8px', border: 'none', background: 'rgba(255,255,255,0.05)', color: 'rgba(255,255,255,0.3)', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', transition: 'all 0.2s' }} title="Retry"><${Li} name="RotateCw" size=${13} color="rgba(255,255,255,0.35)" /></button>`}
      </div>
      <div style=${{ fontSize: '10px', color: 'rgba(255,255,255,0.1)', marginTop: '2px', textAlign: isUser ? 'right' : 'left', paddingLeft: isUser ? '0' : '4px', paddingRight: isUser ? '4px' : '0' }}>${m.stamp}</div>
    </div>
  `;
}

// ─── Chat Panel (full-screen modern) ──────────────────
function ChatPanel(props) {
  var _input = useState('');
  var text = _input[0], setText = _input[1];
  var feedRef = useRef(null);
  var inputRef = useRef(null);

  useEffect(function() {
    if (feedRef.current) feedRef.current.scrollTop = feedRef.current.scrollHeight;
  }, [props.messages.length, props.thinking]);

  useEffect(function() {
    if (props.open && inputRef.current) inputRef.current.focus();
  }, [props.open]);

  function handleSubmit(e) {
    e.preventDefault();
    if (!text.trim()) return;
    props.onSend(text.trim());
    setText('');
  }

  if (!props.open) return null;

  var hasText = text.trim().length > 0;

  return html`
    <div style=${{ position: 'fixed', inset: 0, zIndex: 50, display: 'flex', flexDirection: 'column', background: 'rgba(7,11,20,0.92)', backdropFilter: 'blur(60px) saturate(1.8)', WebkitBackdropFilter: 'blur(60px) saturate(1.8)', animation: 'fadeIn 0.25s ease-out' }}>

      <div style=${{ position: 'absolute', top: 0, left: 0, right: 0, height: '1px', background: 'linear-gradient(90deg, transparent, rgba(0,212,255,0.12), transparent)' }} />

      <div style=${{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '16px 24px', flexShrink: 0 }}>
        <div style=${{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div style=${{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <div style=${{ width: '7px', height: '7px', borderRadius: '50%', background: props.thinking ? '#00D4FF' : 'rgba(0,212,255,0.35)', boxShadow: props.thinking ? '0 0 10px rgba(0,212,255,0.6)' : 'none', animation: props.thinking ? 'pulse 1s infinite' : 'none' }} />
            <span style=${{ fontSize: '14px', fontWeight: 600, letterSpacing: '3px', color: 'rgba(255,255,255,0.85)' }}>NALLY</span>
          </div>
        </div>
        <div style=${{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          ${props.thinking && html`<span style=${{ fontSize: '11px', color: 'rgba(0,212,255,0.5)', fontFamily: 'monospace', padding: '4px 10px', borderRadius: '999px', background: 'rgba(0,212,255,0.06)', border: '1px solid rgba(0,212,255,0.1)' }}>thinking...</span>`}
          ${props.activeTool && html`<span style=${{ fontSize: '11px', color: 'rgba(0,212,255,0.6)', fontFamily: 'monospace', padding: '4px 10px', borderRadius: '999px', background: 'rgba(0,212,255,0.06)', border: '1px solid rgba(0,212,255,0.1)' }}><${Li} name="Loader" size=${11} color="rgba(0,212,255,0.6)" />${' ' + props.activeTool}</span>`}
          <button onClick=${props.onClear} style=${{ width: '36px', height: '36px', borderRadius: '12px', border: '1px solid rgba(255,255,255,0.06)', background: 'rgba(255,255,255,0.04)', color: 'rgba(255,255,255,0.3)', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', transition: 'all 0.2s', backdropFilter: 'blur(8px)' }} title="Clear"><${Li} name="Trash2" size=${16} color="rgba(255,255,255,0.3)" /></button>
        </div>
      </div>

      <div ref=${feedRef} style=${{ flex: 1, overflowY: 'auto', padding: '8px 24px 24px', display: 'flex', flexDirection: 'column', gap: '8px', maxWidth: '720px', width: '100%', margin: '0 auto' }}>
        ${props.messages.map(function(m) { return html`<${MsgBubble} key=${m.id} msg=${m} onRetry=${props.onRetry} />`; })}
        ${props.thinking && !props.activeTool && html`
          <div style=${{ alignSelf: 'flex-start', padding: '4px 0' }}>
            <div class="dot-bounce" style=${{ display: 'flex', gap: '6px', padding: '12px 18px', background: 'rgba(255,255,255,0.04)', borderRadius: '16px', borderBottomLeftRadius: '4px', backdropFilter: 'blur(12px)', border: '1px solid rgba(255,255,255,0.04)' }}>
              <span style=${{ width: '6px', height: '6px', borderRadius: '50%', background: 'rgba(0,212,255,0.5)' }} />
              <span style=${{ width: '6px', height: '6px', borderRadius: '50%', background: 'rgba(0,212,255,0.5)' }} />
              <span style=${{ width: '6px', height: '6px', borderRadius: '50%', background: 'rgba(0,212,255,0.5)' }} />
            </div>
          </div>
        `}
      </div>

      <div style=${{ padding: '12px 24px 28px', flexShrink: 0, maxWidth: '720px', width: '100%', margin: '0 auto' }}>
        <form onSubmit=${handleSubmit} style=${{ display: 'flex', alignItems: 'center', gap: '0', background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: '999px', padding: '5px 5px 5px 8px', backdropFilter: 'blur(24px)', WebkitBackdropFilter: 'blur(24px)', boxShadow: '0 4px 30px rgba(0,0,0,0.25), inset 0 1px 0 rgba(255,255,255,0.04)', transition: 'border-color 0.2s, box-shadow 0.2s' }}>
          <button type="button" onClick=${props.onClose} style=${{ width: '38px', height: '38px', borderRadius: '50%', border: 'none', background: 'transparent', color: 'rgba(255,255,255,0.35)', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, transition: 'all 0.2s' }}><${Li} name="ArrowLeft" size=${18} color="rgba(255,255,255,0.35)" /></button>
          <input ref=${inputRef} type="text" value=${text} onInput=${function(e) { setText(e.target.value); }} placeholder="Message Nally..." style=${{ flex: 1, height: '40px', background: 'transparent', border: 'none', color: '#E2E8F0', fontSize: '14px', fontFamily: 'Inter,system-ui,sans-serif', outline: 'none', padding: '0 4px' }} />
          ${hasText && html`<button type="button" onclick=${function() { setText(''); inputRef.current && inputRef.current.focus(); }} style=${{ width: '32px', height: '32px', borderRadius: '50%', border: 'none', background: 'rgba(255,255,255,0.08)', color: 'rgba(255,255,255,0.4)', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, transition: 'all 0.15s' }}><${Li} name="X" size=${14} color="rgba(255,255,255,0.4)" /></button>`}
          <button type="submit" disabled=${!hasText} style=${{ width: '40px', height: '40px', borderRadius: '50%', border: 'none', background: hasText ? 'linear-gradient(135deg, #00D4FF, #0090FF)' : 'rgba(255,255,255,0.06)', color: hasText ? '#000' : 'rgba(255,255,255,0.15)', cursor: 'pointer', flexShrink: 0, transition: 'all 0.25s', display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: hasText ? '0 0 20px rgba(0,212,255,0.3)' : 'none' }}>${hasText ? html`<${Li} name="Send" size=${18} color="#000" />` : html`<${Li} name="Search" size=${18} color="rgba(255,255,255,0.15)" />`}</button>
        </form>
      </div>
    </div>
  `;
}

// ─── Chat Widget (draggable, resizable) ──────────────
function ChatWidget(props) {
  var _input = useState('');
  var text = _input[0], setText = _input[1];
  var feedRef = useRef(null);
  var inputRef = useRef(null);

  useEffect(function() {
    if (feedRef.current) feedRef.current.scrollTop = feedRef.current.scrollHeight;
  }, [props.messages.length, props.thinking]);

  useEffect(function() {
    if (inputRef.current) inputRef.current.focus();
  }, []);

  function handleSubmit(e) {
    e.preventDefault();
    if (!text.trim()) return;
    props.onSend(text.trim());
    setText('');
  }

  var hasText = text.trim().length > 0;

  return html`
    <${ResizableWidget}
      title="Chat" icon="MessageCircle" iconColor="rgba(0,212,255,0.6)"
      x=${props.x} y=${props.y} w=${props.w || 420} h=${props.h || 550}
      z=${props.z} minW=${320} minH=${300}
      onMove=${props.onMove} onResize=${props.onResize}
      onMinimize=${props.onMinimize} onClose=${props.onClose}
    >
      <div style=${{ display: 'flex', flexDirection: 'column', height: '100%' }}>
        <div style=${{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '4px 0', flexShrink: 0 }}>
          <div style=${{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <div style=${{ width: '6px', height: '6px', borderRadius: '50%', background: props.thinking ? '#00D4FF' : 'rgba(0,212,255,0.35)', boxShadow: props.thinking ? '0 0 8px rgba(0,212,255,0.6)' : 'none', animation: props.thinking ? 'pulse 1s infinite' : 'none' }} />
            <span style=${{ fontSize: '11px', fontFamily: 'monospace', color: 'rgba(255,255,255,0.4)' }}>
              ${props.thinking ? 'thinking...' : props.connected ? 'ready' : 'offline'}
            </span>
            ${props.activeTool && html`<span style=${{ fontSize: '10px', color: 'rgba(0,212,255,0.6)', fontFamily: 'monospace' }}><${Li} name="Loader" size=${10} color="rgba(0,212,255,0.6)" />${' ' + props.activeTool}</span>`}
          </div>
          <button onClick=${props.onClear} style=${{ width: '22px', height: '22px', borderRadius: '6px', border: 'none', background: 'transparent', color: 'rgba(255,255,255,0.25)', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }} title="Clear"><${Li} name="Trash2" size=${12} color="rgba(255,255,255,0.25)" /></button>
        </div>

        <div ref=${feedRef} style=${{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '6px', paddingBottom: '8px' }}>
          ${props.messages.map(function(m) { return html`<${MsgBubble} key=${m.id} msg=${m} onRetry=${props.onRetry} />`; })}
          ${props.thinking && !props.activeTool && html`
            <div style=${{ alignSelf: 'flex-start', padding: '2px 0' }}>
              <div class="dot-bounce" style=${{ display: 'flex', gap: '5px', padding: '8px 12px', background: 'rgba(255,255,255,0.04)', borderRadius: '12px', borderBottomLeftRadius: '4px', border: '1px solid rgba(255,255,255,0.04)' }}>
                <span style=${{ width: '5px', height: '5px', borderRadius: '50%', background: 'rgba(0,212,255,0.5)' }} />
                <span style=${{ width: '5px', height: '5px', borderRadius: '50%', background: 'rgba(0,212,255,0.5)' }} />
                <span style=${{ width: '5px', height: '5px', borderRadius: '50%', background: 'rgba(0,212,255,0.5)' }} />
              </div>
            </div>
          `}
        </div>

        <form onSubmit=${handleSubmit} style=${{ display: 'flex', alignItems: 'center', gap: '4px', flexShrink: 0, paddingTop: '6px', borderTop: '1px solid rgba(255,255,255,0.04)' }}>
          <input ref=${inputRef} type="text" value=${text} onInput=${function(e) { setText(e.target.value); }} placeholder="Message Nally..." style=${{ flex: 1, height: '34px', background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: '8px', color: '#E2E8F0', fontSize: '13px', fontFamily: 'Inter,system-ui,sans-serif', outline: 'none', padding: '0 10px' }} />
          ${hasText && html`<button type="button" onclick=${function() { setText(''); inputRef.current && inputRef.current.focus(); }} style=${{ width: '28px', height: '28px', borderRadius: '6px', border: 'none', background: 'rgba(255,255,255,0.06)', color: 'rgba(255,255,255,0.3)', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}><${Li} name="X" size=${12} color="rgba(255,255,255,0.3)" /></button>`}
          <button type="submit" disabled=${!hasText} style=${{ width: '32px', height: '32px', borderRadius: '8px', border: 'none', background: hasText ? 'linear-gradient(135deg, #00D4FF, #0090FF)' : 'rgba(255,255,255,0.06)', color: hasText ? '#000' : 'rgba(255,255,255,0.15)', cursor: 'pointer', flexShrink: 0, transition: 'all 0.2s', display: 'flex', alignItems: 'center', justifyContent: 'center' }}><${Li} name="Send" size=${14} color=${hasText ? '#000' : 'rgba(255,255,255,0.15)'} /></button>
        </form>
      </div>
    </${ResizableWidget}>
  `;
}

// ─── Dynamic Panel (created by ui_control tool) ───────
function DynamicPanel(props) {
  var content = props.content || '';

  function renderContent(c) {
    if (typeof c === 'string') {
      return html`<div dangerouslySetInnerHTML=${{ __html: c }} />`;
    }
    if (typeof c === 'object' && c !== null) {
      if (Array.isArray(c)) {
        return c.map(function(item, i) { return html`<div key=${i}>${renderContent(item)}</div>`; });
      }
      var type = c.type || 'text';
      if (type === 'heading') {
        return html`<div style=${{ fontSize: '16px', fontWeight: 600, color: '#E2E8F0', marginBottom: '8px' }}>${c.text || ''}</div>`;
      }
      if (type === 'text') {
        return html`<div style=${{ fontSize: '13px', color: 'rgba(255,255,255,0.6)', lineHeight: '1.6' }} dangerouslySetInnerHTML=${{ __html: md(c.body || c.text || '') }} />`;
      }
      if (type === 'card') {
        return html`
          <div style=${{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: '10px', padding: '12px', marginBottom: '8px' }}>
            ${c.title && html`<div style=${{ fontSize: '13px', fontWeight: 600, color: '#E2E8F0', marginBottom: '6px' }}>${c.title}</div>`}
            <div style=${{ fontSize: '12px', color: 'rgba(255,255,255,0.5)', lineHeight: '1.5' }} dangerouslySetInnerHTML=${{ __html: md(c.body || '') }} />
          </div>`;
      }
      if (type === 'list') {
        return html`
          <div style=${{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            ${(c.items || []).map(function(item, i) {
              return html`<div key=${i} style=${{ display: 'flex', alignItems: 'center', gap: '8px', padding: '6px 8px', borderRadius: '6px', background: 'rgba(255,255,255,0.02)', fontSize: '12px', color: 'rgba(255,255,255,0.6)' }}>
                ${item.icon && html`<${Li} name=${item.icon} size=${12} color="rgba(0,212,255,0.6)" />`}
                <span>${item.text || item.label || ''}</span>
              </div>`;
            })}
          </div>`;
      }
      if (type === 'table') {
        return html`
          <div style=${{ overflow: 'auto' }}>
            <table style=${{ width: '100%', borderCollapse: 'collapse', fontSize: '12px' }}>
              <thead><tr>${(c.headers || []).map(function(h, i) {
                return html`<th key=${i} style=${{ textAlign: 'left', padding: '6px 8px', borderBottom: '1px solid rgba(255,255,255,0.06)', color: 'rgba(255,255,255,0.4)', fontWeight: 500 }}>${h}</th>`;
              })}</tr></thead>
              <tbody>${(c.rows || []).map(function(row, ri) {
                return html`<tr key=${ri}>${row.map(function(cell, ci) {
                  return html`<td key=${ci} style=${{ padding: '6px 8px', borderBottom: '1px solid rgba(255,255,255,0.03)', color: 'rgba(255,255,255,0.6)' }}>${cell}</td>`;
                })}</tr>`;
              })}</tbody>
            </table>
          </div>`;
      }
      if (type === 'buttons') {
        return html`
          <div style=${{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
            ${(c.items || []).map(function(btn, i) {
              return html`<button key=${i} style=${{ padding: '6px 12px', borderRadius: '6px', border: '1px solid rgba(255,255,255,0.08)', background: 'rgba(255,255,255,0.04)', color: 'rgba(255,255,255,0.6)', cursor: 'pointer', fontSize: '12px', transition: 'all 0.15s' }} onClick=${function() { beep(600, 0.03, 'sine'); }}>${btn.label || btn.text || ''}</button>`;
            })}
          </div>`;
      }
    }
    return html`<div style=${{ fontSize: '12px', color: 'rgba(255,255,255,0.4)' }}>Unsupported content format</div>`;
  }

  return html`
    <${ResizableWidget}
      title=${props.title || 'Panel'} icon="Square" iconColor="rgba(0,212,255,0.6)"
      x=${props.x} y=${props.y} w=${props.w || 400} h=${props.h || 350}
      z=${props.z || 20} minW=${280} minH=${200}
      onMove=${props.onMove} onResize=${props.onResize}
      onMinimize=${props.onMinimize} onClose=${props.onClose}
    >
      <div style=${{ overflowY: 'auto', height: '100%' }}>
        ${renderContent(props.content)}
      </div>
    </${ResizableWidget}>
  `;
}

// ─── 3D Matrix Cylinder (mouse-rotates) ──────────────
function MatrixRain() {
  var canvasRef = useRef(null);
  var mouseRef = useRef({ x: 0 });
  var rotRef = useRef(0);

  useEffect(function() {
    var canvas = canvasRef.current;
    if (!canvas) return;
    var ctx = canvas.getContext('2d');
    var frame;

    var numCols = 50;
    var radius = 350;
    var fontSize = 20;
    var drops = [];
    var chars = '你好世界未来科技智能数据网络系统程序代码创新力量梦想希望自由光明宇宙星辰海洋山川风雨雷电时间空间生命永恒真理美丽勇气智慧正义和平爱健康快乐成功胜利荣耀创造探索发现学习成长进步突破АБВГДЕЖЗИКЛМНОПРСТУФХЦЧШЩЭЮЯабвгдежзиклмнопрстуфхцчшщэюя가나다라마바사아자차카타파하éèêëàâçîïôùûúë';
    var phrases = ['NALLY','CLINTON','LAGOS','NGOZI','SAID I WOULDNT MAKE IT','WATCH ME','LAGOS BOY','TRUST THE PROCESS','GRIND','NO EXCUSES','PROVE THEM WRONG','UNDERDOG','RISE','FROM THE BOTTOM','WE MOVE','SHIT','DAMN','未来','科技','智慧','力量','代码','创新','自由','光明','希望','勇气','HOLA','MUNDO','FUTURO','AMOR','PAZ','LUZ','CREAR','ЗДРАВСТВУЙ','МИР','СИЛА','ЛЮБОВЬ','СВЕТ','КОД','СВОБОДА','БУДУЩЕЕ','НАДЕЖДА','ТЕХНОЛОГИЯ','BONJOUR','MONDE','LUMIÈRE','AMOUR','PAIX','CRÉER','LIBERTÉ','AVENIR','COURAGE','RÊVE','안녕하세요','세계','빛','사랑','평화','자유','희망','미래','기술','용기'];

    for (var i = 0; i < numCols; i++) {
      drops.push(Math.random() * -60);
    }

    function resize() {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
    }

    function onMouse(e) {
      mouseRef.current.x = e.clientX;
    }

    // Track which columns are showing phrases
    var phraseState = []; // { phrase, offset }
    for (var i = 0; i < numCols; i++) phraseState.push(null);

    function draw() {
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      var targetRot = (mouseRef.current.x / canvas.width - 0.5) * Math.PI * 2;
      rotRef.current += (targetRot - rotRef.current) * 0.03;

      var cx = canvas.width / 2;

      var visible = [];
      for (var i = 0; i < numCols; i++) {
        var angle = (i / numCols) * Math.PI * 2 + rotRef.current;
        var x = cx + Math.sin(angle) * radius;
        var z = Math.cos(angle) * radius;

        if (z < -50) continue;

        var y = drops[i] * fontSize;
        var depth01 = (z + radius) / (2 * radius);

        visible.push({ i: i, x: x, y: y, z: z, depth: depth01 });
      }

      visible.sort(function(a, b) { return a.z - b.z; });

      for (var v = 0; v < visible.length; v++) {
        var col = visible[v];
        var scale = 0.4 + col.depth * 0.6;
        var alpha = 0.1 + col.depth * 0.6;
        var sz = Math.floor(fontSize * scale);

        // Decide if this column shows a phrase or random char
        if (!phraseState[col.i] && Math.random() > 0.92) {
          phraseState[col.i] = { phrase: phrases[Math.floor(Math.random() * phrases.length)], offset: 0 };
        }

        var ps = phraseState[col.i];

        if (ps) {
          // Draw each character of the phrase vertically
          var phrase = ps.phrase;
          for (var c = 0; c < phrase.length; c++) {
            var charY = col.y + c * sz;
            if (charY < -50 || charY > canvas.height + 50) continue;

            var bright = Math.random();
            var a;
            if (bright > 0.92) a = alpha * 1.8;
            else if (bright > 0.6) a = alpha * 1.0;
            else a = alpha * 0.6;

            // First char of phrase is brightest
            if (c === 0) a = Math.min(1, alpha * 2);

            ctx.fillStyle = 'rgba(0,212,255,' + Math.min(1, a) + ')';
            ctx.font = sz + 'px monospace';
            ctx.fillText(phrase[c], col.x, charY);

            // Glow on near columns
            if (col.depth > 0.7) {
              ctx.shadowColor = 'rgba(0,212,255,0.4)';
              ctx.shadowBlur = 6;
              ctx.fillText(phrase[c], col.x, charY);
              ctx.shadowColor = 'transparent';
              ctx.shadowBlur = 0;
            }
          }
        } else {
          // Random character
          var char = chars[Math.floor(Math.random() * chars.length)];
          var bright = Math.random();
          var a;
          if (bright > 0.92) a = alpha * 1.5;
          else if (bright > 0.6) a = alpha * 0.8;
          else a = alpha * 0.4;

          ctx.fillStyle = 'rgba(0,212,255,' + Math.min(1, a) + ')';
          ctx.font = sz + 'px monospace';
          ctx.fillText(char, col.x, col.y);

          if (col.depth > 0.7 && Math.random() > 0.85) {
            ctx.shadowColor = 'rgba(0,212,255,0.5)';
            ctx.shadowBlur = 8;
            ctx.fillText(char, col.x, col.y);
            ctx.shadowColor = 'transparent';
            ctx.shadowBlur = 0;
          }
        }

        // Reset
        if (col.y > canvas.height + 100) {
          phraseState[col.i] = null;
          drops[col.i] = Math.random() * -15;
        }
        drops[col.i] += 0.12 + Math.random() * 0.12;
      }
    }

    function loop() { draw(); frame = requestAnimationFrame(loop); }
    window.addEventListener('resize', resize);
    window.addEventListener('mousemove', onMouse);
    resize();
    loop();
    return function() {
      window.removeEventListener('resize', resize);
      window.removeEventListener('mousemove', onMouse);
      cancelAnimationFrame(frame);
    };
  }, []);

  return html`<canvas ref=${canvasRef} style=${{ position: 'absolute', inset: 0, pointerEvents: 'none', zIndex: 1 }} />`;
}

// ─── Widget Metadata (icon + color for dock) ─────────
var widgetMeta = {
  clock:    { icon: 'Clock',        color: 'rgba(0,212,255,0.6)' },
  email:    { icon: 'Mail',         color: 'rgba(248,113,113,0.6)' },
  telegram: { icon: 'Send',         color: 'rgba(96,165,250,0.7)' },
  whatsapp: { icon: 'Phone',        color: 'rgba(37,211,102,0.7)' },
  weather:  { icon: 'Cloud',        color: 'rgba(96,165,250,0.7)' },
  music:    { icon: 'Music',        color: 'rgba(255,255,255,0.5)' },
  notes:    { icon: 'StickyNote',   color: 'rgba(250,204,21,0.6)' },
  status:   { icon: 'Activity',     color: 'rgba(52,211,153,0.6)' },
  tasks:    { icon: 'ListTodo',     color: 'rgba(168,85,247,0.6)' },
  chat:     { icon: 'MessageCircle', color: 'rgba(0,212,255,0.6)' },
};

// ─── Dock Component ──────────────────────────────────
function Dock(props) {
  var minimized = props.minimized || [];
  var onRestore = props.onRestore;
  var onToggleWidgets = props.onToggleWidgets;
  var widgetsOn = props.widgetsOn;
  var onOpenChat = props.onOpenChat;

  return html`
    <div class="dock" style=${{
      position: 'fixed', right: 0, top: 0, bottom: 0, width: '52px',
      background: 'rgba(13,17,23,0.8)', backdropFilter: 'blur(30px)',
      WebkitBackdropFilter: 'blur(30px)',
      borderLeft: '1px solid rgba(255,255,255,0.06)',
      display: 'flex', flexDirection: 'column', alignItems: 'center',
      padding: '12px 0', gap: '4px', zIndex: 60,
    }}>
      <button class="dock-btn" onClick=${onToggleWidgets} title="Toggle widgets" style=${{
        color: widgetsOn ? 'rgba(0,212,255,0.6)' : 'rgba(255,255,255,0.4)',
      }}><${Li} name="LayoutDashboard" size=${18} color=${widgetsOn ? 'rgba(0,212,255,0.6)' : 'rgba(255,255,255,0.4)'} /></button>

      <div style=${{ flex: 1, width: '1px', background: 'rgba(255,255,255,0.04)', margin: '8px 0' }} />

      ${minimized.map(function(name) {
        var meta = widgetMeta[name] || { icon: 'Circle', color: 'rgba(255,255,255,0.4)' };
        return html`
          <button class="dock-icon" onClick=${function() { onRestore(name); }} title=${name}>
            <span class="tooltip">${name.charAt(0).toUpperCase() + name.slice(1)}</span>
            <${Li} name=${meta.icon} size=${18} color=${meta.color} />
          </button>
        `;
      })}

      <div style=${{ flex: 1, width: '1px', background: 'rgba(255,255,255,0.04)', margin: '8px 0' }} />

      <button class="dock-btn" onClick=${onOpenChat} title="Chat" style=${{
        color: 'rgba(255,255,255,0.4)',
      }}><${Li} name="MessageCircle" size=${18} color="rgba(255,255,255,0.4)" /></button>
    </div>
  `;
}

// ─── Draggable Widget Container ───────────────────────
function Widget(props) {
  var pos = useState({ x: props.x || 60, y: props.y || 60 });
  var position = pos[0], setPosition = pos[1];
  var dragging = useState(false);
  var isDragging = dragging[0], setDragging = dragging[1];
  var offset = useRef({ x: 0, y: 0 });
  var maximized = useState(false);
  var isMaximized = maximized[0], setMaximized = maximized[1];
  var prevPos = useRef(null);

  function onDown(e) {
    if (e.target.closest('.widget-collapse-btn')) return;
    setDragging(true);
    offset.current = { x: e.clientX - position.x, y: e.clientY - position.y };
    e.preventDefault();
  }

  useEffect(function() {
    setPosition({ x: props.x || 60, y: props.y || 60 });
  }, [props.x, props.y]);

  useEffect(function() {
    if (!isDragging) return;
    function onMove(e) {
      var newPos = { x: e.clientX - offset.current.x, y: e.clientY - offset.current.y };
      setPosition(newPos);
    }
    function onUp() {
      setDragging(false);
      if (props.onMove) {
        var finalPos = { x: document.querySelectorAll('[data-widget-id]')[0] ? 0 : 0, y: 0 };
      }
    }
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return function() { window.removeEventListener('mousemove', onMove); window.removeEventListener('mouseup', onUp); };
  }, [isDragging]);

  // Report position changes to parent on mouseup
  var lastPos = useRef(position);
  useEffect(function() {
    if (!isDragging && (position.x !== lastPos.current.x || position.y !== lastPos.current.y)) {
      lastPos.current = position;
      if (props.onMove) props.onMove(position);
    }
  }, [isDragging]);

  function toggleMaximize() {
    if (isMaximized) {
      // Restore
      if (prevPos.current) setPosition(prevPos.current);
      setMaximized(false);
      beep(600, 0.03, 'sine');
    } else {
      // Maximize to 50% of screen
      prevPos.current = { x: position.x, y: position.y };
      var mx = Math.round(window.innerWidth * 0.25) + 52;
      var my = Math.round(window.innerHeight * 0.15);
      setPosition({ x: mx, y: my });
      setMaximized(true);
      beep(800, 0.03, 'sine');
    }
  }

  var isCollapsed = props.collapsed || false;
  var ww = typeof window !== 'undefined' ? window.innerWidth : 1200;
  var wh = typeof window !== 'undefined' ? window.innerHeight : 800;

  return html`
    <div style=${{
      position: 'absolute',
      left: position.x + 'px',
      top: position.y + 'px',
      width: isMaximized ? '50vw' : (props.width || 260) + 'px',
      height: isMaximized ? '50vh' : 'auto',
      zIndex: isMaximized ? 98 : (isDragging ? 99 : (props.z || 20)),
      background: 'rgba(13,17,23,0.92)', backdropFilter: 'blur(40px) saturate(1.6)',
      WebkitBackdropFilter: 'blur(40px) saturate(1.6)',
      border: '1px solid rgba(255,255,255,0.06)', borderRadius: isMaximized ? '0px' : '16px',
      boxShadow: isDragging ? '0 12px 50px rgba(0,0,0,0.6), 0 0 2px rgba(0,212,255,0.2)' : '0 8px 40px rgba(0,0,0,0.4), 0 0 1px rgba(0,212,255,0.1)',
      overflow: 'hidden', transition: isDragging ? 'none' : 'all 0.2s ease',
      animation: 'fadeIn 0.3s ease-out',
      userSelect: 'none',
    }}>
      <div onMouseDown=${onDown} style=${{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '10px 14px', cursor: isMaximized ? 'default' : (isDragging ? 'grabbing' : 'grab'), borderBottom: isCollapsed ? 'none' : '1px solid rgba(255,255,255,0.04)',
        background: 'rgba(255,255,255,0.02)',
      }}>
        <div style=${{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <${Li} name=${props.icon || 'Circle'} size=${14} color=${props.iconColor || 'rgba(0,212,255,0.6)'} />
          <span style=${{ fontSize: '11px', fontWeight: 600, letterSpacing: '1.5px', textTransform: 'uppercase', color: 'rgba(255,255,255,0.5)' }}>${props.title}</span>
        </div>
        <div style=${{ display: 'flex', gap: '2px' }}>
          <button class="widget-collapse-btn" onClick=${function() { props.onMinimize && props.onMinimize(); beep(400, 0.03, 'sine'); }} style=${{
            width: '24px', height: '24px', borderRadius: '6px', border: 'none', background: 'transparent',
            color: 'rgba(255,255,255,0.25)', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}><${Li} name="Minus" size=${12} color="rgba(255,255,255,0.25)" /></button>
          <button class="widget-collapse-btn" onClick=${toggleMaximize} style=${{
            width: '24px', height: '24px', borderRadius: '6px', border: 'none', background: 'transparent',
            color: 'rgba(255,255,255,0.25)', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}><${Li} name=${isMaximized ? 'Minimize2' : 'Maximize2'} size=${12} color="rgba(255,255,255,0.25)" /></button>
          <button class="widget-collapse-btn" onClick=${function() { props.onClose && props.onClose(); beep(600, 0.02, 'sine'); }} style=${{
            width: '24px', height: '24px', borderRadius: '6px', border: 'none', background: 'transparent',
            color: 'rgba(255,255,255,0.25)', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}><${Li} name="X" size=${12} color="rgba(255,255,255,0.25)" /></button>
        </div>
      </div>
      ${!isCollapsed && html`<div style=${{ padding: '12px 14px', overflow: isMaximized ? 'auto' : 'visible', height: isMaximized ? 'calc(100vh - 44px)' : 'auto' }}>${props.children}</div>`}
    </div>
  `;
}

// ─── Resizable Widget Container ───────────────────────
function ResizableWidget(props) {
  var pos = useState({ x: props.x || 60, y: props.y || 60 });
  var position = pos[0], setPosition = pos[1];
  var sz = useState({ w: props.w || 800, h: props.h || 500 });
  var size = sz[0], setSize = sz[1];
  var dragging = useState(false);
  var isDragging = dragging[0], setDragging = dragging[1];
  var resizing = useState(false);
  var isResizing = resizing[0], setResizing = resizing[1];
  var dragOffset = useRef({ x: 0, y: 0 });
  var resizeData = useRef({ edge: '', startX: 0, startY: 0, startX: 0, startY: 0, startW: 0, startH: 0 });
  var lastPos = useRef(position);
  var lastSize = useRef(size);
  var maximized = useState(false);
  var isMaximized = maximized[0], setMaximized = maximized[1];
  var prevPos = useRef(null);
  var prevSize = useRef(null);

  var minW = props.minW || 300;
  var minH = props.minH || 200;

  // Sync from props
  useEffect(function() {
    setPosition({ x: props.x || 60, y: props.y || 60 });
  }, [props.x, props.y]);
  useEffect(function() {
    setSize({ w: props.w || 800, h: props.h || 500 });
  }, [props.w, props.h]);

  // Drag from title bar
  function onDragDown(e) {
    if (e.target.closest('.widget-btn')) return;
    setDragging(true);
    dragOffset.current = { x: e.clientX - position.x, y: e.clientY - position.y };
    e.preventDefault();
  }

  useEffect(function() {
    if (!isDragging) return;
    function onMove(e) {
      setPosition({ x: e.clientX - dragOffset.current.x, y: e.clientY - dragOffset.current.y });
    }
    function onUp() { setDragging(false); }
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return function() { window.removeEventListener('mousemove', onMove); window.removeEventListener('mouseup', onUp); };
  }, [isDragging]);

  useEffect(function() {
    if (!isDragging && (position.x !== lastPos.current.x || position.y !== lastPos.current.y)) {
      lastPos.current = position;
      if (props.onMove) props.onMove(position);
    }
  }, [isDragging]);

  // Resize from edges/corners
  function onResizeDown(edge, e) {
    e.preventDefault(); e.stopPropagation();
    if (isMaximized) return;
    setResizing(true);
    resizeData.current = {
      edge: edge, startX: e.clientX, startY: e.clientY,
      origX: position.x, origY: position.y, origW: size.w, origH: size.h
    };
  }

  useEffect(function() {
    if (!isResizing) return;
    var d = resizeData.current;
    function onMove(e) {
      var dx = e.clientX - d.startX;
      var dy = e.clientY - d.startY;
      var newX = d.origX, newY = d.origY, newW = d.origW, newH = d.origH;
      var edge = d.edge;

      if (edge.indexOf('e') !== -1) newW = Math.max(minW, d.origW + dx);
      if (edge.indexOf('w') !== -1) { newW = Math.max(minW, d.origW - dx); newX = d.origX + (d.origW - newW); }
      if (edge.indexOf('s') !== -1) newH = Math.max(minH, d.origH + dy);
      if (edge.indexOf('n') !== -1) { newH = Math.max(minH, d.origH - dy); newY = d.origY + (d.origH - newH); }

      setPosition({ x: newX, y: newY });
      setSize({ w: newW, h: newH });
    }
    function onUp() {
      setResizing(false);
      if (props.onResize) props.onResize({ w: size.w, h: size.h });
    }
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return function() { window.removeEventListener('mousemove', onMove); window.removeEventListener('mouseup', onUp); };
  }, [isResizing]);

  useEffect(function() {
    if (!isResizing && (size.w !== lastSize.current.w || size.h !== lastSize.current.h)) {
      lastSize.current = size;
      if (props.onResize) props.onResize(size);
    }
  }, [isResizing]);

  function toggleMaximize() {
    if (isMaximized) {
      // Restore
      if (prevPos.current) setPosition(prevPos.current);
      if (prevSize.current) setSize(prevSize.current);
      setMaximized(false);
      beep(600, 0.03, 'sine');
    } else {
      // Maximize to 50% of screen
      prevPos.current = { x: position.x, y: position.y };
      prevSize.current = { w: size.w, h: size.h };
      var mx = Math.round(window.innerWidth * 0.25) + 52;
      var my = Math.round(window.innerHeight * 0.15);
      var mw = Math.round(window.innerWidth * 0.5);
      var mh = Math.round(window.innerHeight * 0.5);
      setPosition({ x: mx, y: my });
      setSize({ w: mw, h: mh });
      setMaximized(true);
      beep(800, 0.03, 'sine');
    }
  }

  var isCollapsed = props.collapsed || false;
  var active = isDragging || isResizing;

  return html`
    <div style=${{
      position: 'absolute',
      left: position.x + 'px',
      top: position.y + 'px',
      width: size.w + 'px',
      height: isCollapsed ? 'auto' : size.h + 'px',
      zIndex: isMaximized ? 98 : (active ? 99 : (props.z || 20)),
      background: 'rgba(13,17,23,0.92)', backdropFilter: 'blur(40px) saturate(1.6)',
      WebkitBackdropFilter: 'blur(40px) saturate(1.6)',
      border: '1px solid rgba(255,255,255,0.06)', borderRadius: isMaximized ? '0px' : '12px',
      boxShadow: active ? '0 12px 50px rgba(0,0,0,0.6), 0 0 2px rgba(0,212,255,0.2)' : '0 8px 40px rgba(0,0,0,0.4), 0 0 1px rgba(0,212,255,0.1)',
      overflow: 'hidden', display: 'flex', flexDirection: 'column',
      transition: active ? 'none' : 'all 0.2s ease',
      animation: 'fadeIn 0.3s ease-out', userSelect: 'none',
    }}>
      <div onMouseDown=${onDragDown} style=${{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '8px 12px', cursor: isMaximized ? 'default' : (isDragging ? 'grabbing' : 'grab'),
        borderBottom: isCollapsed ? 'none' : '1px solid rgba(255,255,255,0.04)',
        background: 'rgba(255,255,255,0.02)', flexShrink: 0,
      }}>
        <div style=${{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <${Li} name=${props.icon || 'Square'} size=${14} color=${props.iconColor || 'rgba(0,212,255,0.6)'} />
          <span style=${{ fontSize: '11px', fontWeight: 600, letterSpacing: '1.5px', textTransform: 'uppercase', color: 'rgba(255,255,255,0.5)' }}>${props.title}</span>
        </div>
        <div style=${{ display: 'flex', gap: '2px' }}>
          <button class="widget-btn" onClick=${function() { props.onMinimize && props.onMinimize(); beep(400, 0.03, 'sine'); }} style=${{
            width: '24px', height: '24px', borderRadius: '6px', border: 'none', background: 'transparent',
            color: 'rgba(255,255,255,0.25)', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}><${Li} name="Minus" size=${12} color="rgba(255,255,255,0.25)" /></button>
          <button class="widget-btn" onClick=${toggleMaximize} style=${{
            width: '24px', height: '24px', borderRadius: '6px', border: 'none', background: 'transparent',
            color: 'rgba(255,255,255,0.25)', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}><${Li} name=${isMaximized ? 'Minimize2' : 'Maximize2'} size=${12} color="rgba(255,255,255,0.25)" /></button>
          <button class="widget-btn" onClick=${function() { props.onClose && props.onClose(); beep(600, 0.02, 'sine'); }} style=${{
            width: '24px', height: '24px', borderRadius: '6px', border: 'none', background: 'transparent',
            color: 'rgba(255,255,255,0.25)', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}><${Li} name="X" size=${12} color="rgba(255,255,255,0.25)" /></button>
        </div>
      </div>
      ${!isCollapsed && html`<div style=${{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>${props.children}</div>`}
      ${!isCollapsed && !isMaximized && html`
        <div className="resize-handle resize-n" onMouseDown=${function(e) { onResizeDown('n', e); }} />
        <div className="resize-handle resize-s" onMouseDown=${function(e) { onResizeDown('s', e); }} />
        <div className="resize-handle resize-e" onMouseDown=${function(e) { onResizeDown('e', e); }} />
        <div className="resize-handle resize-w" onMouseDown=${function(e) { onResizeDown('w', e); }} />
        <div className="resize-handle resize-ne" onMouseDown=${function(e) { onResizeDown('ne', e); }} />
        <div className="resize-handle resize-nw" onMouseDown=${function(e) { onResizeDown('nw', e); }} />
        <div className="resize-handle resize-se" onMouseDown=${function(e) { onResizeDown('se', e); }} />
        <div className="resize-handle resize-sw" onMouseDown=${function(e) { onResizeDown('sw', e); }} />
      `}
    </div>
  `;
}

// ─── Email Widget ─────────────────────────────────────
function EmailWidget(props) {
  var mockEmails = [
    { id: 1, from: 'GitHub', subject: '[nally] New issue opened: widget overflow', time: '2m', unread: true, color: '#F87171', label: 'Code' },
    { id: 2, from: 'Vercel', subject: 'Deployment succeeded — nally.app', time: '15m', unread: true, color: '#34D399', label: 'Deploy' },
    { id: 3, from: 'Twitter', subject: '@clinton_nally mentioned you', time: '1h', unread: false, color: '#60A5FA', label: 'Social' },
    { id: 4, from: 'Lagos Dev Community', subject: 'Meetup this Saturday — React Workshop', time: '3h', unread: false, color: '#FBBF24', label: 'Community' },
    { id: 5, from: 'AWS', subject: 'Your bill is ready — ₦12,450', time: '5h', unread: false, color: '#F97316', label: 'Billing' },
    { id: 6, from: 'LinkedIn', subject: '3 people viewed your profile', time: '8h', unread: false, color: '#818CF8', label: 'Network' },
    { id: 7, from: 'Nally', subject: 'Daily digest: 4 tasks completed', time: '1d', unread: false, color: '#00D4FF', label: 'Nally' },
  ];

  var state = useState({ emails: [], expanded: null, loading: true, configured: null, fullBody: null, loadingBody: false });
  var s = state[0], setS = state[1];

  // Fetch real Gmail data on mount
  useEffect(function() {
    fetch(BACKEND + '/api/gmail/inbox?max=10')
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.configured && data.authenticated && data.emails && data.emails.length > 0) {
          var colors = ['#F87171', '#34D399', '#60A5FA', '#FBBF24', '#F97316', '#818CF8', '#00D4FF', '#A78BFA'];
          var emails = data.emails.map(function(em, i) {
            return Object.assign({}, em, { color: colors[i % colors.length] });
          });
          setS({ emails: emails, expanded: null, loading: false, configured: true, fullBody: null, loadingBody: false });
        } else if (data.configured === false) {
          setS({ emails: mockEmails, expanded: null, loading: false, configured: false, fullBody: null, loadingBody: false });
        } else {
          setS({ emails: mockEmails, expanded: null, loading: false, configured: data.configured, fullBody: null, loadingBody: false });
        }
      })
      .catch(function() {
        setS({ emails: mockEmails, expanded: null, loading: false, configured: false, fullBody: null, loadingBody: false });
      });
  }, []);

  var unreadCount = s.emails.filter(function(e) { return e.unread; }).length;

  function toggleExpand(id) {
    var wasExpanded = s.expanded === id;
    setS(function(p) {
      var emails = p.emails.map(function(e) {
        return e.id === id ? Object.assign({}, e, { unread: false }) : e;
      });
      return Object.assign({}, p, { emails: emails, expanded: wasExpanded ? null : id, fullBody: null, loadingBody: false });
    });
    beep(700, 0.02, 'sine');

    // Fetch full email body when expanding
    if (!wasExpanded) {
      setS(function(p) { return Object.assign({}, p, { loadingBody: true }); });
      fetch(BACKEND + '/api/gmail/read/' + id)
      .then(function(r) { if (r.status === 401) { _handle401(); return; } return r.json(); })
        .then(function(data) {
          setS(function(p) { return Object.assign({}, p, { fullBody: data.body || data.error || 'No content', loadingBody: false }); });
        })
        .catch(function() {
          setS(function(p) { return Object.assign({}, p, { fullBody: 'Failed to load email', loadingBody: false }); });
        });
    }
  }

  function handleReply(em) {
    var to = em.from.includes('@') ? em.from : '';
    var subject = em.subject.startsWith('Re: ') ? em.subject : 'Re: ' + em.subject;
    var body = '\n\n---\nOn ' + em.time + ', ' + em.from + ' wrote:\n' + (s.fullBody || em.snippet || '');
    window.open('mailto:' + encodeURIComponent(to) + '?subject=' + encodeURIComponent(subject) + '&body=' + encodeURIComponent(body), '_blank');
  }

  function handleForward(em) {
    var subject = em.subject.startsWith('Fwd: ') ? em.subject : 'Fwd: ' + em.subject;
    var body = '\n\n---\nForwarded message:\nFrom: ' + em.from + '\nSubject: ' + em.subject + '\n\n' + (s.fullBody || em.snippet || '');
    window.open('mailto:?subject=' + encodeURIComponent(subject) + '&body=' + encodeURIComponent(body), '_blank');
  }

  function formatBody(text) {
    if (!text) return '';
    // Strip HTML tags for basic display
    return text.replace(/<[^>]*>/g, '').replace(/&nbsp;/g, ' ').replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&#39;/g, "'").replace(/&quot;/g, '"').trim();
  }

  return html`
    <${Widget} ...${props} title="Email" icon="Mail" iconColor="rgba(248,113,113,0.6)" width="300">
      <div>
        <div style=${{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' }}>
          <div style=${{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span style=${{ fontSize: '11px', color: 'rgba(255,255,255,0.3)' }}>Inbox</span>
            ${unreadCount > 0 && html`<span style=${{ fontSize: '10px', color: '#F87171', background: 'rgba(248,113,113,0.1)', padding: '1px 6px', borderRadius: '999px', fontWeight: 600 }}>${unreadCount} new</span>`}
            ${s.configured === false && html`<span style=${{ fontSize: '9px', color: '#FBBF24', background: 'rgba(251,191,36,0.1)', padding: '1px 6px', borderRadius: '999px' }}>Mock</span>`}
          </div>
        </div>
        <div style=${{ display: 'flex', flexDirection: 'column', gap: '2px', maxHeight: s.expanded ? '400px' : '260px', overflowY: 'auto', transition: 'max-height 0.2s' }}>
          ${s.loading && html`<div style=${{ textAlign: 'center', padding: '20px', color: 'rgba(255,255,255,0.3)', fontSize: '11px' }}>Loading emails...</div>`}
          ${!s.loading && s.emails.map(function(em) {
            var expanded = s.expanded === em.id;
            return html`
              <div key=${em.id} onClick=${function() { toggleExpand(em.id); }} style=${{
                padding: '8px 10px', borderRadius: '8px', cursor: 'pointer',
                background: expanded ? 'rgba(255,255,255,0.04)' : 'transparent',
                borderLeft: em.unread ? '2px solid ' + em.color : '2px solid transparent',
                transition: 'background 0.15s',
              }}>
                <div style=${{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <div style=${{
                    width: '28px', height: '28px', borderRadius: '8px', flexShrink: 0,
                    background: (em.color || '#666') + '15', display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontSize: '11px', fontWeight: 700, color: em.color || '#666',
                  }}>${(em.from || '?').charAt(0)}</div>
                  <div style=${{ flex: 1, minWidth: 0 }}>
                    <div style=${{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span style=${{ fontSize: '12px', fontWeight: em.unread ? 600 : 400, color: em.unread ? '#E2E8F0' : 'rgba(255,255,255,0.4)' }}>${em.from}</span>
                      <span style=${{ fontSize: '9px', color: 'rgba(255,255,255,0.2)', fontFamily: 'monospace', flexShrink: 0 }}>${em.time}</span>
                    </div>
                    <div style=${{ fontSize: '11px', color: 'rgba(255,255,255,0.3)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', marginTop: '1px' }}>${em.subject}</div>
                  </div>
                </div>
                ${expanded && html`
                  <div style=${{ marginTop: '8px', paddingTop: '8px', borderTop: '1px solid rgba(255,255,255,0.04)' }}>
                    ${s.loadingBody && html`<div style=${{ textAlign: 'center', padding: '12px', color: 'rgba(255,255,255,0.3)', fontSize: '10px' }}>Loading email...</div>`}
                    ${!s.loadingBody && s.fullBody && html`
                      <div style=${{ fontSize: '11px', color: 'rgba(255,255,255,0.4)', lineHeight: '1.5', maxHeight: '200px', overflowY: 'auto', whiteSpace: 'pre-wrap', wordBreak: 'break-word', padding: '6px 8px', background: 'rgba(0,0,0,0.2)', borderRadius: '6px', marginBottom: '8px' }}>${formatBody(s.fullBody)}</div>
                    `}
                    ${!s.loadingBody && !s.fullBody && html`
                      <div style=${{ fontSize: '11px', color: 'rgba(255,255,255,0.3)', lineHeight: '1.4', marginBottom: '8px' }}>
                        ${em.snippet || 'No preview available'}
                      </div>
                    `}
                    <div style=${{ display: 'flex', gap: '6px' }}>
                      <button class="widget-btn" onClick=${function(e) { e.stopPropagation(); handleReply(em); }} style=${{ padding: '4px 10px', borderRadius: '6px', border: '1px solid rgba(255,255,255,0.06)', background: 'rgba(255,255,255,0.03)', color: 'rgba(255,255,255,0.4)', cursor: 'pointer', fontSize: '10px', display: 'flex', alignItems: 'center', gap: '4px' }}><${Li} name="Reply" size=${10} color="rgba(255,255,255,0.4)" /> Reply</button>
                      <button class="widget-btn" onClick=${function(e) { e.stopPropagation(); handleForward(em); }} style=${{ padding: '4px 10px', borderRadius: '6px', border: '1px solid rgba(255,255,255,0.06)', background: 'rgba(255,255,255,0.03)', color: 'rgba(255,255,255,0.4)', cursor: 'pointer', fontSize: '10px', display: 'flex', alignItems: 'center', gap: '4px' }}><${Li} name="Forward" size=${10} color="rgba(255,255,255,0.4)" /> Forward</button>
                    </div>
                  </div>
                `}
              </div>
            `;
          })}
        </div>
      </div>
    </${Widget}>
  `;
}

// ─── Telegram Widget ──────────────────────────────────
function TelegramWidget(props) {
  var mockChats = [
    { id: 1, name: 'Dev Community', msg: 'Clinton: just pushed the new update 🚀', time: '1m', unread: 3, online: true, avatar: '#60A5FA' },
    { id: 2, name: 'Mum ❤️', msg: 'Don\'t forget to eat o!', time: '15m', unread: 1, online: true, avatar: '#F472B6' },
    { id: 3, name: 'Lagos Coders', msg: 'Anyone know a good ReactNative tutor?', time: '30m', unread: 0, online: false, avatar: '#34D399' },
    { id: 4, name: 'Ola', msg: 'Check this out bro', time: '1h', unread: 0, online: true, avatar: '#FBBF24' },
    { id: 5, name: 'Nally Bot', msg: 'Daily summary ready', time: '2h', unread: 0, online: false, avatar: '#00D4FF' },
    { id: 6, name: 'Class Group', msg: 'Assignment deadline extended to Friday', time: '4h', unread: 5, online: false, avatar: '#A78BFA' },
    { id: 7, name: 'Chidi', msg: 'You dey code? Make we link up', time: '6h', unread: 0, online: false, avatar: '#FB923C' },
  ];

  var state = useState({ chats: [], activeChat: null, loading: true, configured: null, messages: [] });
  var s = state[0], setS = state[1];

  // Fetch real Telegram data on mount
  useEffect(function() {
    fetch(BACKEND + '/api/telegram/chats')
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.configured && data.authenticated && data.chats && data.chats.length > 0) {
          var avatarColors = ['#60A5FA', '#F472B6', '#34D399', '#FBBF24', '#00D4FF', '#A78BFA', '#FB923C'];
          var chats = data.chats.map(function(c, i) {
            return Object.assign({}, c, { avatar: avatarColors[i % avatarColors.length] });
          });
          setS({ chats: chats, activeChat: null, loading: false, configured: true, messages: [] });
        } else if (data.configured === false) {
          setS({ chats: mockChats, activeChat: null, loading: false, configured: false, messages: [] });
        } else {
          setS({ chats: mockChats, activeChat: null, loading: false, configured: data.configured, messages: [] });
        }
      })
      .catch(function() {
        setS({ chats: mockChats, activeChat: null, loading: false, configured: false, messages: [] });
      });
  }, []);

  var unreadCount = s.chats.reduce(function(sum, c) { return sum + c.unread; }, 0);

  function openChat(id) {
    setS(function(p) {
      var chats = p.chats.map(function(c) {
        return c.id === id ? Object.assign({}, c, { unread: 0 }) : c;
      });
      return Object.assign({}, p, { chats: chats, activeChat: p.activeChat === id ? null : id, messages: [] });
    });
    beep(700, 0.02, 'sine');

    // Fetch messages for this chat
    fetch(BACKEND + '/api/telegram/messages/' + id)
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.messages) {
          setS(function(p) { return Object.assign({}, p, { messages: data.messages }); });
        }
      })
      .catch(function() {});
  }

  function sendMessage(chatId, text) {
    if (!text.trim()) return;
    fetch(BACKEND + '/api/telegram/send', {
      method: 'POST',
      headers: _authHeaders(),
      body: JSON.stringify({ chat_id: chatId, text: text }),
    })
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.ok) {
          setS(function(p) {
            var msgs = p.messages.concat([{ from: 'You', text: text, date: Math.floor(Date.now() / 1000) }]);
            return Object.assign({}, p, { messages: msgs });
          });
        }
      })
      .catch(function() {});
  }

  return html`
    <${Widget} ...${props} title="Telegram" icon="Send" iconColor="rgba(96,165,250,0.7)" width="280">
      <div>
        <div style=${{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' }}>
          <div style=${{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span style=${{ fontSize: '11px', color: 'rgba(255,255,255,0.3)' }}>Chats</span>
            ${unreadCount > 0 && html`<span style=${{ fontSize: '10px', color: '#60A5FA', background: 'rgba(96,165,250,0.1)', padding: '1px 6px', borderRadius: '999px', fontWeight: 600 }}>${unreadCount} unread</span>`}
            ${s.configured === false && html`<span style=${{ fontSize: '9px', color: '#FBBF24', background: 'rgba(251,191,36,0.1)', padding: '1px 6px', borderRadius: '999px' }}>Mock</span>`}
          </div>
        </div>
        <div style=${{ display: 'flex', flexDirection: 'column', gap: '2px', maxHeight: '280px', overflowY: 'auto' }}>
          ${s.loading && html`<div style=${{ textAlign: 'center', padding: '20px', color: 'rgba(255,255,255,0.3)', fontSize: '11px' }}>Loading chats...</div>`}
          ${!s.loading && s.chats.map(function(chat) {
            var active = s.activeChat === chat.id;
            return html`
              <div key=${chat.id} onClick=${function() { openChat(chat.id); }} style=${{
                padding: '8px 10px', borderRadius: '8px', cursor: 'pointer',
                background: active ? 'rgba(96,165,250,0.06)' : 'transparent',
                transition: 'background 0.15s',
              }}>
                <div style=${{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <div style=${{ position: 'relative', flexShrink: 0 }}>
                    <div style=${{
                      width: '32px', height: '32px', borderRadius: '50%',
                      background: (chat.avatar || '#60A5FA') + '20', display: 'flex', alignItems: 'center', justifyContent: 'center',
                      fontSize: '13px', fontWeight: 700, color: chat.avatar || '#60A5FA',
                    }}>${(chat.name || '?').charAt(0)}</div>
                    ${chat.online && html`<div style=${{ position: 'absolute', bottom: '0px', right: '0px', width: '8px', height: '8px', borderRadius: '50%', background: '#34D399', border: '2px solid rgba(13,17,23,0.85)' }} />`}
                  </div>
                  <div style=${{ flex: 1, minWidth: 0 }}>
                    <div style=${{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span style=${{ fontSize: '12px', fontWeight: 500, color: '#E2E8F0' }}>${chat.name}</span>
                      <span style=${{ fontSize: '9px', color: 'rgba(255,255,255,0.2)', fontFamily: 'monospace' }}>${chat.time}</span>
                    </div>
                    <div style=${{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '2px' }}>
                      <span style=${{ fontSize: '11px', color: 'rgba(255,255,255,0.3)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', flex: 1 }}>${chat.msg}</span>
                      ${chat.unread > 0 && html`<span style=${{ fontSize: '9px', color: '#000', background: '#60A5FA', borderRadius: '999px', padding: '1px 5px', fontWeight: 700, flexShrink: 0, marginLeft: '6px' }}>${chat.unread}</span>`}
                    </div>
                  </div>
                </div>
                ${active && html`
                  <div style=${{ marginTop: '8px', paddingTop: '8px', borderTop: '1px solid rgba(255,255,255,0.04)' }}>
                    ${s.messages.length > 0 && html`
                      <div style=${{ maxHeight: '120px', overflowY: 'auto', marginBottom: '6px' }}>
                        ${s.messages.map(function(m, i) {
                          return html`<div key=${i} style=${{ fontSize: '10px', color: 'rgba(255,255,255,0.4)', padding: '2px 0' }}><span style=${{ color: 'rgba(96,165,250,0.8)' }}>${m.from}:</span> ${m.text}</div>`;
                        })}
                      </div>
                    `}
                    <div style=${{ display: 'flex', gap: '6px' }}>
                      <input type="text" placeholder="Message..." onKeyDown=${function(e) { if (e.key === 'Enter') { sendMessage(chat.id, e.target.value); e.target.value = ''; } }} style=${{ flex: 1, height: '28px', background: 'rgba(0,0,0,0.3)', border: '1px solid rgba(255,255,255,0.04)', borderRadius: '6px', padding: '0 8px', color: '#E2E8F0', fontSize: '11px', outline: 'none' }} />
                      <button class="widget-btn" onClick=${function(e) { var input = e.target.closest('div').querySelector('input'); sendMessage(chat.id, input.value); input.value = ''; }} style=${{ width: '28px', height: '28px', borderRadius: '6px', border: 'none', background: 'rgba(96,165,250,0.15)', color: '#60A5FA', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}><${Li} name="Send" size=${12} color="#60A5FA" /></button>
                    </div>
                  </div>
                `}
              </div>
            `;
          })}
        </div>
      </div>
    </${Widget}>
  `;
}

// ─── WhatsApp Widget ──────────────────────────────────
function WhatsAppWidget(props) {
  var mockChats = [
    { id: 1, name: 'Dad', msg: 'How far? How school dey go?', time: '5m', unread: 2, online: true, avatar: '#25D366' },
    { id: 2, name: 'Aunty Bimpe', msg: 'Happy birthday in advance! 🎂', time: '30m', unread: 0, online: false, avatar: '#FF6B6B' },
    { id: 3, name: 'Project Group', msg: 'Tunde: I\'ll send the API docs tonight', time: '1h', unread: 4, online: false, avatar: '#A78BFA' },
    { id: 4, name: 'Sade', msg: 'See you tomorrow!', time: '2h', unread: 0, online: true, avatar: '#FBBF24' },
    { id: 5, name: 'Church Group', msg: 'Service starts at 9am sharp', time: '3h', unread: 0, online: false, avatar: '#34D399' },
    { id: 6, name: 'Emeka', msg: 'Bro check this restaurant out', time: '5h', unread: 1, online: false, avatar: '#FB923C' },
  ];

  var saved = lsload('whatsapp', { chats: mockChats, activeChat: null });
  var state = useState(saved);
  var s = state[0], setS = state[1];

  useEffect(function() { lssave('whatsapp', s); }, [s]);

  var unreadCount = s.chats.reduce(function(sum, c) { return sum + c.unread; }, 0);

  function openChat(id) {
    setS(function(p) {
      var chats = p.chats.map(function(c) {
        return c.id === id ? Object.assign({}, c, { unread: 0 }) : c;
      });
      return Object.assign({}, p, { chats: chats, activeChat: p.activeChat === id ? null : id });
    });
    beep(700, 0.02, 'sine');
  }

  return html`
    <${Widget} ...${props} title="WhatsApp" icon="Phone" iconColor="rgba(37,211,102,0.7)" width="280">
      <div>
        <div style=${{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' }}>
          <div style=${{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span style=${{ fontSize: '11px', color: 'rgba(255,255,255,0.3)' }}>Chats</span>
            ${unreadCount > 0 && html`<span style=${{ fontSize: '10px', color: '#25D366', background: 'rgba(37,211,102,0.1)', padding: '1px 6px', borderRadius: '999px', fontWeight: 600 }}>${unreadCount} unread</span>`}
          </div>
        </div>
        <div style=${{ display: 'flex', flexDirection: 'column', gap: '2px', maxHeight: '280px', overflowY: 'auto' }}>
          ${s.chats.map(function(chat) {
            var active = s.activeChat === chat.id;
            return html`
              <div key=${chat.id} onClick=${function() { openChat(chat.id); }} style=${{
                padding: '8px 10px', borderRadius: '8px', cursor: 'pointer',
                background: active ? 'rgba(37,211,102,0.06)' : 'transparent',
                transition: 'background 0.15s',
              }}>
                <div style=${{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <div style=${{ position: 'relative', flexShrink: 0 }}>
                    <div style=${{
                      width: '32px', height: '32px', borderRadius: '50%',
                      background: chat.avatar + '20', display: 'flex', alignItems: 'center', justifyContent: 'center',
                      fontSize: '13px', fontWeight: 700, color: chat.avatar,
                    }}>${chat.name.charAt(0)}</div>
                    ${chat.online && html`<div style=${{ position: 'absolute', bottom: '0px', right: '0px', width: '8px', height: '8px', borderRadius: '50%', background: '#25D366', border: '2px solid rgba(13,17,23,0.85)' }} />`}
                  </div>
                  <div style=${{ flex: 1, minWidth: 0 }}>
                    <div style=${{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span style=${{ fontSize: '12px', fontWeight: 500, color: '#E2E8F0' }}>${chat.name}</span>
                      <span style=${{ fontSize: '9px', color: chat.unread > 0 ? '#25D366' : 'rgba(255,255,255,0.2)', fontFamily: 'monospace' }}>${chat.time}</span>
                    </div>
                    <div style=${{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '2px' }}>
                      <span style=${{ fontSize: '11px', color: 'rgba(255,255,255,0.3)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', flex: 1 }}>${chat.msg}</span>
                      ${chat.unread > 0 && html`<span style=${{ fontSize: '9px', color: '#000', background: '#25D366', borderRadius: '999px', padding: '1px 5px', fontWeight: 700, flexShrink: 0, marginLeft: '6px' }}>${chat.unread}</span>`}
                    </div>
                  </div>
                </div>
                ${active && html`
                  <div style=${{ marginTop: '8px', paddingTop: '8px', borderTop: '1px solid rgba(255,255,255,0.04)' }}>
                    <div style=${{ display: 'flex', gap: '6px' }}>
                      <input type="text" placeholder="Message..." style=${{ flex: 1, height: '28px', background: 'rgba(0,0,0,0.3)', border: '1px solid rgba(255,255,255,0.04)', borderRadius: '6px', padding: '0 8px', color: '#E2E8F0', fontSize: '11px', outline: 'none' }} />
                      <button class="widget-btn" style=${{ width: '28px', height: '28px', borderRadius: '6px', border: 'none', background: 'rgba(37,211,102,0.15)', color: '#25D366', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}><${Li} name="Send" size=${12} color="#25D366" /></button>
                    </div>
                  </div>
                `}
              </div>
            `;
          })}
        </div>
      </div>
    </${Widget}>
  `;
}

// ─── Clock Widget ─────────────────────────────────────
function ClockWidget(props) {
  var tick = useState(new Date());
  var time = tick[0], setTime = tick[1];

  useEffect(function() {
    var iv = setInterval(function() { setTime(new Date()); }, 1000);
    return function() { clearInterval(iv); };
  }, []);

  var h = time.getHours().toString().padStart(2, '0');
  var m = time.getMinutes().toString().padStart(2, '0');
  var s = time.getSeconds().toString().padStart(2, '0');
  var days = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
  var months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

  return html`
    <${Widget} ...${props} title="Clock" icon="Clock" iconColor="rgba(0,212,255,0.6)" width="220">
      <div style=${{ textAlign: 'center' }}>
        <div style=${{ fontSize: '36px', fontFamily: 'Orbitron,monospace', fontWeight: 700, color: '#E2E8F0', letterSpacing: '2px', lineHeight: 1 }}>
          <span>${h}</span><span style=${{ color: 'rgba(0,212,255,0.5)', animation: 'pulse 1s infinite' }}>:</span><span>${m}</span>
          <span style=${{ fontSize: '14px', color: 'rgba(0,212,255,0.4)', fontFamily: 'monospace', marginLeft: '4px' }}>${s}</span>
        </div>
        <div style=${{ fontSize: '11px', color: 'rgba(255,255,255,0.3)', marginTop: '8px', fontFamily: 'monospace', letterSpacing: '1px' }}>
          ${days[time.getDay()]} ${time.getDate()} ${months[time.getMonth()]} ${time.getFullYear()}
        </div>
      </div>
    </${Widget}>
  `;
}

// ─── Weather Widget ───────────────────────────────────
function WeatherWidget(props) {
  var data = useState({ temp: '--', desc: 'Loading...', icon: 'Cloud', humidity: '--', wind: '--' });
  var w = data[0], setW = data[1];

  useEffect(function() {
    // Mock for now — swap with real API later
    setTimeout(function() {
      setW({ temp: '27', desc: 'Partly Cloudy', icon: 'Cloud', humidity: '72', wind: '14' });
    }, 800);
  }, []);

  return html`
    <${Widget} ...${props} title="Weather" icon="Cloud" iconColor="rgba(96,165,250,0.7)" width="220">
      <div style=${{ display: 'flex', alignItems: 'center', gap: '12px' }}>
        <div style=${{ fontSize: '32px', lineHeight: 1 }}><${Li} name=${w.icon} size=${36} color="rgba(96,165,250,0.7)" /></div>
        <div>
          <div style=${{ fontSize: '28px', fontWeight: 700, color: '#E2E8F0', lineHeight: 1 }}>${w.temp}°</div>
          <div style=${{ fontSize: '11px', color: 'rgba(255,255,255,0.35)', marginTop: '2px' }}>${w.desc}</div>
        </div>
      </div>
      <div style=${{ display: 'flex', gap: '16px', marginTop: '10px', paddingTop: '10px', borderTop: '1px solid rgba(255,255,255,0.04)' }}>
        <div style=${{ fontSize: '11px', color: 'rgba(255,255,255,0.3)' }}><span style=${{ color: 'rgba(96,165,250,0.5)' }}>💧</span> ${w.humidity}%</div>
        <div style=${{ fontSize: '11px', color: 'rgba(255,255,255,0.3)' }}><span style=${{ color: 'rgba(96,165,250,0.5)' }}>💨</span> ${w.wind} km/h</div>
      </div>
    </${Widget}>
  `;
}

// ─── Quick Notes Widget ───────────────────────────────
function NotesWidget(props) {
  var saved = '';
  try { saved = localStorage.getItem('nally-notes') || ''; } catch(e) {}
  var note = useState(saved);
  var text = note[0], setText = note[1];

  useEffect(function() {
    try { localStorage.setItem('nally-notes', text); } catch(e) {}
  }, [text]);

  return html`
    <${Widget} ...${props} title="Notes" icon="StickyNote" iconColor="rgba(250,204,21,0.6)" width="260">
      <textarea value=${text} onInput=${function(e) { setText(e.target.value); }} placeholder="Quick notes..." style=${{
        width: '100%', height: '120px', background: 'rgba(0,0,0,0.3)', border: '1px solid rgba(255,255,255,0.04)',
        borderRadius: '10px', padding: '10px 12px', color: '#E2E8F0', fontSize: '12px', lineHeight: '1.6',
        fontFamily: 'Inter,system-ui,sans-serif', resize: 'vertical', outline: 'none',
        transition: 'border-color 0.2s',
      }} />
      <div style=${{ fontSize: '10px', color: 'rgba(255,255,255,0.15)', marginTop: '6px', textAlign: 'right' }}>${text.length} chars</div>
    </${Widget}>
  `;
}

// ─── System Status Widget ─────────────────────────────
function StatusWidget(props) {
  var uptime = useState(0);
  var u = uptime[0], setU = uptime[1];

  useEffect(function() {
    var start = Date.now();
    var iv = setInterval(function() { setU(Math.floor((Date.now() - start) / 1000)); }, 1000);
    return function() { clearInterval(iv); };
  }, []);

  function fmt(s) {
    var h = Math.floor(s / 3600);
    var m = Math.floor((s % 3600) / 60);
    var sec = s % 60;
    return (h > 0 ? h + 'h ' : '') + m + 'm ' + sec + 's';
  }

  var memUsed = Math.round(performance.memory ? performance.memory.usedJSHeapSize / 1048576 : 0);
  var memTotal = Math.round(performance.memory ? performance.memory.jsHeapSizeLimit / 1048576 : 0);

  return html`
    <${Widget} ...${props} title="Status" icon="Activity" iconColor="rgba(52,211,153,0.6)" width="220">
      <div style=${{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        <div style=${{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style=${{ fontSize: '11px', color: 'rgba(255,255,255,0.3)' }}>Backend</span>
          <span style=${{ display: 'flex', alignItems: 'center', gap: '5px', fontSize: '11px', color: props.connected ? 'rgba(52,211,153,0.7)' : 'rgba(248,113,113,0.7)' }}>
            <span style=${{ width: '6px', height: '6px', borderRadius: '50%', background: props.connected ? '#34D399' : '#F87171', boxShadow: '0 0 6px ' + (props.connected ? 'rgba(52,211,153,0.5)' : 'rgba(248,113,113,0.5)') }} />
            ${props.connected ? 'Online' : 'Offline'}
          </span>
        </div>
        <div style=${{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style=${{ fontSize: '11px', color: 'rgba(255,255,255,0.3)' }}>Uptime</span>
          <span style=${{ fontSize: '11px', fontFamily: 'monospace', color: 'rgba(0,212,255,0.5)' }}>${fmt(u)}</span>
        </div>
        ${memUsed > 0 && html`
          <div style=${{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style=${{ fontSize: '11px', color: 'rgba(255,255,255,0.3)' }}>Memory</span>
            <span style=${{ fontSize: '11px', fontFamily: 'monospace', color: 'rgba(0,212,255,0.5)' }}>${memUsed}/${memTotal} MB</span>
          </div>
        `}
        <div style=${{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style=${{ fontSize: '11px', color: 'rgba(255,255,255,0.3)' }}>Messages</span>
          <span style=${{ fontSize: '11px', fontFamily: 'monospace', color: 'rgba(0,212,255,0.5)' }}>${props.msgCount || 0}</span>
        </div>
      </div>
    </${Widget}>
  `;
}

// ─── Task List Widget ─────────────────────────────────
function TaskWidget(props) {
  var saved = [];
  try { saved = JSON.parse(localStorage.getItem('nally-tasks') || '[]'); } catch(e) {}
  var tasks = useState(saved);
  var list = tasks[0], setList = tasks[1];
  var input = useState('');
  var val = input[0], setVal = input[1];

  useEffect(function() {
    try { localStorage.setItem('nally-tasks', JSON.stringify(list)); } catch(e) {}
  }, [list]);

  function addTask(e) {
    e.preventDefault();
    if (!val.trim()) return;
    setList(function(p) { return p.concat([{ id: Date.now(), text: val.trim(), done: false }]); });
    setVal('');
    beep(900, 0.02, 'sine');
  }

  function toggleTask(id) {
    setList(function(p) { return p.map(function(t) { return t.id === id ? Object.assign({}, t, { done: !t.done }) : t; }); });
    beep(700, 0.02, 'sine');
  }

  function removeTask(id) {
    setList(function(p) { return p.filter(function(t) { return t.id !== id; }); });
    beep(500, 0.02, 'sine');
  }

  return html`
    <${Widget} ...${props} title="Tasks" icon="ListTodo" iconColor="rgba(168,85,247,0.6)" width="260">
      <form onSubmit=${addTask} style=${{ display: 'flex', gap: '6px', marginBottom: '10px' }}>
        <input type="text" value=${val} onInput=${function(e) { setVal(e.target.value); }} placeholder="Add task..." style=${{
          flex: 1, height: '32px', background: 'rgba(0,0,0,0.3)', border: '1px solid rgba(255,255,255,0.04)',
          borderRadius: '8px', padding: '0 10px', color: '#E2E8F0', fontSize: '12px', outline: 'none',
          fontFamily: 'Inter,system-ui,sans-serif',
        }} />
        <button type="submit" style=${{
          width: '32px', height: '32px', borderRadius: '8px', border: 'none',
          background: val.trim() ? 'rgba(168,85,247,0.2)' : 'rgba(255,255,255,0.04)',
          color: val.trim() ? 'rgba(168,85,247,0.7)' : 'rgba(255,255,255,0.15)',
          cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}><${Li} name="Plus" size=${14} color=${val.trim() ? 'rgba(168,85,247,0.7)' : 'rgba(255,255,255,0.15)'} /></button>
      </form>
      <div style=${{ maxHeight: '160px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '4px' }}>
        ${list.length === 0 && html`<div style=${{ fontSize: '11px', color: 'rgba(255,255,255,0.15)', textAlign: 'center', padding: '12px 0' }}>No tasks yet</div>`}
        ${list.map(function(t) {
          return html`
            <div key=${t.id} style=${{ display: 'flex', alignItems: 'center', gap: '8px', padding: '6px 8px', borderRadius: '8px', background: t.done ? 'rgba(52,211,153,0.04)' : 'rgba(255,255,255,0.02)', transition: 'background 0.2s' }}>
              <button onClick=${function() { toggleTask(t.id); }} style=${{
                width: '18px', height: '18px', borderRadius: '5px', border: '1.5px solid ' + (t.done ? 'rgba(52,211,153,0.5)' : 'rgba(255,255,255,0.12)'),
                background: t.done ? 'rgba(52,211,153,0.15)' : 'transparent', cursor: 'pointer',
                display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, transition: 'all 0.2s',
              }}>${t.done ? html`<${Li} name="Check" size=${10} color="#34D399" />` : ''}</button>
              <span style=${{ flex: 1, fontSize: '12px', color: t.done ? 'rgba(255,255,255,0.25)' : 'rgba(255,255,255,0.6)', textDecoration: t.done ? 'line-through' : 'none', transition: 'all 0.2s' }}>${t.text}</span>
              <button onClick=${function() { removeTask(t.id); }} style=${{
                width: '20px', height: '20px', borderRadius: '5px', border: 'none', background: 'transparent',
                color: 'rgba(255,255,255,0.15)', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
                opacity: 0, transition: 'opacity 0.2s',
              }} className="task-del"><${Li} name="X" size=${10} color="rgba(255,255,255,0.2)" /></button>
            </div>
          `;
        })}
      </div>
      ${list.length > 0 && html`
        <div style=${{ display: 'flex', justifyContent: 'space-between', marginTop: '8px', paddingTop: '8px', borderTop: '1px solid rgba(255,255,255,0.04)' }}>
          <span style=${{ fontSize: '10px', color: 'rgba(255,255,255,0.15)' }}>${list.filter(function(t) { return t.done; }).length}/${list.length} done</span>
          ${list.some(function(t) { return t.done; }) && html`<button onClick=${function() { setList(function(p) { return p.filter(function(t) { return !t.done; }); }); beep(500, 0.02, 'sine'); }} style=${{ fontSize: '10px', color: 'rgba(248,113,113,0.5)', background: 'none', border: 'none', cursor: 'pointer' }}>Clear done</button>`}
        </div>
      `}
    </${Widget}>
  `;
}

// ─── Music Player Widget ──────────────────────────────
function MusicWidget(props) {
  var platforms = [
    { id: 'spotify', name: 'Spotify', color: '#1DB954', bg: 'rgba(29,185,84,0.08)', border: 'rgba(29,185,84,0.2)' },
    { id: 'apple', name: 'Apple Music', color: '#FC3C44', bg: 'rgba(252,60,68,0.08)', border: 'rgba(252,60,68,0.2)' },
    { id: 'youtube', name: 'YouTube Music', color: '#FF0000', bg: 'rgba(255,0,0,0.08)', border: 'rgba(255,0,0,0.2)' },
    { id: 'audiomack', name: 'Audiomack', color: '#FFA200', bg: 'rgba(255,162,0,0.08)', border: 'rgba(255,162,0,0.2)' }
  ];

  var saved = lsload('music', { platform: 'spotify', playing: false, title: '', artist: '', album: '', progress: 0, duration: 0, volume: 75 });
  var state = useState(saved);
  var s = state[0], setS = state[1];

  useEffect(function() { lssave('music', s); }, [s]);

  var pl = platforms.find(function(p) { return p.id === s.platform; }) || platforms[0];

  // Simulated playback timer
  var ivRef = useRef(null);
  useEffect(function() {
    if (s.playing && s.duration > 0) {
      ivRef.current = setInterval(function() {
        setS(function(p) {
          if (p.progress >= p.duration) {
            return Object.assign({}, p, { playing: false, progress: 0 });
          }
          return Object.assign({}, p, { progress: p.progress + 1 });
        });
      }, 1000);
    }
    return function() { if (ivRef.current) clearInterval(ivRef.current); };
  }, [s.playing, s.duration]);

  function fmtTime(sec) {
    var m = Math.floor(sec / 60);
    var s = Math.floor(sec % 60);
    return m + ':' + (s < 10 ? '0' : '') + s;
  }

  function setPlatform(id) {
    setS(function(p) { return Object.assign({}, p, { platform: id }); });
    beep(800, 0.02, 'sine');
  }

  function togglePlay() {
    setS(function(p) { return Object.assign({}, p, { playing: !p.playing }); });
    beep(s.playing ? 500 : 700, 0.03, 'sine');
  }

  function prevTrack() {
    setS(function(p) { return Object.assign({}, p, { progress: 0 }); });
    beep(600, 0.02, 'sine');
  }

  function nextTrack() {
    setS(function(p) { return Object.assign({}, p, { progress: 0, playing: true }); });
    beep(900, 0.02, 'sine');
  }

  var pct = s.duration > 0 ? (s.progress / s.duration) * 100 : 0;

  return html`
    <${Widget} ...${props} title="Music" icon="Music" iconColor="${pl.color}" width="280">
      <div>
        <div style=${{ display: 'flex', gap: '2px', marginBottom: '12px', background: 'rgba(0,0,0,0.3)', borderRadius: '8px', padding: '3px' }}>
          ${platforms.map(function(p) {
            var active = s.platform === p.id;
            return html`
              <button key=${p.id} onClick=${function() { setPlatform(p.id); }} style=${{
                flex: 1, padding: '5px 0', borderRadius: '6px', border: 'none', fontSize: '9px', fontWeight: 600,
                letterSpacing: '0.5px', cursor: 'pointer', transition: 'all 0.2s', fontFamily: 'Inter,system-ui,sans-serif',
                background: active ? p.bg : 'transparent',
                color: active ? p.color : 'rgba(255,255,255,0.2)',
                border: active ? '1px solid ' + p.border : '1px solid transparent',
              }}>${p.name}</button>
            `;
          })}
        </div>

        <div style=${{ display: 'flex', gap: '12px', alignItems: 'center', marginBottom: '12px' }}>
          <div style=${{
            width: '56px', height: '56px', borderRadius: '10px', flexShrink: 0,
            background: 'linear-gradient(135deg, ' + pl.color + '22, ' + pl.color + '08)',
            border: '1px solid ' + pl.color + '15',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}><${Li} name="Music" size=${22} color=${pl.color + '80'} /></div>
          <div style=${{ flex: 1, minWidth: 0 }}>
            <div style=${{ fontSize: '13px', fontWeight: 600, color: '#E2E8F0', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>${s.title || 'Not playing'}</div>
            <div style=${{ fontSize: '11px', color: 'rgba(255,255,255,0.3)', marginTop: '2px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>${s.artist || 'Select a track'}</div>
            ${s.album && html`<div style=${{ fontSize: '10px', color: 'rgba(255,255,255,0.15)', marginTop: '2px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>${s.album}</div>`}
          </div>
        </div>

        <div style=${{ marginBottom: '10px' }}>
          <div style=${{ height: '3px', background: 'rgba(255,255,255,0.06)', borderRadius: '3px', overflow: 'hidden', cursor: 'pointer' }}
            onClick=${function(e) {
              var rect = e.currentTarget.getBoundingClientRect();
              var x = e.clientX - rect.left;
              var pct = Math.max(0, Math.min(1, x / rect.width));
              setS(function(p) { return Object.assign({}, p, { progress: Math.floor(pct * p.duration) }); });
            }}>
            <div style=${{ height: '100%', width: pct + '%', background: pl.color, borderRadius: '3px', transition: s.playing ? 'none' : 'width 0.1s' }} />
          </div>
          <div style=${{ display: 'flex', justifyContent: 'space-between', marginTop: '4px' }}>
            <span style=${{ fontSize: '9px', fontFamily: 'monospace', color: 'rgba(255,255,255,0.2)' }}>${fmtTime(s.progress)}</span>
            <span style=${{ fontSize: '9px', fontFamily: 'monospace', color: 'rgba(255,255,255,0.2)' }}>${fmtTime(s.duration)}</span>
          </div>
        </div>

        <div style=${{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '16px', marginBottom: '10px' }}>
          <button onClick=${prevTrack} style=${{
            width: '32px', height: '32px', borderRadius: '50%', border: 'none', background: 'transparent',
            color: 'rgba(255,255,255,0.4)', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
            transition: 'all 0.15s',
          }}><${Li} name="SkipBack" size=${16} color="rgba(255,255,255,0.4)" /></button>
          <button onClick=${togglePlay} style=${{
            width: '40px', height: '40px', borderRadius: '50%', border: 'none',
            background: s.playing ? pl.color : 'rgba(255,255,255,0.08)',
            color: s.playing ? '#000' : 'rgba(255,255,255,0.5)',
            cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
            transition: 'all 0.2s', boxShadow: s.playing ? '0 0 16px ' + pl.color + '40' : 'none',
          }}>${s.playing ? html`<${Li} name="Pause" size=${18} color="#000" />` : html`<${Li} name="Play" size=${18} color="rgba(255,255,255,0.5)" />`}</button>
          <button onClick=${nextTrack} style=${{
            width: '32px', height: '32px', borderRadius: '50%', border: 'none', background: 'transparent',
            color: 'rgba(255,255,255,0.4)', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
            transition: 'all 0.15s',
          }}><${Li} name="SkipForward" size=${16} color="rgba(255,255,255,0.4)" /></button>
        </div>

        <div style=${{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <${Li} name="Volume2" size=${12} color="rgba(255,255,255,0.2)" />
          <div style=${{ flex: 1, height: '3px', background: 'rgba(255,255,255,0.06)', borderRadius: '3px', cursor: 'pointer', position: 'relative' }}
            onClick=${function(e) {
              var rect = e.currentTarget.getBoundingClientRect();
              var x = e.clientX - rect.left;
              var pct = Math.max(0, Math.min(100, Math.round((x / rect.width) * 100)));
              setS(function(p) { return Object.assign({}, p, { volume: pct }); });
            }}>
            <div style=${{ height: '100%', width: s.volume + '%', background: 'rgba(255,255,255,0.2)', borderRadius: '3px' }} />
          </div>
          <span style=${{ fontSize: '9px', fontFamily: 'monospace', color: 'rgba(255,255,255,0.15)', minWidth: '24px', textAlign: 'right' }}>${s.volume}%</span>
        </div>
      </div>
    </${Widget}>
  `;
}

// ─── App ──────────────────────────────────────────────
function App() {
  var _active = useState(function() { return lsload('active', false); });
  var active = _active[0], setActive = _active[1];
  var _msgs = useState(function() { return lsload('messages', []); });
  var messages = _msgs[0], setMessages = _msgs[1];
  var _thinking = useState(false);
  var thinking = _thinking[0], setThinking = _thinking[1];
  var _tool = useState('');
  var activeTool = _tool[0], setActiveTool = _tool[1];
  var _conn = useState(false);
  var connected = _conn[0], setConnected = _conn[1];
  var _widgets = useState(function() { return lsload('widgetsOn', true); });
  var widgetsOn = _widgets[0], setWidgetsOn = _widgets[1];
  var _widgetList = useState(function() {
    var saved = lsload('widgetList', null);
    var defaults = ['clock', 'email', 'telegram', 'whatsapp', 'weather', 'music', 'notes', 'status', 'tasks'];
    if (!saved) return defaults;
    var merged = saved.slice();
    defaults.forEach(function(w) { if (merged.indexOf(w) === -1) merged.push(w); });
    return merged;
  });
  var widgetList = _widgetList[0], setWidgetList = _widgetList[1];
  var _wpos = useState(function() { return lsload('widgetPos', {}); });
  var wpos = _wpos[0], setWpos = _wpos[1];
  var _wcol = useState(function() { return lsload('widgetCol', {}); });
  var wcol = _wcol[0], setWcol = _wcol[1];
  var _wmin = useState(function() { return lsload('widgetMin', {}); });
  var wmin = _wmin[0], setWmin = _wmin[1];

  // Dynamic panels (created by ui_control tool)
  var _dynPanels = useState({});
  var dynamicPanels = _dynPanels[0], setDynamicPanels = _dynPanels[1];

  // Dedup: track if streaming already delivered content this round
  var _streamedThisRound = [false];

  // Approval gate state
  var _approval = useState(null);
  var pendingApproval = _approval[0], setPendingApproval = _approval[1];

  // Persist state on changes
  useEffect(function() { lssave('active', active); }, [active]);
  useEffect(function() { lssave('messages', messages); }, [messages]);
  useEffect(function() { lssave('widgetsOn', widgetsOn); }, [widgetsOn]);
  useEffect(function() { lssave('widgetList', widgetList); }, [widgetList]);
  useEffect(function() { lssave('widgetPos', wpos); }, [wpos]);
  useEffect(function() { lssave('widgetCol', wcol); }, [wcol]);
  useEffect(function() { lssave('widgetMin', wmin); }, [wmin]);

  // Auto-activate if returning with active state
  useEffect(function() {
    if (active) beep(680, 0.1, 'triangle');
  }, []);

  useEffect(function() {
    console.log('[NALLY] App mounted, initializing SSE...');
    initSocket(
      function() { setConnected(true); },
      function() { setConnected(false); }
    );

    return function() {
      if (_sseAbort) _sseAbort.abort();
    };
  }, []);

  function handleSend(text) {
    beep(425, 0.06, 'sine');
    setMessages(function(p) { return p.concat([{ id: 'u-' + Date.now(), sender: 'user', text: text, stamp: stamp() }]); });
    setThinking(true);

    var _streamId = null;
    var _streamText = '';

    sendMsg(text, {
      onEvent: function(event) {
        if (event.type === 'thinking') {
          setThinking(true);
        } else if (event.type === 'idle') {
          setThinking(false);
          setActiveTool('');
        } else if (event.type === 'tool_call') {
          setActiveTool(event.name);
          beep(1200, 0.02, 'square');
          setMessages(function(p) { return p.concat([{ id: 'tc-' + Date.now(), type: 'tool_call', name: event.name }]); });
        } else if (event.type === 'tool_result') {
          setActiveTool('');
          beep(event.success ? 800 : 300, 0.03, 'sine');
          setMessages(function(p) {
            return p.map(function(m) {
              return (m.type === 'tool_call' && m.name === event.name && m.duration_ms == null)
                ? Object.assign({}, m, { result: event.result, duration_ms: event.duration_ms, success: event.success })
                : m;
            });
          });
        } else if (event.type === 'stream_chunk') {
          var chunk = event.text || '';
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
        } else if (event.type === 'response') {
          var respText = event.text || event.response || '';
          if (_streamId) {
            var sid2 = _streamId;
            setMessages(function(p) {
              return p.map(function(m) {
                return m.id === sid2 ? Object.assign({}, m, { isTyping: false }) : m;
              });
            });
            _streamId = null;
            _streamText = '';
          } else {
            var id = 'n-' + Date.now();
            var s2 = stamp();
            var i = 0;
            setMessages(function(p) { return p.concat([{ id: id, sender: 'nally', text: '', stamp: s2, isTyping: true }]); });
            var iv = setInterval(function() {
              setMessages(function(p) {
                return p.map(function(m) {
                  return m.id === id ? Object.assign({}, m, { text: respText.substring(0, i + 1), isTyping: i < respText.length - 1 }) : m;
                });
              });
              if (i % 3 === 0) beep(1550, 0.004, 'triangle');
              i++;
              if (i >= respText.length) clearInterval(iv);
            }, 15);
          }
        } else if (event.type === 'error') {
          setThinking(false);
          var errId = 'n-' + Date.now();
          var errText = event.response || 'Something went wrong';
          var errStamp = stamp();
          setMessages(function(p) { return p.concat([{ id: errId, sender: 'nally', text: errText, stamp: errStamp, isTyping: false }]); });
        } else if (event.type === 'approval_request') {
          beep(600, 0.08, 'sine');
          setPendingApproval(event);
        } else if (event.type === 'ui_command') {
          var action = event.action;
          var target = event.target;
          if (action === 'open' && target) {
            setWidgetList(function(p) { return p.indexOf(target) !== -1 ? p : p.concat([target]); });
          } else if (action === 'close' && target) {
            setWidgetList(function(p) { return p.filter(function(w) { return w !== target; }); });
          } else if (action === 'minimize' && target) {
            setWmin(function(p) { return Object.assign({}, p, { [target]: true }); });
          } else if (action === 'restore' && target) {
            setWmin(function(p) { var n = Object.assign({}, p); delete n[target]; return n; });
          }
          beep(400, 0.03, 'sine');
        }
      },
      onDone: function() {
        if (_streamId) {
          var sid3 = _streamId;
          setMessages(function(p) {
            return p.map(function(m) {
              return m.id === sid3 ? Object.assign({}, m, { isTyping: false }) : m;
            });
          });
          _streamId = null;
          _streamText = '';
        }
        setThinking(false);
      },
      onError: function(e) {
        setThinking(false);
        var errId2 = 'n-' + Date.now();
        setMessages(function(p) { return p.concat([{ id: errId2, sender: 'nally', text: 'Network error: ' + e.message, stamp: stamp(), isTyping: false }]); });
      }
    });
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

  function handleActivate() {
    if (!active) {
      setActive(true);
      beep(680, 0.2, 'triangle');
      setTimeout(function() { beep(880, 0.1, 'sine'); }, 100);
    }
  }

  function handleWidgetMove(name, pos) {
    setWpos(function(p) { var n = Object.assign({}, p); n[name] = pos; return n; });
  }

  function handleWidgetToggleCollapse(name) {
    setWcol(function(p) { var n = Object.assign({}, p); n[name] = !n[name]; return n; });
  }

  function handleWidgetClose(name) {
    setWidgetList(function(p) { return p.filter(function(w) { return w !== name; }); });
  }

  function handleWidgetMinimize(name) {
    setWmin(function(p) { var n = Object.assign({}, p); n[name] = true; return n; });
    beep(400, 0.03, 'sine');
  }

  function handleWidgetRestore(name) {
    setWmin(function(p) { var n = Object.assign({}, p); n[name] = false; return n; });
    beep(800, 0.03, 'sine');
  }

  function handleRestoreAll() {
    setWmin({});
    beep(600, 0.05, 'sine');
  }

  var ww = typeof window !== 'undefined' ? window.innerWidth : 1200;
  var wh = typeof window !== 'undefined' ? window.innerHeight : 800;
  var defaultPos = {
    clock: { x: 60, y: 60 },
    email: { x: 60, y: 280 },
    telegram: { x: Math.max(60, ww - 290), y: 60 },
    whatsapp: { x: Math.max(60, ww - 290), y: 280 },
    weather: { x: 60, y: 500 },
    music: { x: 60, y: 720 },
    notes: { x: 60, y: 940 },
    status: { x: Math.max(60, ww - 290), y: 500 },
    tasks: { x: Math.max(60, ww - 290), y: 720 },
    chat: { x: Math.max(60, Math.round(ww / 2 - 210)), y: Math.max(60, Math.round(wh / 2 - 275)) },
  };

  return html`
    <div style=${{ height: '100vh', display: 'flex', flexDirection: 'column', background: '#070B14', position: 'relative', overflow: 'hidden' }}>
      <div style=${{ position: 'absolute', top: '20%', left: '30%', width: '400px', height: '400px', background: 'radial-gradient(circle,rgba(0,212,255,0.06) 0%,transparent 70%)', pointerEvents: 'none', filter: 'blur(60px)' }} />
      <div style=${{ position: 'absolute', bottom: '10%', right: '20%', width: '500px', height: '500px', background: 'radial-gradient(circle,rgba(0,212,255,0.03) 0%,transparent 70%)', pointerEvents: 'none', filter: 'blur(80px)' }} />
      <${MatrixRain} />

      ${!connected && html`
        <div style=${{ position: 'fixed', top: '16px', left: '50%', transform: 'translateX(-50%)', zIndex: 100, padding: '8px 16px', borderRadius: '999px', background: 'rgba(127,29,29,0.5)', border: '1px solid rgba(239,68,68,0.3)', color: '#FCA5A5', fontSize: '11px', fontFamily: 'monospace' }}>Backend offline</div>
      `}

      <main style=${{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', position: 'relative', zIndex: 10 }}>

        ${widgetsOn && html`
          <div style=${{ position: 'absolute', inset: 0, pointerEvents: 'none' }}>
            <div style=${{ pointerEvents: 'auto' }}>
              ${widgetList.includes('clock') && !wmin.clock && html`<${ClockWidget} x=${(wpos.clock || defaultPos.clock).x} y=${(wpos.clock || defaultPos.clock).y} z=${20} collapsed=${!!wcol.clock} onMove=${function(p) { handleWidgetMove('clock', p); }} onMinimize=${function() { handleWidgetMinimize('clock'); }} onClose=${function() { handleWidgetClose('clock'); }} />`}
              ${widgetList.includes('email') && !wmin.email && html`<${EmailWidget} x=${(wpos.email || defaultPos.email).x} y=${(wpos.email || defaultPos.email).y} z=${20} collapsed=${!!wcol.email} onMove=${function(p) { handleWidgetMove('email', p); }} onMinimize=${function() { handleWidgetMinimize('email'); }} onClose=${function() { handleWidgetClose('email'); }} />`}
              ${widgetList.includes('telegram') && !wmin.telegram && html`<${TelegramWidget} x=${(wpos.telegram || defaultPos.telegram).x} y=${(wpos.telegram || defaultPos.telegram).y} z=${20} collapsed=${!!wcol.telegram} onMove=${function(p) { handleWidgetMove('telegram', p); }} onMinimize=${function() { handleWidgetMinimize('telegram'); }} onClose=${function() { handleWidgetClose('telegram'); }} />`}
              ${widgetList.includes('whatsapp') && !wmin.whatsapp && html`<${WhatsAppWidget} x=${(wpos.whatsapp || defaultPos.whatsapp).x} y=${(wpos.whatsapp || defaultPos.whatsapp).y} z=${20} collapsed=${!!wcol.whatsapp} onMove=${function(p) { handleWidgetMove('whatsapp', p); }} onMinimize=${function() { handleWidgetMinimize('whatsapp'); }} onClose=${function() { handleWidgetClose('whatsapp'); }} />`}
              ${widgetList.includes('weather') && !wmin.weather && html`<${WeatherWidget} x=${(wpos.weather || defaultPos.weather).x} y=${(wpos.weather || defaultPos.weather).y} z=${20} collapsed=${!!wcol.weather} onMove=${function(p) { handleWidgetMove('weather', p); }} onMinimize=${function() { handleWidgetMinimize('weather'); }} onClose=${function() { handleWidgetClose('weather'); }} />`}
              ${widgetList.includes('music') && !wmin.music && html`<${MusicWidget} x=${(wpos.music || defaultPos.music).x} y=${(wpos.music || defaultPos.music).y} z=${20} collapsed=${!!wcol.music} onMove=${function(p) { handleWidgetMove('music', p); }} onMinimize=${function() { handleWidgetMinimize('music'); }} onClose=${function() { handleWidgetClose('music'); }} />`}
              ${widgetList.includes('notes') && !wmin.notes && html`<${NotesWidget} x=${(wpos.notes || defaultPos.notes).x} y=${(wpos.notes || defaultPos.notes).y} z=${20} collapsed=${!!wcol.notes} onMove=${function(p) { handleWidgetMove('notes', p); }} onMinimize=${function() { handleWidgetMinimize('notes'); }} onClose=${function() { handleWidgetClose('notes'); }} />`}
              ${widgetList.includes('status') && !wmin.status && html`<${StatusWidget} connected=${connected} msgCount=${messages.length} x=${(wpos.status || { x: window.innerWidth - 342, y: 60 }).x} y=${(wpos.status || { x: window.innerWidth - 342, y: 60 }).y} z=${20} collapsed=${!!wcol.status} onMove=${function(p) { handleWidgetMove('status', p); }} onMinimize=${function() { handleWidgetMinimize('status'); }} onClose=${function() { handleWidgetClose('status'); }} />`}
              ${widgetList.includes('tasks') && !wmin.tasks && html`<${TaskWidget} x=${(wpos.tasks || { x: window.innerWidth - 342, y: 280 }).x} y=${(wpos.tasks || { x: window.innerWidth - 342, y: 280 }).y} z=${20} collapsed=${!!wcol.tasks} onMove=${function(p) { handleWidgetMove('tasks', p); }} onMinimize=${function() { handleWidgetMinimize('tasks'); }} onClose=${function() { handleWidgetClose('tasks'); }} />`}
              ${widgetList.includes('chat') && !wmin.chat && html`<${ChatWidget} x=${(wpos.chat || defaultPos.chat).x} y=${(wpos.chat || defaultPos.chat).y} z=${30} messages=${messages} thinking=${thinking} connected=${connected} activeTool=${activeTool} onSend=${handleSend} onRetry=${handleRetry} onClear=${function() { setMessages([]); lssave('messages', []); }} onMove=${function(p) { handleWidgetMove('chat', p); }} onResize=${function(s) {}} onMinimize=${function() { handleWidgetMinimize('chat'); }} onClose=${function() { handleWidgetClose('chat'); }} />`}
              ${Object.keys(dynamicPanels).map(function(id) {
                var p = dynamicPanels[id];
                var wId = 'dynamic_' + id;
                return html`<${DynamicPanel} key=${id} title=${p.title} content=${p.content} x=${p.x || 100} y=${p.y || 100} w=${p.w || 400} h=${p.h || 350} z=${20} onMove=${function(pos) { setDynamicPanels(function(prev) { var n = Object.assign({}, prev); if (n[id]) { n[id] = Object.assign({}, n[id], { x: pos.x, y: pos.y }); } return n; }); }} onResize=${function(sz) { setDynamicPanels(function(prev) { var n = Object.assign({}, prev); if (n[id]) { n[id] = Object.assign({}, n[id], { w: sz.w, h: sz.h }); } return n; }); }} onMinimize=${function() { handleWidgetMinimize(wId); }} onClose=${function() { setDynamicPanels(function(prev) { var n = Object.assign({}, prev); delete n[id]; return n; }); handleWidgetClose(wId); }} />`;
              })}
            </div>
          </div>
        `}

        <div style=${{ display: 'flex', flexDirection: 'column', alignItems: 'center', transition: 'transform 0.5s ease-out' }}>
          <${Orb} active=${active} thinking=${thinking} onClick=${handleActivate} />
          ${!active && html`<p style=${{ fontSize: '11px', fontFamily: 'monospace', letterSpacing: '4px', textTransform: 'uppercase', color: 'rgba(255,255,255,0.12)', marginTop: '24px', animation: 'pulse 3s ease-in-out infinite' }}>Tap to activate</p>`}
          ${active && html`
            <p style=${{ fontSize: '11px', fontFamily: 'monospace', letterSpacing: '3px', textTransform: 'uppercase', color: 'rgba(255,255,255,0.15)', marginTop: '16px' }}>
              ${thinking ? 'Processing' : connected ? 'Ready' : 'Offline'}
            </p>
            <div style=${{ display: 'flex', gap: '10px', marginTop: '16px' }}>
              <button onClick=${function() { setWidgetsOn(!widgetsOn); beep(500, 0.05, 'sine'); }} style=${{
                width: '48px', height: '48px', borderRadius: '50%', border: '1px solid rgba(255,255,255,0.08)',
                background: widgetsOn ? 'rgba(0,212,255,0.08)' : 'rgba(255,255,255,0.03)',
                color: widgetsOn ? 'rgba(0,212,255,0.6)' : 'rgba(255,255,255,0.4)',
                cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', transition: 'all 0.2s',
              }}><${Li} name="LayoutDashboard" size=${20} color=${widgetsOn ? 'rgba(0,212,255,0.6)' : 'rgba(255,255,255,0.4)'} /></button>
              <button onClick=${function() {
                var hasChat = widgetList.indexOf('chat') !== -1;
                if (!hasChat) {
                  setWidgetList(function(p) { return p.concat(['chat']); });
                } else if (wmin.chat) {
                  handleWidgetRestore('chat');
                } else {
                  handleWidgetMinimize('chat');
                }
                beep(500, 0.05, 'sine');
              }} style=${{
                width: '48px', height: '48px', borderRadius: '50%', border: '1px solid rgba(255,255,255,0.08)',
                background: 'rgba(255,255,255,0.03)', color: 'rgba(255,255,255,0.4)',
                cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', transition: 'all 0.2s',
              }}><${Li} name="MessageCircle" size=${20} color="rgba(255,255,255,0.4)" /></button>
            </div>
          `}
        </div>
      </main>

      <${Dock}
        minimized=${Object.keys(wmin).filter(function(k) { return wmin[k] && widgetList.indexOf(k) !== -1; })}
        onRestore=${handleWidgetRestore}
        onToggleWidgets=${function() { setWidgetsOn(!widgetsOn); beep(500, 0.05, 'sine'); }}
        widgetsOn=${widgetsOn}
        onOpenChat=${function() {
          var hasChat = widgetList.indexOf('chat') !== -1;
          if (!hasChat) {
            setWidgetList(function(p) { return p.concat(['chat']); });
          } else if (wmin.chat) {
            handleWidgetRestore('chat');
          } else {
            handleWidgetMinimize('chat');
          }
          beep(500, 0.05, 'sine');
        }}
      />

      ${pendingApproval && html`
        <div style=${{ position: 'fixed', inset: 0, zIndex: 9999, background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(8px)', display: 'flex', alignItems: 'center', justifyContent: 'center', animation: 'fadeIn 0.2s ease-out' }}>
          <div style=${{ background: 'rgba(13,17,23,0.95)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '16px', padding: '28px', maxWidth: '420px', width: '90%', boxShadow: '0 20px 60px rgba(0,0,0,0.5)' }}>
            <div style=${{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '16px' }}>
              <div style=${{ width: '36px', height: '36px', borderRadius: '10px', background: pendingApproval.permission === 'destructive' ? 'rgba(239,68,68,0.15)' : 'rgba(251,191,36,0.15)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <${Li} name="Shield" size=${18} color=${pendingApproval.permission === 'destructive' ? '#EF4444' : '#FBBF24'} />
              </div>
              <div>
                <div style=${{ fontSize: '15px', fontWeight: 600, color: '#E2E8F0' }}>Confirm Action</div>
                <div style=${{ fontSize: '11px', color: 'rgba(255,255,255,0.4)', fontFamily: 'monospace' }}>${pendingApproval.permission} permission</div>
              </div>
            </div>
            <div style=${{ background: 'rgba(0,0,0,0.3)', borderRadius: '10px', padding: '12px 14px', marginBottom: '20px', border: '1px solid rgba(255,255,255,0.04)' }}>
              <div style=${{ fontSize: '12px', color: 'rgba(0,212,255,0.7)', fontFamily: 'monospace', marginBottom: '6px' }}>${pendingApproval.name}</div>
              <div style=${{ fontSize: '11px', color: 'rgba(255,255,255,0.35)', fontFamily: 'monospace', wordBreak: 'break-all', maxHeight: '80px', overflow: 'auto' }}>${JSON.stringify(pendingApproval.args, null, 2)}</div>
            </div>
            <div style=${{ display: 'flex', gap: '10px' }}>
              <button onClick=${function() {
                fetch(BACKEND + '/api/approval', {
                  method: 'POST',
                  headers: _authHeaders(),
                  body: JSON.stringify({ tool_call_id: pendingApproval.tool_call_id, approved: false })
                }).then(function(r) { if (r.status === 401) _handle401(); });
                setPendingApproval(null);
                beep(300, 0.05, 'sine');
              }} style=${{ flex: 1, padding: '10px', borderRadius: '10px', border: '1px solid rgba(255,255,255,0.08)', background: 'rgba(255,255,255,0.04)', color: 'rgba(255,255,255,0.5)', cursor: 'pointer', fontSize: '13px', fontWeight: 500, transition: 'all 0.15s' }}>Deny</button>
              <button onClick=${function() {
                fetch(BACKEND + '/api/approval', {
                  method: 'POST',
                  headers: _authHeaders(),
                  body: JSON.stringify({ tool_call_id: pendingApproval.tool_call_id, approved: true })
                }).then(function(r) { if (r.status === 401) _handle401(); });
                setPendingApproval(null);
                beep(800, 0.05, 'sine');
              }} style=${{ flex: 1, padding: '10px', borderRadius: '10px', border: 'none', background: 'linear-gradient(135deg, #00D4FF, #0090FF)', color: '#000', cursor: 'pointer', fontSize: '13px', fontWeight: 600, transition: 'all 0.15s' }}>Allow</button>
            </div>
          </div>
        </div>
      `}
    </div>
  `;
}

// ─── Error Boundary (class component required by React) ───
class ErrorBoundary extends React.Component {
  constructor(props) { super(props); this.state = { error: null }; }
  componentDidCatch(err) {
    console.error('[NALLY] React render error:', err);
    this.setState({ error: err });
  }
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
