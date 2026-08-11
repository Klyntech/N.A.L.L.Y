window.NALLY = window.NALLY || {};

NALLY.toggleThought = function() {
  NALLY.state.thoughtCollapsed = !NALLY.state.thoughtCollapsed;
  NALLY.dom.thoughtWrap.classList.toggle('collapsed', NALLY.state.thoughtCollapsed);
};

NALLY.checkMobile = function() { return NALLY.isMobile.matches; };

NALLY.isMobile = window.matchMedia('(max-width: 640px)');

NALLY.toggleDrawer = function() {
  var s = NALLY.state;
  var d = NALLY.dom;
  s.drawerOpen = !s.drawerOpen;
  if (s.drawerOpen) {
    if (NALLY.checkMobile()) {
      d.chatDrawer.style.transition = 'none';
      d.chatDrawer.style.opacity = '0';
      d.chatDrawer.classList.add('open');
      void d.chatDrawer.offsetWidth;
      d.chatDrawer.style.transition = 'opacity 0.25s ease';
      d.chatDrawer.style.opacity = '1';
      setTimeout(function() { d.chatInput.focus(); }, 300);
    } else {
      var orbRect = NALLY.orb.el.getBoundingClientRect();
      var orbCX = orbRect.left + orbRect.width / 2;
      var orbCY = orbRect.top + orbRect.height / 2;
      d.chatDrawer.style.transition = 'none';
      d.chatDrawer.style.left = orbCX + 'px';
      d.chatDrawer.style.top = orbCY + 'px';
      d.chatDrawer.style.transform = 'translate(-50%, -50%) scale(0.15)';
      d.chatDrawer.style.opacity = '0';
      d.chatDrawer.classList.add('open');
      void d.chatDrawer.offsetWidth;
      d.chatDrawer.style.transition = 'left 0.5s cubic-bezier(0.22,1,0.36,1), top 0.5s cubic-bezier(0.22,1,0.36,1), transform 0.5s cubic-bezier(0.22,1,0.36,1), opacity 0.4s ease';
      d.chatDrawer.style.left = '50%';
      d.chatDrawer.style.top = '50%';
      d.chatDrawer.style.transform = 'translate(-50%, -50%) scale(1)';
      d.chatDrawer.style.opacity = '1';
      setTimeout(function() {
        d.chatDrawer.style.transition = 'opacity 0.3s ease, box-shadow 0.3s ease';
        d.chatInput.focus();
      }, 510);
    }
  } else {
    NALLY.closeDrawer();
  }
};

NALLY.closeDrawer = function() {
  var s = NALLY.state;
  var d = NALLY.dom;
  if (NALLY.checkMobile()) {
    d.chatDrawer.style.transition = 'opacity 0.2s ease';
    d.chatDrawer.style.opacity = '0';
    setTimeout(function() {
      d.chatDrawer.classList.remove('open', 'maximized');
      s.isMaximized = false;
      d.chatDrawer.style.transition = 'none';
      d.chatDrawer.style.opacity = '';
    }, 220);
  } else {
    var orbRect = NALLY.orb.el.getBoundingClientRect();
    var orbCX = orbRect.left + orbRect.width / 2;
    var orbCY = orbRect.top + orbRect.height / 2;
    d.chatDrawer.style.transition = 'left 0.4s cubic-bezier(0.22,1,0.36,1), top 0.4s cubic-bezier(0.22,1,0.36,1), transform 0.4s cubic-bezier(0.22,1,0.36,1), opacity 0.3s ease';
    d.chatDrawer.style.left = orbCX + 'px';
    d.chatDrawer.style.top = orbCY + 'px';
    d.chatDrawer.style.transform = 'translate(-50%, -50%) scale(0.15)';
    d.chatDrawer.style.opacity = '0';
    setTimeout(function() {
      d.chatDrawer.classList.remove('open', 'maximized');
      s.isMaximized = false;
      d.chatDrawer.style.transition = 'none';
      d.chatDrawer.style.left = '50%';
      d.chatDrawer.style.top = '50%';
      d.chatDrawer.style.transform = 'translate(-50%, -50%)';
      d.chatDrawer.style.opacity = '';
    }, 410);
  }
  s.drawerOpen = false;
};

NALLY.minimizeDrawer = function() {
  NALLY.closeDrawer();
};

NALLY.maximizeDrawer = function() {
  var s = NALLY.state;
  var d = NALLY.dom;
  if (s.isMaximized) {
    d.chatDrawer.classList.remove('maximized');
    if (s.savedBounds) {
      d.chatDrawer.style.top = s.savedBounds.top;
      d.chatDrawer.style.left = s.savedBounds.left;
      d.chatDrawer.style.width = s.savedBounds.width;
      d.chatDrawer.style.height = s.savedBounds.height;
      d.chatDrawer.style.transform = 'none';
    }
    s.isMaximized = false;
  } else {
    s.savedBounds = {
      top: d.chatDrawer.style.top || '50%',
      left: d.chatDrawer.style.left || '50%',
      width: d.chatDrawer.style.width || '560px',
      height: d.chatDrawer.style.height || '480px',
    };
    d.chatDrawer.classList.add('maximized');
    s.isMaximized = true;
  }
};

NALLY.initDrawer = function() {
  var s = NALLY.state;
  var d = NALLY.dom;

  d.chatInput.addEventListener('input', function() {
    this.style.height = 'auto';
    this.style.height = Math.min(this.scrollHeight, 100) + 'px';
  });

  d.chatInput.addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && !e.shiftKey && !e.ctrlKey) {
      e.preventDefault();
      NALLY.sendChat();
      return;
    }
    if (e.key === 'Enter' && e.ctrlKey) {
      e.preventDefault();
      NALLY.sendChat();
      return;
    }
  });

  d.titlebar.addEventListener('dblclick', function(e) {
    if (e.target.classList.contains('dot')) return;
    NALLY.maximizeDrawer();
  });

  d.titlebar.addEventListener('mousedown', function(e) {
    if (NALLY.checkMobile()) return;
    if (e.target.classList.contains('dot')) return;
    if (s.isMaximized) return;
    s.dragState.active = true;
    var rect = d.chatDrawer.getBoundingClientRect();
    s.dragState.offsetX = e.clientX - rect.left;
    s.dragState.offsetY = e.clientY - rect.top;
    d.chatDrawer.style.transform = 'none';
    e.preventDefault();
  });

  document.addEventListener('mousemove', function(e) {
    if (!s.dragState.active) return;
    var x = e.clientX - s.dragState.offsetX;
    var y = e.clientY - s.dragState.offsetY;
    d.chatDrawer.style.left = x + 'px';
    d.chatDrawer.style.top = y + 'px';
  });

  document.addEventListener('mouseup', function() {
    s.dragState.active = false;
  });

  document.querySelectorAll('.resize-handle').forEach(function(handle) {
    handle.addEventListener('mousedown', function(e) {
      if (NALLY.checkMobile()) return;
      if (s.isMaximized) return;
      e.preventDefault();
      e.stopPropagation();
      var rect = d.chatDrawer.getBoundingClientRect();
      s.resizeState.active = true;
      s.resizeState.dir = handle.dataset.dir;
      s.resizeState.startX = e.clientX;
      s.resizeState.startY = e.clientY;
      s.resizeState.startW = rect.width;
      s.resizeState.startH = rect.height;
      s.resizeState.startL = rect.left;
      s.resizeState.startT = rect.top;
      d.chatDrawer.style.transform = 'none';
    });
  });

  document.addEventListener('mousemove', function(e) {
    if (!s.resizeState.active) return;
    var dx = e.clientX - s.resizeState.startX;
    var dy = e.clientY - s.resizeState.startY;
    var dir = s.resizeState.dir;
    var minW = 320, minH = 260;
    var newW = s.resizeState.startW, newH = s.resizeState.startH;
    var newL = s.resizeState.startL, newT = s.resizeState.startT;

    if (dir.includes('e')) newW = Math.max(minW, s.resizeState.startW + dx);
    if (dir.includes('w')) { newW = Math.max(minW, s.resizeState.startW - dx); newL = s.resizeState.startL + (s.resizeState.startW - newW); }
    if (dir.includes('s')) newH = Math.max(minH, s.resizeState.startH + dy);
    if (dir.includes('n')) { newH = Math.max(minH, s.resizeState.startH - dy); newT = s.resizeState.startT + (s.resizeState.startH - newH); }

    d.chatDrawer.style.width = newW + 'px';
    d.chatDrawer.style.height = newH + 'px';
    d.chatDrawer.style.left = newL + 'px';
    d.chatDrawer.style.top = newT + 'px';
  });

  document.addEventListener('mouseup', function() {
    s.resizeState.active = false;
  });

  NALLY.isMobile.addEventListener('change', function() {
    if (!NALLY.checkMobile() && s.drawerOpen) NALLY.closeDrawer();
  });
};
