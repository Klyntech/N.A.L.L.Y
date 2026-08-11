window.NALLY = window.NALLY || {};

NALLY.handleSSE = function(evt, setStreamEl) {
  var s = NALLY.state;
  switch (evt.type) {
    case 'busy':
      NALLY.think(evt.text);
      break;

    case 'tool_call':
      NALLY.removeTyping();
      NALLY.addToolCard(evt.name, evt.args, evt.id);
      NALLY.think('Running ' + evt.name + '...');
      break;

    case 'tool_result':
      NALLY.updateToolCard(evt.tool_call_id, evt.result, false);
      NALLY.think('Processing result...');
      if (evt.diff && evt.file_path) {
        NALLY.showDiff(evt.diff, evt.file_path);
      }
      break;

    case 'thought':
      NALLY.think(evt.text);
      break;

    case 'stream_chunk':
      NALLY.removeTyping();
      if (!s.streamMsgEl) {
        s.streamMsgEl = NALLY.addChatMsgStream();
        setStreamEl(s.streamMsgEl);
      }
      if (typeof evt.text !== 'string') {
        console.warn('[stream_chunk] non-string evt.text:', typeof evt.text, evt);
      }
      s.streamMsgEl.textContent += (typeof evt.text === 'string' ? evt.text : '');
      NALLY.dom.scrollToBottom();
      break;

    case 'response':
      NALLY.removeTyping();
      NALLY.dom.clearThinking();
      if (typeof evt.text !== 'string') {
        console.warn('[response] non-string evt.text:', typeof evt.text, evt);
      }
      var respText = typeof evt.text === 'string' ? evt.text : String(evt.text || '');
      if (s.streamMsgEl) {
        s.streamMsgEl.innerHTML = NALLY.renderMd(respText);
        lucide.createIcons();
        var _msgEl2 = s.streamMsgEl.parentElement;
        if (_msgEl2 && !_msgEl2.querySelector('.msg-trace')) {
          var traceLink2 = document.createElement('button');
          traceLink2.className = 'msg-trace';
          traceLink2.textContent = 'View trace';
          traceLink2.addEventListener('click', function() {
            if (s.currentRunId) NALLY.showTrace(s.currentRunId);
          });
          _msgEl2.appendChild(traceLink2);
        }
      } else {
        NALLY.addChatMsg(respText, true);
      }
      s.streamMsgEl = null;
      NALLY.speak(respText);
      break;

    case 'error':
      NALLY.removeTyping();
      NALLY.dom.clearThinking();
      s.streamMsgEl = null;
      NALLY.addChatMsg('Error: ' + evt.text, true);
      break;

    case 'stream_done':
      NALLY.removeTyping();
      NALLY.dom.clearThinking();
      if (s.streamMsgEl) {
        s.streamMsgEl.innerHTML = NALLY.renderMd(s.streamMsgEl.textContent);
        lucide.createIcons();
        var _msgEl = s.streamMsgEl.parentElement;
        if (_msgEl && !_msgEl.querySelector('.msg-trace')) {
          var traceLink = document.createElement('button');
          traceLink.className = 'msg-trace';
          traceLink.textContent = 'View trace';
          traceLink.addEventListener('click', function() {
            if (s.currentRunId) NALLY.showTrace(s.currentRunId);
          });
          _msgEl.appendChild(traceLink);
        }
      }
      break;

    case 'run_id':
      s.currentRunId = evt.run_id || null;
      break;

    case 'confirmation_required':
      NALLY.buildApprovalCard(evt);
      break;
  }
};

NALLY.sendChat = function() {
  var s = NALLY.state;
  var d = NALLY.dom;
  var text = d.chatInput.value.trim();
  if (!text) return;
  NALLY.addChatMsg(text, false);
  d.chatInput.value = '';
  d.chatInput.style.height = 'auto';
  s.streamMsgEl = null;

  NALLY.showTyping();
  NALLY.think('Thinking...');

  if (s.useWebSocket && s.ws && s.ws.connected) {
    s.ws.send(text, s.tabId);
    return;
  }

  if (s.chatAbort) s.chatAbort.abort();
  s.chatAbort = new AbortController();

  var streamMsgEl = null;

  fetch(NALLY.API + '/api/chat', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': 'Bearer ' + s.token,
    },
    body: JSON.stringify({ message: text, tab_id: s.tabId }),
    signal: s.chatAbort.signal,
  }).then(function(res) {
    if (!res.ok) throw new Error('HTTP ' + res.status);
    var reader = res.body.getReader();
    var decoder = new TextDecoder();
    var buffer = '';

    function readChunk() {
      reader.read().then(function(result) {
        if (result.done) {
          NALLY.removeTyping();
          NALLY.dom.clearThinking();
          if (streamMsgEl && !streamMsgEl.querySelector('p, h1, h2, h3, h4, ul, ol, pre, blockquote, table')) {
            streamMsgEl.innerHTML = NALLY.renderMd(streamMsgEl.textContent);
            lucide.createIcons();
          }
          return;
        }

        buffer += decoder.decode(result.value, { stream: true });
        var lines = buffer.split('\n');
        buffer = lines.pop();

        for (var i = 0; i < lines.length; i++) {
          var line = lines[i].trim();
          if (!line.startsWith('data: ')) continue;
          var jsonStr = line.substring(6);
          if (jsonStr === '{"event": "done"}') continue;

          try {
            var evt = JSON.parse(jsonStr);
            NALLY.handleSSE(evt, function(el) { streamMsgEl = el; });
          } catch (e) { console.error('SSE parse error:', e, jsonStr); }
        }

        readChunk();
      });
    }

    readChunk();
  }).catch(function(err) {
    if (err.name === 'AbortError') return;
    NALLY.removeTyping();
    NALLY.dom.clearThinking();
    NALLY.addChatMsg('Backend offline — make sure NALLY server is running on port 5000.', true);
  });
};
