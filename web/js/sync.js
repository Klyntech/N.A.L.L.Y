window.NALLY = window.NALLY || {};

NALLY.initSync = function() {
  var s = NALLY.state;

  // 1. BroadcastChannel: instant sync for settings across tabs
  try {
    s.syncChannel = new BroadcastChannel('nally-sync');
    s.syncChannel.onmessage = function(e) {
      var d = e.data;
      if (!d || !d.type) return;
      if (d.type === 'theme') {
        document.body.className = '';
        document.body.classList.add('theme-' + d.value);
        if (NALLY.dom.compactToggle.checked) document.body.classList.add('compact');
        if (NALLY.dom.lockToggle.checked) document.body.classList.add('lock-mode');
        document.querySelectorAll('.theme-swatch').forEach(function(sw) {
          sw.classList.toggle('active', sw.dataset.theme === d.value);
        });
      } else if (d.type === 'compact') {
        document.body.classList.toggle('compact', d.value);
        NALLY.dom.compactToggle.checked = d.value;
      } else if (d.type === 'lock') {
        document.body.classList.toggle('lock-mode', d.value);
        NALLY.dom.lockToggle.checked = d.value;
      } else if (d.type === 'clear') {
        if (d.tab_id === s.tabId) return;
        NALLY.dom.chatMessages.innerHTML = '';
      } else if (d.type === 'history') {
        NALLY.loadHistory();
      } else if (d.type === 'mcp') {
        NALLY.renderServices();
      }
    };
  } catch(e) { console.warn('BroadcastChannel not supported'); }

  // Wrap settings functions to broadcast changes
  var origSetTheme = NALLY.setTheme;
  NALLY.setTheme = function(name) {
    origSetTheme(name);
    if (s.syncChannel) s.syncChannel.postMessage({ type: 'theme', value: name });
  };

  var origSetCompact = NALLY.setCompact;
  NALLY.setCompact = function(on) {
    origSetCompact(on);
    if (s.syncChannel) s.syncChannel.postMessage({ type: 'compact', value: on });
  };

  var origSetLockMode = NALLY.setLockMode;
  NALLY.setLockMode = function(on) {
    origSetLockMode(on);
    if (s.syncChannel) s.syncChannel.postMessage({ type: 'lock', value: on });
  };

  // Wrap clearChat to broadcast
  var origClearChat = NALLY.clearChat;
  NALLY.clearChat = function() {
    origClearChat();
    if (s.syncChannel) s.syncChannel.postMessage({ type: 'clear', tab_id: s.tabId });
  };
};

// 2. Persistent SSE: subscribe to server-side events for real-time sync
NALLY.subscribeEvents = function() {
  var s = NALLY.state;
  if (s.evtSource) { s.evtSource.close(); s.evtSource = null; }
  if (!s.token) return;
  try {
    s.evtSource = new EventSource(NALLY.API + '/api/events?token=' + encodeURIComponent(s.token));
    s.evtSource.addEventListener('connected', function() {
      console.log('[sync] Connected to event stream');
    });
    s.evtSource.addEventListener('user_message', function(e) {
      var data = {};
      try { data = JSON.parse(e.data); } catch(err) {}
      if (data.tab_id === s.tabId) return;
      NALLY.addChatMsg(data.text || '', false);
    });
    s.evtSource.addEventListener('thinking', function(e) {
      var data = {};
      try { data = JSON.parse(e.data); } catch(err) {}
      if (data.tab_id === s.tabId) return;
      NALLY.showTyping();
    });
    s.evtSource.addEventListener('assistant_message', function(e) {
      var data = {};
      try { data = JSON.parse(e.data); } catch(err) {}
      if (data.tab_id === s.tabId) return;
      NALLY.removeTyping();
      NALLY.addChatMsg(data.text || '', true);
    });
    s.evtSource.addEventListener('history_cleared', function(e) {
      var data = {};
      try { data = JSON.parse(e.data); } catch(err) {}
      if (data.tab_id === s.tabId) return;
      NALLY.dom.chatMessages.innerHTML = '';
    });
    s.evtSource.addEventListener('approval_resolved', function() {
    });
    s.evtSource.addEventListener('mcp_status', function() {
      NALLY.renderServices();
    });
    s.evtSource.addEventListener('verification', function(e) {
      var data = {};
      try { data = JSON.parse(e.data); } catch(err) {}
      if (data.is_honest === false || data.contradicted_count > 0 || data.unsupported_count > 0) {
        var warnings = [];
        for (var i = 0; i < (data.findings || []).length; i++) {
          var f = data.findings[i];
          if (f.verdict === 'unsupported' || f.verdict === 'contradicted') {
            warnings.push('[' + f.verdict + '] ' + f.claim);
          }
        }
        if (warnings.length > 0) {
          NALLY.think('Verification: ' + warnings.length + ' claim(s) flagged');
        }
      }
    });
    s.evtSource.onerror = function() {
      s.evtSource.close();
      s.evtSource = null;
      if (!s.token) return;
      NALLY.verifyToken(s.token).then(function(ok) {
        if (!ok) {
          console.warn('[sync] Token expired, prompting re-login');
          NALLY.showLogin();
        } else {
          console.warn('[sync] SSE error, will retry in 5s...');
          setTimeout(NALLY.subscribeEvents, 5000);
        }
      });
    };
  } catch(e) {
    console.warn('[sync] EventSource failed:', e);
    setTimeout(NALLY.subscribeEvents, 5000);
  }
};
