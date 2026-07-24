// ─── React / HTM Setup ──────────────────────────────
var _a = React, useState = _a.useState, useEffect = _a.useEffect, useRef = _a.useRef, useCallback = _a.useCallback, useMemo = _a.useMemo;
var html = htm.bind(React.createElement);

// ─── Constants ──────────────────────────────────────
var BACKEND = window.location.origin;

// ─── Auth ───────────────────────────────────────────
var _accessToken = '';

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

function _authHeaders() {
  var h = { 'Content-Type': 'application/json' };
  if (_accessToken) h['Authorization'] = 'Bearer ' + _accessToken;
  return h;
}

function _showLoginPrompt(onDone) {
  var overlay = document.createElement('div');
  overlay.id = 'nally-login-overlay';
  overlay.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.85);z-index:99999;display:flex;align-items:center;justify-content:center;';
  var box = document.createElement('div');
  box.style.cssText = 'background:#111;border:1px solid rgba(255,255,255,0.1);border-radius:12px;padding:32px;width:340px;text-align:center;position:relative;';
  var closeBtn = document.createElement('button');
  closeBtn.textContent = '×';
  closeBtn.style.cssText = 'position:absolute;top:8px;right:12px;background:none;border:none;color:rgba(255,255,255,0.3);font-size:20px;cursor:pointer;padding:4px 8px;';
  closeBtn.addEventListener('click', function() { overlay.remove(); if (onDone) onDone(); });
  var h = document.createElement('div');
  h.textContent = 'Enter Access Token';
  h.style.cssText = 'color:rgba(255,255,255,0.8);font-size:15px;font-weight:600;margin-bottom:20px;font-family:system-ui;';
  var inp = document.createElement('input');
  inp.type = 'password';
  inp.placeholder = 'NALLY_ACCESS_TOKEN';
  inp.style.cssText = 'width:100%;padding:10px 12px;border-radius:8px;border:1px solid rgba(255,255,255,0.1);background:rgba(255,255,255,0.05);color:#fff;font-size:14px;font-family:monospace;outline:none;box-sizing:border-box;';
  var btn = document.createElement('button');
  btn.textContent = 'Connect';
  btn.style.cssText = 'width:100%;padding:10px;border-radius:8px;border:none;background:rgba(62,207,184,0.12);color:rgba(62,207,184,0.9);font-size:14px;font-weight:600;margin-top:12px;cursor:pointer;font-family:system-ui;';
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
  box.appendChild(closeBtn); box.appendChild(h); box.appendChild(inp); box.appendChild(btn);
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

// ─── SSE Connection ─────────────────────────────────
var _sseAbort = null;
var _eventHandlers = {};

function _emit(event, data) {
  var handlers = _eventHandlers[event];
  if (handlers) {
    handlers.forEach(function(fn) { fn(data); });
  }
}

function on(event, fn) {
  if (!_eventHandlers[event]) _eventHandlers[event] = [];
  _eventHandlers[event].push(fn);
}

function off(event, fn) {
  var handlers = _eventHandlers[event];
  if (!handlers) return;
  var idx = handlers.indexOf(fn);
  if (idx !== -1) handlers.splice(idx, 1);
}

// ─── Send Message via SSE ───────────────────────────
var _sendMsgCallbacks = [];

function sendMsg(msg) {
  if (_sseAbort) { _sseAbort.abort(); _sseAbort = null; }
  var ctrl = new AbortController();
  _sseAbort = ctrl;

  _emit('status', { status: 'thinking' });

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
        if (result.done) {
          _emit('stream_done', {});
          _emit('status', { status: 'idle' });
          return;
        }
        buffer += decoder.decode(result.value, { stream: true });
        var lines = buffer.split('\n');
        buffer = lines.pop();
        for (var i = 0; i < lines.length; i++) {
          var line = lines[i].trim();
          if (!line.startsWith('data: ')) continue;
          var data = line.slice(6);
          if (data === '[DONE]') {
            _emit('stream_done', {});
            _emit('status', { status: 'idle' });
            return;
          }
          try {
            var event = JSON.parse(data);
            var name = event.event || event.type || 'message';
            var payload = event.data || event;
            _emit(name, payload);
          } catch(e) {}
        }
        return readChunk();
      });
    }
    return readChunk();
  }).catch(function(e) {
    if (e.name === 'AbortError') return;
    console.error('[NALLY] SSE error:', e);
    _emit('status', { status: 'idle' });
    _emit('response', { text: 'Network error: ' + e.message });
  });
}

// ─── HTTP helpers ───────────────────────────────────
function httpPost(path, body) {
  return fetch(BACKEND + path, {
    method: 'POST',
    headers: _authHeaders(),
    body: JSON.stringify(body)
  }).then(function(r) {
    if (r.status === 401) { _handle401(); throw new Error('Unauthorized'); }
    return r.json();
  });
}

// ─── Audio ──────────────────────────────────────────
var _sharedAudioCtx = null;
function _getAudioCtx() {
  if (!_sharedAudioCtx || _sharedAudioCtx.state === 'closed') {
    try { _sharedAudioCtx = new (window.AudioContext || window.webkitAudioContext)(); } catch(e) {}
  }
  return _sharedAudioCtx;
}

function beep(freq, dur, type) {
  try {
    var ctx = _getAudioCtx();
    if (!ctx) return;
    if (ctx.state === 'suspended') ctx.resume();
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

// ─── Haptic ─────────────────────────────────────────
function haptic(ms) {
  try { if (navigator.vibrate) navigator.vibrate(ms || 10); } catch(e) {}
}

// ─── Time ───────────────────────────────────────────
function stamp() {
  return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

// ─── LocalStorage ───────────────────────────────────
function lsload(key, fallback) {
  try { var v = localStorage.getItem('nally-' + key); return v !== null ? JSON.parse(v) : fallback; } catch(e) { return fallback; }
}
function lssave(key, val) {
  try { localStorage.setItem('nally-' + key, JSON.stringify(val)); } catch(e) {}
}

// ─── Lucide Icons ───────────────────────────────────
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

// ─── Markdown ───────────────────────────────────────
function escapeHtml(str) {
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
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

function md(text) {
  if (!text) return '';
  var s = escapeHtml(text);
  s = s.replace(/```(\w*)\n([\s\S]*?)```/g, function(_, lang, code) {
    return '<div class="code-block" style="position:relative;background:rgba(0,0,0,0.5);border:1px solid rgba(124,106,239,0.15);border-radius:12px;padding:12px 12px 12px 14px;overflow-x:auto;margin:8px 0"><button class="copy-btn" onclick="copyCode(this)" title="Copy" style="position:absolute;top:6px;right:6px;width:28px;height:28px;border-radius:6px;border:none;background:rgba(255,255,255,0.08);color:rgba(255,255,255,0.4);cursor:pointer;opacity:0;transition:all 0.2s;display:flex;align-items:center;justify-content:center">' + ico('Copy', 12, 'rgba(255,255,255,0.4)') + '</button>' + (lang ? '<div style="font-size:10px;color:rgba(124,106,239,0.55);font-family:monospace;margin-bottom:6px">' + lang + '</div>' : '') + '<code style="color:#A78BFA;font-size:12px;font-family:monospace;white-space:pre">' + code + '</code></div>';
  });
  s = s.replace(/`([^`]+)`/g, '<code style="background:rgba(0,0,0,0.4);padding:2px 6px;border-radius:4px;color:#A78BFA;font-size:12px;font-family:monospace">$1</code>');
  s = s.replace(/\*\*(.+?)\*\*/g, '<strong style="color:#F1F5F9">$1</strong>');
  s = s.replace(/\*(.+?)\*/g, '<em>$1</em>');
  s = s.replace(/^### (.+)$/gm, '<div style="font-size:15px;font-weight:600;color:#E2E8F0;margin:12px 0 4px">$1</div>');
  s = s.replace(/^## (.+)$/gm, '<div style="font-size:17px;font-weight:700;color:#F1F5F9;margin:14px 0 6px">$1</div>');
  s = s.replace(/^# (.+)$/gm, '<div style="font-size:20px;font-weight:700;color:#fff;margin:16px 0 8px">$1</div>');
  s = s.replace(/^- (.+)$/gm, '<div style="margin-left:16px">&#8226; $1</div>');
  s = s.replace(/^> (.+)$/gm, '<div style="border-left:3px solid rgba(124,106,239,0.25);padding-left:12px;color:rgba(255,255,255,0.5);margin:4px 0">$1</div>');
  s = s.replace(/\n/g, '<br/>');
  return s;
}
