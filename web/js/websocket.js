window.NALLY = window.NALLY || {};

NALLY.initWebSocket = function() {
  var s = NALLY.state;
  if (!s.token || s.ws) return;
  
  var wsProtocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  var wsUrl = wsProtocol + '//' + location.host + '/ws/web:default';
  
  s.ws = new NallyWebSocket(wsUrl, s.token);
  
  s.ws.on('connected', function() {
    console.log('[chat] WebSocket connected');
    s.useWebSocket = true;
  });
  
  s.ws.on('disconnected', function() {
    console.log('[chat] WebSocket disconnected, falling back to SSE');
    s.useWebSocket = false;
  });
  
  s.ws.on('thought', function(data) {
    NALLY.think(data.text || 'Thinking...');
  });
  
  s.ws.on('stream_chunk', function(data) {
    NALLY.removeTyping();
    if (!s.streamMsgEl) {
      s.streamMsgEl = NALLY.addChatMsgStream();
    }
    if (typeof data.text === 'string') {
      s.streamMsgEl.textContent += data.text;
    }
  });
  
  s.ws.on('tool_call', function(data) {
    NALLY.removeTyping();
    NALLY.addToolCard(data.name, data.args, data.id);
    NALLY.think('Running ' + data.name + '...');
  });
  
  s.ws.on('tool_result', function(data) {
    NALLY.updateToolCard(data.tool_call_id, data.result, false);
    NALLY.think('Processing result...');
    if (data.diff && data.file_path) {
      NALLY.showDiff(data.diff, data.file_path);
    }
  });

  s.ws.on('verification', function(data) {
    if (data.is_honest === false || data.contradicted_count > 0 || data.unsupported_count > 0) {
      var warnings = [];
      for (var i = 0; i < (data.findings || []).length; i++) {
        var f = data.findings[i];
        if (f.verdict === 'unsupported' || f.verdict === 'contradicted') {
          warnings.push('[' + f.verdict + '] ' + f.claim + ': ' + f.evidence);
        }
      }
      if (warnings.length > 0) {
        NALLY.think('Verification: ' + warnings.length + ' claim(s) flagged');
      }
    }
  });

  s.ws.on('response', function(data) {
    NALLY.removeTyping();
    NALLY.dom.clearThinking();

    if (s.streamMsgEl) {
      s.streamMsgEl.innerHTML = NALLY.renderMd(data.text || '');
      lucide.createIcons();
      s.streamMsgEl = null;
    } else {
      NALLY.addChatMsg(data.text || '', true);
    }
  });
  
  s.ws.on('error', function(data) {
    NALLY.removeTyping();
    NALLY.dom.clearThinking();
    if (data.text) {
      NALLY.addChatMsg(data.text, true);
    }
  });

  s.ws.on('busy', function(data) {
    NALLY.think(data.text || 'Queued...');
  });

  s.ws.on('done', function() {
    s.streamMsgEl = null;
  });
  
  s.ws.on('user_message', function(data) {
    if (data.tab_id === s.tabId) return;
    NALLY.addChatMsg(data.text || '', false);
  });
  
  s.ws.on('assistant_message', function(data) {
    if (data.tab_id === s.tabId) return;
    NALLY.addChatMsg(data.text || '', true);
  });
  
  s.ws.on('thinking', function(data) {
    if (data.tab_id === s.tabId) return;
    NALLY.showTyping();
  });
  
  s.ws.on('history_cleared', function() {
    NALLY.dom.chatMessages.innerHTML = '';
  });
  
  s.ws.on('approval_resolved', function() {
  });
  
  s.ws.on('mcp_status', function() {
    NALLY.renderServices();
  });

  s.ws.on('voice_transcript', function(data) {
    NALLY.addChatMsg(data.text, false);
    NALLY.showTyping();
    NALLY.think('Thinking...');
  });

  s.ws.on('tts_audio', function(data) {
    NALLY.removeTyping();
    try {
      var raw = atob(data.audio);
      var arr = new Uint8Array(raw.length);
      for (var i = 0; i < raw.length; i++) arr[i] = raw.charCodeAt(i);
      var audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      audioCtx.decodeAudioData(arr.buffer, function(buffer) {
        var source = audioCtx.createBufferSource();
        source.buffer = buffer;
        source.connect(audioCtx.destination);
        source.onended = function() { audioCtx.close(); };
        source.start(0);
      }, function(e) {
        console.warn('[tts] decode failed:', e);
      });
    } catch (e) {
      console.warn('[tts] playback error:', e);
    }
  });

  s.ws.on('confirmation_required', function(data) {
    NALLY.buildApprovalCard(data);
  });

  s.ws.on('run_id', function(data) {
    s.currentRunId = data.run_id || null;
  });
  
  s.ws.connect();
};
