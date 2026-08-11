window.NALLY = window.NALLY || {};

NALLY.dom = {
  root: document.getElementById('root'),
  statusEl: document.getElementById('status-text'),
  thoughtWrap: document.getElementById('thought-wrap'),
  thoughtContent: document.getElementById('thought-content'),
  chatDrawer: document.getElementById('chat-drawer'),
  chatMessages: document.getElementById('chat-messages'),
  chatInput: document.getElementById('chat-input'),
  titlebar: document.getElementById('drawer-titlebar'),
  loginOverlay: document.getElementById('login-overlay'),
  loginErr: document.getElementById('login-err'),
  settingsDropdown: document.getElementById('settings-dropdown'),
  settingsOverlay: document.getElementById('settings-overlay'),
  diffPanel: document.getElementById('diff-panel'),
  diffBody: document.getElementById('diff-body'),
  diffFile: document.getElementById('diff-file'),
  diffStats: document.getElementById('diff-stats'),
  authOverlay: document.getElementById('auth-modal-overlay'),
  authIcon: document.getElementById('auth-modal-icon'),
  authTitle: document.getElementById('auth-modal-title'),
  authSub: document.getElementById('auth-modal-sub'),
  authSpinner: document.getElementById('auth-modal-spinner'),
  authSuccess: document.getElementById('auth-modal-success'),
  authBody: document.getElementById('auth-modal-body'),
  svcGrid: document.getElementById('svc-grid'),
  compactToggle: document.getElementById('compact-toggle'),
  lockToggle: document.getElementById('lock-toggle'),
  cmdPalette: document.getElementById('command-palette'),
  cmdInput: document.getElementById('cmd-input'),
  cmdResults: document.getElementById('cmd-results'),
  backendStatus: document.getElementById('settings-backend-status'),
  uptimeEl: document.getElementById('settings-uptime')
};

NALLY.dom.scrollToBottom = function() {
  var el = NALLY.dom.chatMessages;
  if (el) el.scrollTop = el.scrollHeight;
};

NALLY.dom.clearThinking = function() {
  NALLY.dom.thoughtContent.textContent = '';
  NALLY.dom.thoughtWrap.classList.remove('visible');
};
