// ─── Input Bar Component ────────────────────────────
function InputBar(props) {
  var _text = useState('');
  var text = _text[0], setText = _text[1];
  var inputRef = useRef(null);

  var onSend = props.onSend;
  var listening = props.listening;
  var onMicToggle = props.onMicToggle;
  var voiceTranscript = props.voiceTranscript || '';
  var placeholder = props.placeholder || 'Ask Nally anything...';

  var hasText = text.trim().length > 0;
  var displayText = listening ? voiceTranscript : text;

  function handleSubmit(e) {
    e.preventDefault();
    var msg = (listening ? voiceTranscript : text).trim();
    if (!msg) return;
    onSend(msg);
    setText('');
  }

  function handleClear() {
    setText('');
    if (inputRef.current) inputRef.current.focus();
  }

  useEffect(function() {
    if (inputRef.current && !listening) inputRef.current.focus();
  }, []);

  return html`
    <div class="input-bar-container" style=${{
      width: '100%',
      maxWidth: '680px',
      padding: '0 16px 16px',
      flexShrink: 0,
    }}>
      <form onSubmit=${handleSubmit} class="input-bar">
        <button type="button" onClick=${onMicToggle} class=${'mic-btn' + (listening ? ' listening' : '')} title=${listening ? 'Stop listening' : 'Start voice input'}>
          ${listening
            ? html`<${Li} name="Mic" size=${20} color="#3ECFB8" />`
            : html`<${Li} name="Mic" size=${20} />`
          }
        </button>

        <input
          ref=${inputRef}
          type="text"
          value=${displayText}
          onInput=${function(e) { if (!listening) setText(e.target.value); }}
          placeholder=${listening ? 'Listening...' : placeholder}
          readOnly=${listening}
          style=${{ opacity: listening && !voiceTranscript ? 0.5 : 1 }}
        />

        ${hasText && !listening && html`
          <button type="button" onclick=${handleClear} class="clear-text-btn">
            <${Li} name="X" size=${14} color="rgba(255,255,255,0.4)" />
          </button>
        `}

        <button type="submit" disabled=${!hasText} class=${'send-btn' + (hasText ? ' active' : '')}>
          ${hasText
            ? html`<${Li} name="ArrowUp" size=${18} color="#fff" />`
            : html`<${Li} name="Search" size=${18} color="rgba(255,255,255,0.15)" />`
          }
        </button>
      </form>
    </div>
  `;
}
