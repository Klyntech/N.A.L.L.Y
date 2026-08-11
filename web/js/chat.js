window.NALLY = window.NALLY || {};

NALLY.addChatMsg = function(text, isNally) {
  if (typeof text !== 'string') text = String(text || '');
  var d = NALLY.dom;
  var msg = document.createElement('div');
  msg.className = 'drawer-msg ' + (isNally ? 'nally' : 'user');

  if (isNally) {
    var name = document.createElement('div');
    name.className = 'msg-name';
    name.textContent = 'NALLY';
    msg.appendChild(name);
  }

  var textEl = document.createElement('div');
  textEl.className = 'msg-text';
  textEl.innerHTML = isNally ? NALLY.renderMd(text) : text.replace(/</g, '&lt;').replace(/>/g, '&gt;');

  msg.appendChild(textEl);

  if (isNally) {
    var copyBtn = document.createElement('button');
    copyBtn.className = 'msg-copy';
    copyBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256"><rect x="92" y="92" width="100" height="100" rx="8" fill="none" stroke="currentColor" stroke-width="16"/><path d="M200,56V40a8,8,0,0,0-8-8H40A8,8,0,0,0,32,40V168a8,8,0,0,0,8,8H56" fill="none" stroke="currentColor" stroke-width="16" stroke-linecap="round"/></svg>';
    copyBtn.title = 'Copy';
    copyBtn.addEventListener('click', function() {
      navigator.clipboard.writeText(text).then(function() {
        copyBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256"><polyline points="40 144 96 200 216 80" fill="none" stroke="currentColor" stroke-width="16" stroke-linecap="round" stroke-linejoin="round"/></svg>';
        setTimeout(function() {
          copyBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256"><rect x="92" y="92" width="100" height="100" rx="8" fill="none" stroke="currentColor" stroke-width="16"/><path d="M200,56V40a8,8,0,0,0-8-8H40A8,8,0,0,0,32,40V168a8,8,0,0,0,8,8H56" fill="none" stroke="currentColor" stroke-width="16" stroke-linecap="round"/></svg>';
        }, 1500);
      });
    });
    msg.appendChild(copyBtn);
  }

  if (isNally) {
    var traceLink = document.createElement('button');
    traceLink.className = 'msg-trace';
    traceLink.textContent = 'View trace';
    traceLink.addEventListener('click', function() {
      if (NALLY.state.currentRunId) {
        NALLY.showTrace(NALLY.state.currentRunId);
      }
    });
    msg.appendChild(traceLink);
  }

  d.chatMessages.appendChild(msg);
  d.scrollToBottom();
};

NALLY.addChatMsgStream = function() {
  var d = NALLY.dom;
  var msg = document.createElement('div');
  msg.className = 'drawer-msg nally';

  var name = document.createElement('div');
  name.className = 'msg-name';
  name.textContent = 'NALLY';
  msg.appendChild(name);

  var textEl = document.createElement('div');
  textEl.className = 'msg-text';
  textEl.textContent = '';
  msg.appendChild(textEl);

  d.chatMessages.appendChild(msg);
  d.scrollToBottom();
  return textEl;
};

NALLY.showTyping = function() {
  NALLY.removeTyping();
  var d = NALLY.dom;
  var wrap = document.createElement('div');
  wrap.className = 'typing-indicator';
  var wave = document.createElement('div');
  wave.className = 'typing-wave';
  for (var i = 0; i < 5; i++) {
    var bar = document.createElement('div');
    bar.className = 'typing-bar';
    wave.appendChild(bar);
  }
  wrap.appendChild(wave);
  d.chatMessages.appendChild(wrap);
  d.scrollToBottom();
  NALLY.state.typingEl = wrap;
};

NALLY.removeTyping = function() {
  if (NALLY.state.typingEl) { NALLY.state.typingEl.remove(); NALLY.state.typingEl = null; }
};

NALLY.loadHistory = function() {
  if (NALLY.state.streamMsgEl) return;
  fetch(NALLY.API + '/api/history', {
    headers: { 'Authorization': 'Bearer ' + NALLY.state.token }
  }).then(function(r) { return r.json(); }).then(function(data) {
    if (data.messages && data.messages.length) {
      data.messages.forEach(function(m) {
        if (m.role !== 'system' && m.role !== 'tool') {
          NALLY.addChatMsg(m.content, m.role === 'assistant');
        }
      });
    }
  }).catch(function(){});
};

NALLY.clearChat = function() {
  fetch(NALLY.API + '/api/clear', {
    method: 'POST',
    headers: { 'Authorization': 'Bearer ' + NALLY.state.token }
  }).then(function() {
    NALLY.dom.chatMessages.innerHTML = '';
  }).catch(function(){});
};
