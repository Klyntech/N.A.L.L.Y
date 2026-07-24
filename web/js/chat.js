// ─── Message Bubble ─────────────────────────────────
function MsgBubble(props) {
  var m = props.msg;
  var isUser = m.sender === 'user';
  var onRetry = props.onRetry;
  var msgIndex = props.msgIndex || 0;

  if (m.type === 'tool_call') {
    var isErr = m.success === false;
    return html`
      <div class="msg-enter" style=${{ display: 'flex', justifyContent: 'flex-start', padding: '2px 0', animationDelay: (msgIndex * 40) + 'ms' }}>
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
    <div class=${'msg-wrap msg-enter' + (isUser ? ' msg-enter-user' : '')} style=${{
      alignSelf: isUser ? 'flex-end' : 'flex-start',
      maxWidth: '85%',
      animationDelay: (msgIndex * 40) + 'ms',
      padding: '2px 0',
    }}>
      <div style=${{
        padding: '12px 16px',
        borderRadius: '18px',
        fontSize: '14px',
        lineHeight: '1.6',
        background: isUser ? 'rgba(124,106,239,0.1)' : 'var(--surface)',
        border: '1px solid ' + (isUser ? 'rgba(124,106,239,0.12)' : 'var(--border)'),
        borderBottomRightRadius: isUser ? '6px' : '18px',
        borderBottomLeftRadius: isUser ? '18px' : '6px',
        boxShadow: '0 2px 8px rgba(0,0,0,0.15)',
        overflowWrap: 'break-word',
        wordBreak: 'break-word',
      }}>
        ${isUser
          ? html`<div dangerouslySetInnerHTML=${{ __html: m.text.replace(/</g, '&lt;').replace(/\n/g, '<br/>') }} />`
          : html`<div dangerouslySetInnerHTML=${{ __html: md(m.text) }} />`
        }
        ${m.isTyping && html`<span style=${{ display: 'inline-block', width: '2px', height: '14px', background: 'rgba(124,106,239,0.5)', animation: 'pulse 1s infinite', verticalAlign: 'middle', marginLeft: '2px', borderRadius: '1px' }} />`}
      </div>
      <div class="msg-actions" style=${{ display: 'flex', gap: '4px', marginTop: '3px', justifyContent: isUser ? 'flex-end' : 'flex-start' }}>
        <button onclick=${copyMsg} style=${{ width: '24px', height: '24px', borderRadius: '6px', border: 'none', background: 'rgba(255,255,255,0.04)', color: 'rgba(255,255,255,0.25)', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }} title="Copy">
          <${Li} name="Copy" size=${12} color="rgba(255,255,255,0.25)" />
        </button>
        ${!isUser && onRetry && html`
          <button onclick=${function() { onRetry(m.text); }} style=${{ width: '24px', height: '24px', borderRadius: '6px', border: 'none', background: 'rgba(255,255,255,0.04)', color: 'rgba(255,255,255,0.25)', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }} title="Retry">
            <${Li} name="RotateCw" size=${12} color="rgba(255,255,255,0.25)" />
          </button>
        `}
      </div>
      <div style=${{ fontSize: '10px', color: 'var(--text-faint)', marginTop: '2px', textAlign: isUser ? 'right' : 'left' }}>${m.stamp}</div>
    </div>
  `;
}

// ─── Skeleton Loader (cold start only) ──────────────
function SkeletonLoader() {
  return html`
    <div style=${{ display: 'flex', flexDirection: 'column', gap: '10px', padding: '8px 0' }}>
      <div class="skeleton-bubble nally" style=${{ width: '75%', padding: '14px 16px' }}>
        <div class="skeleton-line" style=${{ width: '90%' }} />
        <div class="skeleton-line" style=${{ width: '70%' }} />
        <div class="skeleton-line" style=${{ width: '50%' }} />
      </div>
      <div class="skeleton-bubble nally" style=${{ width: '55%', padding: '14px 16px' }}>
        <div class="skeleton-line" style=${{ width: '85%' }} />
        <div class="skeleton-line" />
      </div>
    </div>
  `;
}

// ─── Typing Wave Indicator ──────────────────────────
function TypingWave() {
  return html`
    <div style=${{ alignSelf: 'flex-start', padding: '4px 0' }}>
      <div class="typing-wave" style=${{ background: 'var(--surface)', borderRadius: '14px', borderBottomLeftRadius: '4px', border: '1px solid var(--border)' }}>
        <div class="typing-wave-dot" />
        <div class="typing-wave-dot" />
        <div class="typing-wave-dot" />
      </div>
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
  var _showFab = useState(false);
  var showFab = _showFab[0], setShowFab = _showFab[1];

  useEffect(function() {
    var el = feedRef.current;
    if (!el) return;
    function onScroll() {
      var distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
      setShowFab(distFromBottom > 120);
    }
    el.addEventListener('scroll', onScroll, { passive: true });
    return function() { el.removeEventListener('scroll', onScroll); };
  }, []);

  useEffect(function() {
    if (feedRef.current && !showFab) {
      feedRef.current.scrollTop = feedRef.current.scrollHeight;
    }
  }, [messages.length, thinking, cards.length]);

  function scrollToBottom() {
    if (feedRef.current) {
      feedRef.current.scrollTo({ top: feedRef.current.scrollHeight, behavior: 'smooth' });
    }
  }

  var hasMessages = messages.length > 0 || cards.length > 0;

  if (!hasMessages) return null;

  // Cold start: thinking with no messages yet → show skeleton
  var isColdStart = thinking && messages.length === 0;

  return html`
    <div style=${{ flex: 1, position: 'relative', overflow: 'hidden' }}>
      <div ref=${feedRef} style=${{
        height: '100%',
        overflowY: 'auto',
        padding: '8px 16px',
        display: 'flex',
        flexDirection: 'column',
        gap: '6px',
        maxWidth: '680px',
        width: '100%',
        margin: '0 auto',
      }}>
        ${isColdStart && html`<${SkeletonLoader} />`}

        ${messages.map(function(m, i) {
          return html`<${MsgBubble} key=${m.id} msg=${m} onRetry=${onRetry} msgIndex=${i} />`;
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

        ${thinking && !activeTool && !isColdStart && html`<${TypingWave} />`}
      </div>

      ${showFab && html`
        <button onClick=${scrollToBottom} class="scroll-fab" style=${{
          position: 'absolute',
          bottom: '12px',
          right: '12px',
          width: '36px',
          height: '36px',
          borderRadius: '50%',
          border: '1px solid var(--border)',
          background: 'var(--surface)',
          color: 'var(--iris)',
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          boxShadow: '0 4px 16px rgba(0,0,0,0.3)',
          zIndex: 20,
          animation: 'fadeIn 0.2s ease-out',
        }}>
          <${Li} name="ChevronDown" size=${18} />
        </button>
      `}
    </div>
  `;
}
