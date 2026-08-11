window.NALLY = window.NALLY || {};

NALLY.initHotkeys = function() {
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
      if (NALLY.dom.chatInput.value.trim()) {
        NALLY.dom.chatInput.value = '';
        NALLY.dom.chatInput.style.height = 'auto';
        return;
      }
      if (NALLY.dom.cmdPalette && NALLY.dom.cmdPalette.classList.contains('open')) {
        NALLY.closeCommandPalette();
        return;
      }
      if (NALLY.dom.authOverlay.classList.contains('open')) { NALLY.closeAuthModal(); return; }
      if (NALLY.dom.diffPanel.classList.contains('open')) { NALLY.closeDiff(); return; }
      if (NALLY.state.settingsOpen) { NALLY.closeSettings(); return; }
      if (NALLY.state.drawerOpen) { NALLY.closeDrawer(); return; }
      return;
    }

    if (e.ctrlKey && e.shiftKey && e.key === 'L') {
      e.preventDefault();
      NALLY.dom.lockToggle.checked = !NALLY.dom.lockToggle.checked;
      NALLY.setLockMode(NALLY.dom.lockToggle.checked);
      return;
    }

    if (e.ctrlKey && e.key === '/') {
      e.preventDefault();
      NALLY.toggleDrawer();
      return;
    }

    if (e.ctrlKey && e.key === 'k') {
      e.preventDefault();
      NALLY.openCommandPalette();
      return;
    }
  });
};
