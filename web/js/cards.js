// ─── Result Card Wrapper ────────────────────────────
function ResultCard(props) {
  var title = props.title;
  var icon = props.icon;
  var iconColor = props.iconColor || 'rgba(108,92,231,0.7)';
  var onDismiss = props.onDismiss;
  var children = props.children;

  return html`
    <div class="result-card" style=${{ margin: '4px 0' }}>
      <div class="result-card-header">
        <div class="result-card-title">
          <${Li} name=${icon} size=${14} color=${iconColor} />
          <span>${title}</span>
        </div>
        ${onDismiss && html`
          <button class="result-card-dismiss" onClick=${onDismiss}>
            <${Li} name="X" size=${14} />
          </button>
        `}
      </div>
      <div>${children}</div>
    </div>
  `;
}

// ─── Weather Card ───────────────────────────────────
function WeatherCard(props) {
  var data = props.data || {};
  var temp = data.temp || '28';
  var condition = data.condition || 'Cloudy';
  var city = data.city || 'Lagos';
  var humidity = data.humidity || '78%';
  var wind = data.wind || '12 km/h';

  return html`
    <${ResultCard} title="Weather" icon="Cloud" iconColor="rgba(0,212,255,0.7)" onDismiss=${props.onDismiss}>
      <div style=${{ display: 'flex', alignItems: 'center', gap: '16px' }}>
        <div style=${{ fontSize: '42px', fontWeight: 700, color: '#fff', lineHeight: 1 }}>
          ${temp}<span style=${{ fontSize: '18px', fontWeight: 400, color: 'var(--text-dim)' }}>°C</span>
        </div>
        <div>
          <div style=${{ fontSize: '15px', fontWeight: 600, color: 'var(--text)' }}>${city}</div>
          <div style=${{ fontSize: '13px', color: 'var(--text-dim)', marginTop: '2px' }}>${condition}</div>
        </div>
      </div>
      <div style=${{ display: 'flex', gap: '16px', marginTop: '12px', fontSize: '12px', color: 'var(--text-dim)' }}>
        <span>💧 ${humidity}</span>
        <span>💨 ${wind}</span>
      </div>
    </${ResultCard}>
  `;
}

// ─── Tasks Card ─────────────────────────────────────
function TasksCard(props) {
  var tasks = props.tasks || [];
  var onToggle = props.onToggle;
  var onAdd = props.onAdd;
  var onRemove = props.onRemove;
  var onDismiss = props.onDismiss;

  var _newTask = useState('');
  var newTask = _newTask[0], setNewTask = _newTask[1];

  var done = tasks.filter(function(t) { return t.done; }).length;
  var total = tasks.length;

  function handleAdd(e) {
    e.preventDefault();
    if (!newTask.trim()) return;
    onAdd(newTask.trim());
    setNewTask('');
  }

  return html`
    <${ResultCard} title=${'Tasks' + (total ? ' (' + done + '/' + total + ')' : '')} icon="CheckSquare" iconColor="rgba(108,92,231,0.7)" onDismiss=${onDismiss}>
      <div style=${{ maxHeight: '200px', overflowY: 'auto' }}>
        ${tasks.map(function(t) {
          return html`
            <div class="task-item" key=${t.id}>
              <button class=${'task-check' + (t.done ? ' done' : '')} onClick=${function() { onToggle(t.id); }}>
                ${t.done && html`<${Li} name="Check" size=${12} color="#fff" />`}
              </button>
              <span class=${'task-text' + (t.done ? ' done' : '')}>${t.text}</span>
              <button class="task-del" onClick=${function() { onRemove(t.id); }}>
                <${Li} name="X" size=${12} />
              </button>
            </div>
          `;
        })}
        ${tasks.length === 0 && html`
          <div style=${{ fontSize: '13px', color: 'var(--text-faint)', textAlign: 'center', padding: '12px 0' }}>No tasks yet</div>
        `}
      </div>
      <form onSubmit=${handleAdd} style=${{ display: 'flex', gap: '8px', marginTop: '10px' }}>
        <input type="text" value=${newTask} onInput=${function(e) { setNewTask(e.target.value); }} placeholder="Add a task..." style=${{
          flex: 1, height: '34px', background: 'rgba(255,255,255,0.04)', border: '1px solid var(--border)',
          borderRadius: '8px', color: 'var(--text)', fontSize: '13px', fontFamily: 'var(--font)',
          padding: '0 10px', outline: 'none',
        }} />
        <button type="submit" disabled=${!newTask.trim()} style=${{
          height: '34px', padding: '0 12px', borderRadius: '8px', border: 'none',
          background: newTask.trim() ? 'var(--accent)' : 'rgba(255,255,255,0.04)',
          color: newTask.trim() ? '#fff' : 'var(--text-faint)',
          cursor: 'pointer', fontSize: '12px', fontWeight: 600,
        }}>Add</button>
      </form>
    </${ResultCard}>
  `;
}

// ─── Email Card ─────────────────────────────────────
function EmailCard(props) {
  var emails = props.emails || [];
  var onDismiss = props.onDismiss;

  return html`
    <${ResultCard} title=${'Email' + (emails.length ? ' (' + emails.length + ')' : '')} icon="Mail" iconColor="rgba(251,191,36,0.7)" onDismiss=${onDismiss}>
      <div style=${{ maxHeight: '240px', overflowY: 'auto' }}>
        ${emails.map(function(e) {
          return html`
            <div class="email-item" key=${e.id || e.subject}>
              <div style=${{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div class="email-sender">${e.from || e.sender}</div>
                <div style=${{ fontSize: '10px', color: 'var(--text-faint)' }}>${e.time || ''}</div>
              </div>
              <div class="email-subject">${e.subject}</div>
              <div class="email-preview">${e.preview || e.snippet || ''}</div>
            </div>
          `;
        })}
        ${emails.length === 0 && html`
          <div style=${{ fontSize: '13px', color: 'var(--text-faint)', textAlign: 'center', padding: '12px 0' }}>No emails</div>
        `}
      </div>
    </${ResultCard}>
  `;
}

// ─── Music Card ─────────────────────────────────────
function MusicCard(props) {
  var track = props.track || {};
  var playing = props.playing || false;
  var onPlayPause = props.onPlayPause;
  var onPrev = props.onPrev;
  var onNext = props.onNext;
  var progress = props.progress || 0;
  var onDismiss = props.onDismiss;

  return html`
    <${ResultCard} title="Music" icon="Music" iconColor="rgba(52,211,153,0.7)" onDismiss=${onDismiss}>
      <div style=${{ display: 'flex', alignItems: 'center', gap: '14px', marginBottom: '12px' }}>
        <div style=${{
          width: '48px', height: '48px', borderRadius: '10px',
          background: 'linear-gradient(135deg, var(--accent), var(--cyan))',
          display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
        }}>
          <${Li} name="Music" size=${22} color="#fff" />
        </div>
        <div style=${{ minWidth: 0 }}>
          <div style=${{ fontSize: '14px', fontWeight: 600, color: 'var(--text)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>${track.title || 'No track'}</div>
          <div style=${{ fontSize: '12px', color: 'var(--text-dim)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>${track.artist || 'Unknown artist'}</div>
        </div>
      </div>
      <div class="music-progress" style=${{ marginBottom: '12px' }}>
        <div class="music-progress-fill" style=${{ width: progress + '%' }} />
      </div>
      <div class="music-controls">
        <button class="music-btn" onClick=${onPrev}><${Li} name="SkipBack" size=${16} /></button>
        <button class=${'music-btn' + (playing ? ' play' : '')} onClick=${onPlayPause}>
          ${playing
            ? html`<${Li} name="Pause" size=${20} color="#fff" />`
            : html`<${Li} name="Play" size=${20} color="#fff" />`
          }
        </button>
        <button class="music-btn" onClick=${onNext}><${Li} name="SkipForward" size=${16} /></button>
      </div>
    </${ResultCard}>
  `;
}

// ─── Clock Card ─────────────────────────────────────
function ClockCard(props) {
  var _time = useState(new Date());
  var time = _time[0], setTime = _time[1];

  useEffect(function() {
    var iv = setInterval(function() { setTime(new Date()); }, 1000);
    return function() { clearInterval(iv); };
  }, []);

  var hours = time.getHours();
  var mins = String(time.getMinutes()).padStart(2, '0');
  var secs = String(time.getSeconds()).padStart(2, '0');
  var ampm = hours >= 12 ? 'PM' : 'AM';
  var h12 = hours % 12 || 12;
  var dateStr = time.toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' });

  return html`
    <${ResultCard} title="Clock" icon="Clock" iconColor="rgba(108,92,231,0.7)" onDismiss=${props.onDismiss}>
      <div style=${{ textAlign: 'center', padding: '8px 0' }}>
        <div style=${{ fontFamily: 'Orbitron,sans-serif', fontSize: '36px', fontWeight: 700, color: '#fff', letterSpacing: '2px' }}>
          ${h12}:${mins}<span style=${{ fontSize: '18px', color: 'var(--text-dim)', fontWeight: 400 }}>:${secs}</span>
          <span style=${{ fontSize: '14px', color: 'var(--accent)', marginLeft: '8px' }}>${ampm}</span>
        </div>
        <div style=${{ fontSize: '13px', color: 'var(--text-dim)', marginTop: '6px' }}>${dateStr}</div>
      </div>
    </${ResultCard}>
  `;
}

// ─── Notes Card ─────────────────────────────────────
function NotesCard(props) {
  var notes = props.notes || '';
  var onChange = props.onChange;
  var onDismiss = props.onDismiss;

  return html`
    <${ResultCard} title="Notes" icon="FileText" iconColor="rgba(0,212,255,0.7)" onDismiss=${onDismiss}>
      <textarea value=${notes} onInput=${function(e) { onChange(e.target.value); }}
        placeholder="Write something..."
        style=${{
          width: '100%', height: '100px', background: 'rgba(0,0,0,0.3)',
          border: '1px solid var(--border)', borderRadius: '10px',
          color: 'var(--text)', fontSize: '13px', fontFamily: 'var(--font)',
          padding: '10px 12px', resize: 'none', outline: 'none', lineHeight: 1.6,
        }}
      />
    </${ResultCard}>
  `;
}

// ─── Status Card ────────────────────────────────────
function StatusCard(props) {
  var connected = props.connected;
  var msgCount = props.msgCount || 0;
  var onDismiss = props.onDismiss;

  return html`
    <${ResultCard} title="Status" icon="Activity" iconColor="rgba(52,211,153,0.7)" onDismiss=${onDismiss}>
      <div style=${{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '13px' }}>
        <div style=${{ display: 'flex', justifyContent: 'space-between' }}>
          <span style=${{ color: 'var(--text-dim)' }}>Backend</span>
          <span style=${{ color: connected ? 'var(--green)' : 'var(--red)', display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span style=${{ width: '6px', height: '6px', borderRadius: '50%', background: connected ? 'var(--green)' : 'var(--red)' }} />
            ${connected ? 'Connected' : 'Offline'}
          </span>
        </div>
        <div style=${{ display: 'flex', justifyContent: 'space-between' }}>
          <span style=${{ color: 'var(--text-dim)' }}>Messages</span>
          <span style=${{ color: 'var(--text)' }}>${msgCount}</span>
        </div>
      </div>
    </${ResultCard}>
  `;
}
