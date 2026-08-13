window.NALLY = window.NALLY || {};

NALLY.verifyToken = function(token) {
  return fetch(NALLY.API + '/api/me', {
    headers: { 'Authorization': 'Bearer ' + token }
  }).then(function(r) { return r.ok; }).catch(function() { return false; });
};

NALLY.showLogin = function() {
  NALLY.state.token = '';
  localStorage.removeItem(NALLY.STORAGE_KEY);
  if (NALLY.state.evtSource) { NALLY.state.evtSource.close(); NALLY.state.evtSource = null; }
  NALLY.dom.loginOverlay.classList.remove('hidden');
  document.getElementById('login-token-input').value = '';
  document.getElementById('login-token-input').focus();
};

NALLY.doLogin = function() {
  var input = document.getElementById('login-token-input');
  var token = input.value.trim();
  if (!token) return;
  NALLY.dom.loginErr.style.display = 'none';
  NALLY.verifyToken(token).then(function(ok) {
    if (!ok) throw new Error('bad');
    localStorage.setItem(NALLY.STORAGE_KEY, token);
    NALLY.state.token = token;
    NALLY.dom.loginOverlay.classList.add('hidden');
    NALLY.waitForMarked(NALLY.loadHistory);
    setTimeout(NALLY.subscribeEvents, 500);
    NALLY.initWebSocket();
  }).catch(function() {
    NALLY.dom.loginErr.style.display = 'block';
  });
};

NALLY.initAuth = function() {
  document.getElementById('login-token-input').addEventListener('keydown', function(e) {
    if (e.key === 'Enter') NALLY.doLogin();
  });

  if (!NALLY.state.token) {
    NALLY.dom.loginOverlay.classList.remove('hidden');
  } else {
    NALLY.verifyToken(NALLY.state.token).then(function(ok) {
      if (ok) {
        NALLY.dom.loginOverlay.classList.add('hidden');
        NALLY.waitForMarked(NALLY.loadHistory);
        NALLY.initWebSocket();
      } else {
        NALLY.showLogin();
      }
    });
  }
};
