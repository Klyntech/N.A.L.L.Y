// ─── Message Bubble ─────────────────────────────────
function MsgBubble(props) {
  var m = props.msg;
  var isUser = m.sender === 'user';
  var onRetry = props.onRetry;

  if (m.type === 'tool_call') {
    var isErr = m.success === false;
    return html`
      <div style=${{ display: 'flex', justifyContent: 'flex-start', padding: '2px 0', animation: 'fadeIn 0.2s ease-out' }}>
        <div class=${'tool-chip' + (isErr ? ' error' : '')}>
          ${isErr
            ? html`<${Li} name="XCircle" size=${12} color="#F87171" />`
            : html`<${Li} name="Loader" size=${12} color="#34D399" />`
          }
          <span>${m.name}</span>
          ${m.duration_ms != null && html`<span style=${{ color: 'rgba(255,255,255,0.2)', fontSize: '10px' }}>${m.duration_ms}ms</span>`}
        </div>
      </div>
    `;
  }

  function copyMsg() {
    navigator.clipboard.writeText(m.text).then(function() { beep(1200, 0.03, 'sine'); });
  }

  return html`
    <div class="msg-wrap" style=${{
      alignSelf: isUser ? 'flex-end' : 'flex-start',
      maxWidth: '85%',
      animation: 'fadeIn 0.2s ease-out',
      padding: '2px 0',
    }}>
      <div style=${{
        padding: '12px 16px',
        borderRadius: '18px',
        fontSize: '14px',
        lineHeight: '1.6',
        background: isUser ? 'rgba(108,92,231,0.1)' : 'rgba(255,255,255,0.04)',
        backdropFilter: 'blur(16px)',
        WebkitBackdropFilter: 'blur(16px)',
        border: '1px solid ' + (isUser ? 'rgba(108,92,231,0.12)' : 'rgba(255,255,255,0.05)'),
        borderBottomRightRadius: isUser ? '6px' : '18px',
        borderBottomLeftRadius: isUser ? '18px' : '6px',
        boxShadow: '0 2px 12px rgba(0,0,0,0.1)',
        overflowWrap: 'break-word',
        wordBreak: 'break-word',
      }}>
        ${isUser
          ? html`<div dangerouslySetInnerHTML=${{ __html: m.text.replace(/</g, '&lt;').replace(/\n/g, '<br/>') }} />`
          : html`<div dangerouslySetInnerHTML=${{ __html: md(m.text) }} />`
        }
        ${m.isTyping && html`<span style=${{ display: 'inline-block', width: '2px', height: '14px', background: 'rgba(108,92,231,0.5)', animation: 'pulse 1s infinite', verticalAlign: 'middle', marginLeft: '2px', borderRadius: '1px' }} />`}
      </div>
      <div class="msg-actions" style=${{ display: 'flex', gap: '4px', marginTop: '3px', justifyContent: isUser ? 'flex-end' : 'flex-start' }}>
        <button onclick=${copyMsg} style=${{ width: '24px', height: '24px', borderRadius: '6px', border: 'none', background: 'rgba(255,255,255,0.04)', color: 'rgba(255,255,255,0.25)', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', transition: 'all 0.2s' }} title="Copy">
          <${Li} name="Copy" size=${12} color="rgba(255,255,255,0.25)" />
        </button>
        ${!isUser && onRetry && html`
          <button onclick=${function() { onRetry(m.text); }} style=${{ width: '24px', height: '24px', borderRadius: '6px', border: 'none', background: 'rgba(255,255,255,0.04)', color: 'rgba(255,255,255,0.25)', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', transition: 'all 0.2s' }} title="Retry">
            <${Li} name="RotateCw" size=${12} color="rgba(255,255,255,0.25)" />
          </button>
        `}
      </div>
      <div style=${{ fontSize: '10px', color: 'var(--text-faint)', marginTop: '2px', textAlign: isUser ? 'right' : 'left' }}>${m.stamp}</div>
    </div>
  `;
}

// ─── Chat History ───────────────────────────────────
function ChatHistory(props) {
  var messages = props.messages || [];
  var thinking = props.thinking;
  var activeTool = props.activeTool;
  var onRetry = props.onRetry;
  var cards = props.cards || [];
  var onDismissCard = props.onDismissCard;

  var feedRef = useRef(null);

  useEffect(function() {
    if (feedRef.current) {
      feedRef.current.scrollTop = feedRef.current.scrollHeight;
    }
  }, [messages.length, thinking, cards.length]);

  var hasMessages = messages.length > 0 || cards.length > 0;

  if (!hasMessages) return null;

  return html`
    <div ref=${feedRef} style=${{
      flex: 1,
      overflowY: 'auto',
      padding: '8px 16px',
      display: 'flex',
      flexDirection: 'column',
      gap: '6px',
      maxWidth: '680px',
      width: '100%',
      margin: '0 auto',
    }}>
      ${messages.map(function(m) {
        return html`<${MsgBubble} key=${m.id} msg=${m} onRetry=${onRetry} />`;
      })}

      ${cards.map(function(c) {
        switch (c.type) {
          case 'weather': return html`<${WeatherCard} key=${c.id} data=${c.data} onDismiss=${function() { onDismissCard(c.id); }} />`;
          case 'tasks': return html`<${TasksCard} key=${c.id} tasks=${c.data.tasks} onToggle=${c.data.onToggle} onAdd=${c.data.onAdd} onRemove=${c.data.onRemove} onDismiss=${function() { onDismissCard(c.id); }} />`;
          case 'email': return html`<${EmailCard} key=${c.id} emails=${c.data} onDismiss=${function() { onDismissCard(c.id); }} />`;
          case 'music': return html`<${MusicCard} key=${c.id} track=${c.data.track} playing=${c.data.playing} onPlayPause=${c.data.onPlayPause} onPrev=${c.data.onPrev} onNext=${c.data.onNext} progress=${c.data.progress} onDismiss=${function() { onDismissCard(c.id); }} />`;
          case 'clock': return html`<${ClockCard} key=${c.id} onDismiss=${function() { onDismissCard(c.id); }} />`;
          case 'notes': return html`<${NotesCard} key=${c.id} notes=${c.data.notes} onChange=${c.data.onChange} onDismiss=${function() { onDismissCard(c.id); }} />`;
          case 'status': return html`<${StatusCard} key=${c.id} connected=${c.data.connected} msgCount=${c.data.msgCount} onDismiss=${function() { onDismissCard(c.id); }} />`;
          default: return null;
        }
      })}

      ${thinking && !activeTool && html`
        <div style=${{ alignSelf: 'flex-start', padding: '4px 0' }}>
          <div class="dot-bounce" style=${{ display: 'flex', gap: '5px', padding: '10px 16px', background: 'rgba(255,255,255,0.03)', borderRadius: '14px', borderBottomLeftRadius: '4px', border: '1px solid rgba(255,255,255,0.04)' }}>
            <span style=${{ width: '5px', height: '5px', borderRadius: '50%', background: 'rgba(108,92,231,0.5)' }} />
            <span style=${{ width: '5px', height: '5px', borderRadius: '50%', background: 'rgba(108,92,231,0.5)' }} />
            <span style=${{ width: '5px', height: '5px', borderRadius: '50%', background: 'rgba(108,92,231,0.5)' }} />
          </div>
        </div>
      `}
    </div>
  `;
}
