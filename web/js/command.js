window.NALLY = window.NALLY || {};

NALLY.CMD_COMMANDS = [
  { name: 'Send Message', desc: 'Type in chat input', icon: 'send', action: function(){ NALLY.dom.chatInput.focus(); NALLY.closeCommandPalette(); }, shortcut: 'Enter' },
  { name: 'Clear Chat', desc: 'Clear conversation history', icon: 'trash-2', action: function(){ NALLY.clearChat(); NALLY.closeCommandPalette(); } },
  { name: 'Toggle Drawer', desc: 'Open/close chat panel', icon: 'panel-right', action: function(){ NALLY.toggleDrawer(); NALLY.closeCommandPalette(); }, shortcut: 'Ctrl+/' },
  { name: 'Emergency Stop', desc: 'Abort all operations', icon: 'octagon', action: function(){ NALLY.emergencyStop(); NALLY.closeCommandPalette(); } },
  { name: 'Settings', desc: 'Open settings panel', icon: 'settings', action: function(){ NALLY.openSettings(); NALLY.closeCommandPalette(); } },
  { name: 'Lock Mode', desc: 'Toggle input lock', icon: 'lock', action: function(){ var t = NALLY.dom.lockToggle; t.checked = !t.checked; NALLY.setLockMode(t.checked); NALLY.closeCommandPalette(); }, shortcut: 'Ctrl+Shift+L' },
  { name: 'Theme: Midnight', desc: 'Dark purple theme', icon: 'palette', action: function(){ NALLY.setTheme('midnight'); NALLY.closeCommandPalette(); } },
  { name: 'Theme: Emerald', desc: 'Green theme', icon: 'palette', action: function(){ NALLY.setTheme('emerald'); NALLY.closeCommandPalette(); } },
  { name: 'Theme: Crimson', desc: 'Red theme', icon: 'palette', action: function(){ NALLY.setTheme('crimson'); NALLY.closeCommandPalette(); } },
  { name: 'Theme: Ocean', desc: 'Blue theme', icon: 'palette', action: function(){ NALLY.setTheme('ocean'); NALLY.closeCommandPalette(); } },
];

NALLY.openCommandPalette = function() {
  NALLY.dom.cmdPalette.classList.add('open');
  NALLY.dom.cmdInput.value = '';
  NALLY.dom.cmdInput.focus();
  NALLY.state.cmdActiveIdx = 0;
  NALLY.renderCmdResults('');
};

NALLY.closeCommandPalette = function() {
  NALLY.dom.cmdPalette.classList.remove('open');
};

NALLY.renderCmdResults = function(query) {
  var container = NALLY.dom.cmdResults;
  var q = query.toLowerCase().trim();

  var allItems = NALLY.CMD_COMMANDS.slice();
  NALLY.SERVICES.forEach(function(s) {
    if (s.mcp) {
      var connected = NALLY.getConnected();
      allItems.push({
        name: s.name,
        desc: connected[s.id] ? 'Connected' : 'Connect',
        icon: 'plug',
        action: function() {
          if (connected[s.id]) return;
          NALLY.connectService(s.id);
          NALLY.closeCommandPalette();
        }
      });
    }
  });

  NALLY.state.cmdItems = q
    ? allItems.filter(function(item) {
        return item.name.toLowerCase().indexOf(q) !== -1 || item.desc.toLowerCase().indexOf(q) !== -1;
      })
    : allItems;

  if (NALLY.state.cmdItems.length === 0) {
    container.innerHTML = '<div class="cmd-empty">No results found</div>';
    return;
  }

  NALLY.state.cmdActiveIdx = 0;
  container.innerHTML = NALLY.state.cmdItems.map(function(item, i) {
    return '<div class="cmd-item' + (i === 0 ? ' active' : '') + '" data-idx="' + i + '">'
      + '<div class="cmd-item-icon"><i data-lucide="' + (item.icon || 'zap') + '"></i></div>'
      + '<div class="cmd-item-label"><div class="cmd-item-name">' + item.name + '</div>'
      + '<div class="cmd-item-desc">' + item.desc + '</div></div>'
      + (item.shortcut ? '<span class="cmd-item-shortcut">' + item.shortcut + '</span>' : '')
      + '</div>';
  }).join('');

  lucide.createIcons();

  container.querySelectorAll('.cmd-item').forEach(function(el) {
    el.addEventListener('click', function() {
      var idx = parseInt(el.dataset.idx);
      if (NALLY.state.cmdItems[idx] && NALLY.state.cmdItems[idx].action) NALLY.state.cmdItems[idx].action();
    });
    el.addEventListener('mouseenter', function() {
      container.querySelectorAll('.cmd-item').forEach(function(x) { x.classList.remove('active'); });
      el.classList.add('active');
      NALLY.state.cmdActiveIdx = parseInt(el.dataset.idx);
    });
  });
};

NALLY.updateCmdActive = function() {
  var items = document.querySelectorAll('#cmd-results .cmd-item');
  items.forEach(function(el, i) { el.classList.toggle('active', i === NALLY.state.cmdActiveIdx); });
  if (items[NALLY.state.cmdActiveIdx]) items[NALLY.state.cmdActiveIdx].scrollIntoView({ block: 'nearest' });
};

NALLY.initCommandPalette = function() {
  NALLY.dom.cmdInput.addEventListener('input', function() {
    NALLY.renderCmdResults(this.value);
  });

  NALLY.dom.cmdInput.addEventListener('keydown', function(e) {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      NALLY.state.cmdActiveIdx = Math.min(NALLY.state.cmdActiveIdx + 1, NALLY.state.cmdItems.length - 1);
      NALLY.updateCmdActive();
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      NALLY.state.cmdActiveIdx = Math.max(NALLY.state.cmdActiveIdx - 1, 0);
      NALLY.updateCmdActive();
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (NALLY.state.cmdItems[NALLY.state.cmdActiveIdx] && NALLY.state.cmdItems[NALLY.state.cmdActiveIdx].action) {
        NALLY.state.cmdItems[NALLY.state.cmdActiveIdx].action();
      }
    }
  });

  NALLY.dom.cmdPalette.addEventListener('click', function(e) {
    if (e.target === NALLY.dom.cmdPalette) NALLY.closeCommandPalette();
  });
};
