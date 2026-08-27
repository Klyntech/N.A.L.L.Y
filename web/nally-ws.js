/**
 * Nally WebSocket Client
 * 
 * Provides bidirectional real-time chat via WebSocket.
 * Falls back to SSE if WebSocket is unavailable.
 * 
 * Protocol:
 *   Send: {"type": "user_message", "text": "...", "tab_id": "..."}
 *   Recv: {"type": "thought|stream_chunk|tool_call|tool_result|response|error|done", ...}
 */

class NallyWebSocket {
  constructor(url, token) {
    this.url = url;
    this.token = token;
    this.ws = null;
    this.connected = false;
    this.reconnectDelay = 1000;
    this.maxReconnectDelay = 30000;
    this.handlers = {};
    this.messageQueue = [];
    this._reconnectTimer = null;  // Track pending reconnect timer
  }

  /**
   * Connect to WebSocket server
   */
  connect() {
    if (this.ws && (this.ws.readyState === WebSocket.CONNECTING || this.ws.readyState === WebSocket.OPEN)) {
      return;
    }

    const wsUrl = `${this.url}?token=${encodeURIComponent(this.token)}`;
    
    try {
      this.ws = new WebSocket(wsUrl);
    } catch (e) {
      console.warn('[ws] Connection failed:', e);
      this._scheduleReconnect();
      return;
    }

    this.ws.onopen = () => {
      console.log('[ws] Connected');
      this.connected = true;
      this.reconnectDelay = 1000;
      this._reconnectTimer = null;
      this._flushQueue();
      this._emit('connected', {});
    };

    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'ping') {
          // Respond to server heartbeat
          this._send({ type: 'pong' });
          return;
        }
        this._emit(data.type, data);
      } catch (e) {
        console.error('[ws] Parse error:', e);
      }
    };

    this.ws.onclose = (event) => {
      console.log('[ws] Disconnected:', event.code, event.reason);
      this.connected = false;
      this._emit('disconnected', { code: event.code, reason: event.reason });
      
      if (event.code !== 1000) { // Not clean close
        this._scheduleReconnect();
      }
    };

    this.ws.onerror = (error) => {
      console.error('[ws] Error:', error);
    };
  }

  /**
   * Disconnect from WebSocket
   */
  disconnect() {
    if (this._reconnectTimer) {
      clearTimeout(this._reconnectTimer);
      this._reconnectTimer = null;
    }
    if (this.ws) {
      this.ws.close(1000, 'Client disconnect');
      this.ws = null;
    }
    this.connected = false;
  }

  /**
   * Send a user message
   */
  send(text, tabId) {
    const msg = {
      type: 'user_message',
      text: text,
      tab_id: tabId || ''
    };
    this._send(msg);
  }

  /**
   * Send voice audio (base64 encoded)
   */
  sendAudio(base64Audio, tabId, format) {
    this._send({
      type: 'voice_audio',
      audio: base64Audio,
      format: format || 'pcm_s16le',
      tab_id: tabId || ''
    });
  }

  /**
   * Send abort signal
   */
  abort() {
    this._send({ type: 'abort' });
  }

  /**
   * Send approval response
   */
  approve(toolCallId, approved) {
    this._send({
      type: 'approval',
      tool_call_id: toolCallId,
      approved: approved
    });
  }

  /**
   * Register event handler
   */
  on(event, handler) {
    if (!this.handlers[event]) {
      this.handlers[event] = [];
    }
    this.handlers[event].push(handler);
    return this;
  }

  /**
   * Remove event handler
   */
  off(event, handler) {
    if (this.handlers[event]) {
      this.handlers[event] = this.handlers[event].filter(h => h !== handler);
    }
    return this;
  }

  // ── Internal ──────────────────────────────────────────

  _send(msg) {
    if (this.connected && this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg));
    } else {
      this.messageQueue.push(msg);
    }
  }

  _emit(event, data) {
    const handlers = this.handlers[event] || [];
    for (const handler of handlers) {
      try {
        handler(data);
      } catch (e) {
        console.error('[ws] Handler error:', e);
      }
    }
  }

  _flushQueue() {
    while (this.messageQueue.length > 0) {
      const msg = this.messageQueue.shift();
      this._send(msg);
    }
  }

  _scheduleReconnect() {
    // Cancel any pending reconnect timer to prevent stacking
    if (this._reconnectTimer) {
      clearTimeout(this._reconnectTimer);
      this._reconnectTimer = null;
    }
    // Increase delay BEFORE scheduling so rapid onclose events don't stack
    const baseDelay = this.reconnectDelay;
    this.reconnectDelay = Math.min(this.reconnectDelay * 2, this.maxReconnectDelay);
    // Add jitter (0-50% of delay) to prevent thundering herd on multi-tab reconnect
    const jitter = Math.floor(Math.random() * (baseDelay * 0.5));
    const delay = baseDelay + jitter;
    console.log(`[ws] Reconnecting in ${delay}ms...`);
    this._reconnectTimer = setTimeout(() => {
      this._reconnectTimer = null;
      this.connect();
    }, delay);
  }
}

// Export for use
window.NallyWebSocket = NallyWebSocket;
