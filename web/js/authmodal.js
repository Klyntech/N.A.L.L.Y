window.NALLY = window.NALLY || {};

NALLY.showAuthModal = function(svc, type) {
  var d = NALLY.dom;
  var color = NALLY.SVC_COLORS[svc.id] || '#888';
  var isLight = svc.lightIcon;
  var bg = isLight ? 'rgba(255,255,255,0.9)' : color;
  var fg = isLight ? '#000' : '#fff';
  var svg = NALLY.SVC_ICONS[svc.id] || '';
  var styledSvg = svg.replace('<svg', '<svg style="width:20px;height:20px;color:' + fg + '"');
  d.authIcon.style.background = bg;
  d.authIcon.innerHTML = styledSvg;
  d.authTitle.textContent = 'Connect ' + svc.name;
  d.authSpinner.style.display = '';
  d.authSuccess.classList.remove('show');
  d.authBody.innerHTML = '';

  if (type === 'oauth') {
    d.authSub.textContent = 'Redirecting to ' + svc.name + '...';
    d.authOverlay.classList.add('open');
    fetch(NALLY.API + '/api/mcp/connect/' + NALLY.backendId(svc.id), {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + NALLY.state.token, 'Content-Type': 'application/json' }
    })
    .then(function(r) { return r.json().then(function(j) { return { ok: r.ok, data: j }; }); })
    .then(function(res) {
      if (!res.ok) {
        d.authSpinner.style.display = 'none';
        d.authSub.textContent = res.data.detail || res.data.error || 'Backend error';
        d.authBody.innerHTML = '<button class="auth-modal-btn secondary" onclick="NALLY.closeAuthModal()">Close</button>';
        return;
      }
      var data = res.data;
      if (data.status === 'connected') {
        d.authSpinner.style.display = 'none';
        d.authSuccess.classList.add('show');
        d.authSub.textContent = svc.name + ' already connected';
        d.authBody.innerHTML = '<button class="auth-modal-btn" onclick="NALLY.closeAuth(\'' + svc.id + '\')">Done</button>';
        return;
      }
      if (data.auth_url) {
        d.authSub.textContent = 'Opening ' + svc.name + '...';
        var w = 600, h = 700;
        var left = (screen.width - w) / 2, top = (screen.height - h) / 2;
        var popup = window.open(data.auth_url, 'oauth_' + svc.id, 'width=' + w + ',height=' + h + ',left=' + left + ',top=' + top);
        if (!popup) {
          d.authSpinner.style.display = 'none';
          d.authSub.textContent = 'Popup blocked — allow popups for this site';
          d.authBody.innerHTML = '<button class="auth-modal-btn" onclick="window.open(\'' + data.auth_url + '\')">Open in new tab</button><button class="auth-modal-btn secondary" onclick="NALLY.closeAuthModal()">Close</button>';
          return;
        }
        NALLY.pollConnection(svc.id);
      } else {
        d.authSpinner.style.display = 'none';
        var errMsg = data.detail || data.error || 'Failed to start OAuth flow';
        d.authSub.textContent = errMsg;
        d.authBody.innerHTML = '<button class="auth-modal-btn secondary" onclick="NALLY.closeAuthModal()">Close</button>';
      }
    })
    .catch(function() {
      d.authSpinner.style.display = 'none';
      d.authSub.textContent = 'Backend unreachable';
      d.authBody.innerHTML = '<button class="auth-modal-btn secondary" onclick="NALLY.closeAuthModal()">Close</button>';
    });
  } else {
    d.authSub.textContent = 'Paste your ' + (svc.tokenLabel || 'token') + ' below';
    d.authSpinner.style.display = 'none';
    d.authBody.innerHTML = '<input class="auth-token-input" id="auth-token-val" placeholder="' + (svc.tokenLabel || 'Token') + '" type="password" autofocus onkeydown="if(event.key===\'Enter\')NALLY.submitToken(\'' + svc.id + '\')">'
      + '<button class="auth-modal-btn" onclick="NALLY.submitToken(\'' + svc.id + '\')">Connect</button>'
      + '<button class="auth-modal-btn secondary" onclick="NALLY.closeAuthModal()">Cancel</button>';
    d.authOverlay.classList.add('open');
    setTimeout(function(){ var el=document.getElementById('auth-token-val'); if(el) el.focus(); }, 100);
  }
};

NALLY.submitToken = function(id) {
  var val = document.getElementById('auth-token-val');
  if (!val || !val.value.trim()) return;
  var token = val.value.trim();
  NALLY.dom.authSpinner.style.display = '';
  NALLY.dom.authBody.innerHTML = '';
  NALLY.dom.authSub.textContent = 'Verifying...';

  fetch(NALLY.API + '/api/mcp/token/' + NALLY.backendId(id), {
    method: 'POST',
    headers: { 'Authorization': 'Bearer ' + NALLY.state.token, 'Content-Type': 'application/json' },
    body: JSON.stringify({ token: token })
  })
  .then(function(r) { return r.json(); })
  .then(function() {
    NALLY.dom.authSpinner.style.display = 'none';
    NALLY.dom.authSuccess.classList.add('show');
    var svc = NALLY.findSvc(id);
    NALLY.dom.authSub.textContent = svc.name + ' connected successfully';
    NALLY.dom.authBody.innerHTML = '<button class="auth-modal-btn" onclick="NALLY.closeAuth(\'' + id + '\')">Done</button>';
  })
  .catch(function() {
    NALLY.dom.authSpinner.style.display = 'none';
    NALLY.dom.authSuccess.classList.add('show');
    var svc = NALLY.findSvc(id);
    NALLY.dom.authSub.textContent = svc.name + ' connected (local)';
    NALLY.dom.authBody.innerHTML = '<button class="auth-modal-btn" onclick="NALLY.closeAuth(\'' + id + '\')">Done</button>';
  });
};

NALLY.pollConnection = function(id) {
  var s = NALLY.state;
  if (s.pollInterval) clearInterval(s.pollInterval);
  var checks = 0;
  s.pollInterval = setInterval(function() {
    checks++;
    fetch(NALLY.API + '/api/mcp/services', {
      headers: { 'Authorization': 'Bearer ' + s.token }
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      var svc = data.services ? data.services.find(function(svc){ return svc.name === id || svc.id === id; }) : null;
      if (svc && svc.connected) {
        clearInterval(s.pollInterval); s.pollInterval = null;
        NALLY.dom.authSpinner.style.display = 'none';
        NALLY.dom.authSuccess.classList.add('show');
        NALLY.dom.authSub.textContent = NALLY.findSvc(id).name + ' connected successfully';
        NALLY.dom.authBody.innerHTML = '<button class="auth-modal-btn" onclick="NALLY.closeAuth(\'' + id + '\')">Done</button>';
      }
    })
    .catch(function(){});
    if (checks > 30) {
      clearInterval(s.pollInterval); s.pollInterval = null;
      NALLY.dom.authSpinner.style.display = 'none';
      NALLY.dom.authSub.textContent = 'Timed out — try again';
      NALLY.dom.authBody.innerHTML = '<button class="auth-modal-btn secondary" onclick="NALLY.closeAuthModal()">Close</button>';
    }
  }, 1000);
};

NALLY.closeAuth = function(id) {
  var connected = NALLY.getConnected();
  connected[id] = { at: Date.now() };
  NALLY.saveConnected(connected);
  NALLY.renderServices();
  NALLY.closeAuthModal();
};

NALLY.closeAuthModal = function() {
  if (NALLY.state.pollInterval) { clearInterval(NALLY.state.pollInterval); NALLY.state.pollInterval = null; }
  NALLY.dom.authOverlay.classList.remove('open');
  NALLY.dom.authBody.innerHTML = '';
};

NALLY.initAuthModal = function() {
  NALLY.dom.authOverlay.addEventListener('click', function(e) {
    if (e.target === NALLY.dom.authOverlay) NALLY.closeAuthModal();
  });

  var params = new URLSearchParams(window.location.search);
  if (params.get('oauth') === 'success') {
    var svcId = (params.get('service') || '').toLowerCase();
    if (svcId) {
      var connected = NALLY.getConnected();
      connected[svcId] = { at: Date.now() };
      NALLY.saveConnected(connected);
      NALLY.renderServices();
    }
    window.history.replaceState({}, '', window.location.pathname);
  }
};
