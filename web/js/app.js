window.NALLY = window.NALLY || {};

(function() {
  // ─── Boot Sequence ─────────────────────────────
  NALLY.initMarked();

  // Create orb
  NALLY.orb = NALLY.createOrb({ size: 312, state: 'idle', activated: true });
  document.getElementById('orb-mount').appendChild(NALLY.orb.el);

  // Init all modules
  NALLY.initDrawer();
  NALLY.initSettings();
  NALLY.initAuthModal();
  NALLY.initCommandPalette();
  NALLY.initHotkeys();
  NALLY.initSync();

  // ─── Wire up inline elements (no more onclick) ──

  // Login button
  var loginBtn = document.querySelector('#login-overlay button');
  if (loginBtn) loginBtn.addEventListener('click', function() { NALLY.doLogin(); });

  // Thought toggle
  var thoughtToggle = document.getElementById('thought-toggle');
  if (thoughtToggle) thoughtToggle.addEventListener('click', function() { NALLY.toggleThought(); });

  // Drawer titlebar buttons
  var mobileBack = document.getElementById('mobile-back');
  if (mobileBack) mobileBack.addEventListener('click', function() { NALLY.closeDrawer(); });

  var dotClose = document.querySelector('.dot-close');
  if (dotClose) dotClose.addEventListener('click', function() { NALLY.closeDrawer(); });

  var dotMin = document.querySelector('.dot-min');
  if (dotMin) dotMin.addEventListener('click', function() { NALLY.minimizeDrawer(); });

  var dotMax = document.querySelector('.dot-max');
  if (dotMax) dotMax.addEventListener('click', function() { NALLY.maximizeDrawer(); });

  var clearBtn = document.querySelector('.titlebar-clear');
  if (clearBtn) clearBtn.addEventListener('click', function() { NALLY.clearChat(); });

  var micBtn = document.getElementById('mic-btn');
  if (micBtn) micBtn.addEventListener('click', function() { NALLY.toggleRecording(); });

  var sendBtn = document.querySelector('.drawer-send');
  if (sendBtn) sendBtn.addEventListener('click', function() { NALLY.sendChat(); });

  // Diff panel buttons
  var diffClose = document.querySelector('.diff-close');
  if (diffClose) diffClose.addEventListener('click', function() { NALLY.closeDiff(); });

  var diffMinimize = document.querySelector('.diff-minimize');
  if (diffMinimize) diffMinimize.addEventListener('click', function() { NALLY.minimizeDiff(); });

  // Settings section toggles
  document.querySelectorAll('.settings-head').forEach(function(head) {
    head.addEventListener('click', function() { NALLY.toggleSection(this); });
  });

  // Theme swatches
  document.querySelectorAll('.theme-swatch').forEach(function(swatch) {
    swatch.addEventListener('click', function() { NALLY.setTheme(this.dataset.theme); });
  });

  // Compact toggle
  var compactToggle = document.getElementById('compact-toggle');
  if (compactToggle) compactToggle.addEventListener('change', function() { NALLY.setCompact(this.checked); });

  // Lock toggle
  var lockToggle = document.getElementById('lock-toggle');
  if (lockToggle) lockToggle.addEventListener('change', function() { NALLY.setLockMode(this.checked); });

  // Emergency stop
  var emergencyBtn = document.querySelector('.settings-emergency-btn');
  if (emergencyBtn) emergencyBtn.addEventListener('click', function() { NALLY.emergencyStop(); });

  // Settings icon buttons
  var mobileSettings = document.querySelector('.mobile-settings');
  if (mobileSettings) mobileSettings.addEventListener('click', function(e) { NALLY.toggleSettings(e); });

  var desktopSettings = document.querySelector('.desktop-settings');
  if (desktopSettings) desktopSettings.addEventListener('click', function(e) { NALLY.toggleSettings(e); });

  // ─── Auth Gate ─────────────────────────────────
  NALLY.initAuth();

  // ─── Init Lucide Icons ────────────────────────
  lucide.createIcons();
})();
