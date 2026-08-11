window.NALLY = window.NALLY || {};

NALLY.positionDropdown = function() {
  var isMob = window.innerWidth < 640;
  NALLY.dom.settingsDropdown.classList.remove('pos-desktop', 'pos-mobile');
  NALLY.dom.settingsDropdown.classList.add(isMob ? 'pos-mobile' : 'pos-desktop');
};

NALLY.toggleSettings = function(e) {
  if (e) e.stopPropagation();
  if (NALLY.state.settingsOpen) { NALLY.closeSettings(); }
  else { NALLY.openSettings(); }
};

NALLY.openSettings = function() {
  NALLY.state.settingsOpen = true;
  NALLY.positionDropdown();
  NALLY.dom.settingsOverlay.classList.add('open');
  NALLY.dom.settingsDropdown.classList.add('open');
  NALLY.loadSettingsUI();
};

NALLY.closeSettings = function() {
  NALLY.state.settingsOpen = false;
  NALLY.dom.settingsDropdown.classList.remove('open');
  NALLY.dom.settingsOverlay.classList.remove('open');
};

NALLY.toggleSection = function(head) {
  var section = head.parentElement;
  section.classList.toggle('open');
};

NALLY.setTheme = function(name) {
  document.body.className = '';
  document.body.classList.add('theme-' + name);
  if (NALLY.dom.compactToggle.checked) document.body.classList.add('compact');
  if (NALLY.dom.lockToggle.checked) document.body.classList.add('lock-mode');
  localStorage.setItem(NALLY.THEME_KEY, name);
  document.querySelectorAll('.theme-swatch').forEach(function(s) {
    s.classList.toggle('active', s.dataset.theme === name);
  });
};

NALLY.setCompact = function(on) {
  document.body.classList.toggle('compact', on);
  localStorage.setItem(NALLY.COMPACT_KEY, on);
};

NALLY.setLockMode = function(on) {
  document.body.classList.toggle('lock-mode', on);
  localStorage.setItem(NALLY.LOCK_KEY, on);
};

NALLY.emergencyStop = function() {
  var s = NALLY.state;
  if (s.chatAbort) { s.chatAbort.abort(); s.chatAbort = null; }
  fetch(NALLY.API + '/api/abort', {
    method: 'POST',
    headers: { 'Authorization': 'Bearer ' + s.token }
  }).catch(function(){});
  NALLY.removeTyping();
  NALLY.dom.clearThinking();
  NALLY.orb.setState('idle');
  NALLY.dom.statusEl.textContent = '';
  NALLY.dom.statusEl.style.color = '';

  NALLY.dom.authIcon.style.background = 'rgba(239,68,68,0.15)';
  NALLY.dom.authIcon.style.color = '#EF4444';
  NALLY.dom.authIcon.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="9" y1="9" x2="15" y2="15"/><line x1="15" y1="9" x2="9" y2="15"/></svg>';
  NALLY.dom.authTitle.textContent = 'Emergency Stop';
  NALLY.dom.authSub.textContent = 'All operations halted';
  NALLY.dom.authSpinner.style.display = 'none';
  NALLY.dom.authSuccess.classList.remove('show');
  NALLY.dom.authBody.innerHTML = '<button class="auth-modal-btn" onclick="NALLY.closeAuthModal()">OK</button>';
  NALLY.dom.authOverlay.classList.add('open');
};

NALLY.loadSettingsUI = function() {
  var savedTheme = localStorage.getItem(NALLY.THEME_KEY) || 'midnight';
  NALLY.setTheme(savedTheme);
  var savedCompact = localStorage.getItem(NALLY.COMPACT_KEY) === 'true';
  NALLY.dom.compactToggle.checked = savedCompact;
  document.body.classList.toggle('compact', savedCompact);

  var savedLock = localStorage.getItem(NALLY.LOCK_KEY) === 'true';
  NALLY.dom.lockToggle.checked = savedLock;
  document.body.classList.toggle('lock-mode', savedLock);

  fetch(NALLY.API + '/api/status', { method: 'GET', signal: AbortSignal.timeout(3000) })
    .then(function(r) { NALLY.dom.backendStatus.textContent = 'Online'; NALLY.dom.backendStatus.style.color = 'var(--green)'; })
    .catch(function() { NALLY.dom.backendStatus.textContent = 'Offline'; NALLY.dom.backendStatus.style.color = '#EF4444'; });

  var elapsed = Math.floor((Date.now() - NALLY.state.startTime) / 1000);
  var m = Math.floor(elapsed / 60);
  var h = Math.floor(m / 60);
  NALLY.dom.uptimeEl.textContent = h > 0 ? h + 'h ' + (m % 60) + 'm' : m + 'm ' + (elapsed % 60) + 's';

  NALLY.renderServices();
};

NALLY.initSettings = function() {
  NALLY.dom.settingsOverlay.addEventListener('click', NALLY.closeSettings);

  setInterval(function() {
    var elapsed = Math.floor((Date.now() - NALLY.state.startTime) / 1000);
    var m = Math.floor(elapsed / 60);
    var h = Math.floor(m / 60);
    var s = elapsed % 60;
    if (NALLY.dom.uptimeEl) {
      NALLY.dom.uptimeEl.textContent = h > 0 ? h + 'h ' + (m % 60) + 'm' : m + 'm ' + s + 's';
    }
  }, 1000);
};
