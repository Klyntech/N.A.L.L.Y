// ─── Orb Component ──────────────────────────────────
// States: idle, listening, thinking, speaking
// activated: triggers breathe-to-life entrance animation with particles
function Orb(props) {
  var state = props.state || 'idle';
  var onClick = props.onClick;
  var size = props.size || 200;
  var activated = props.activated || false;

  var stateClass = 'orb-state-' + state;

  var glowColor;
  switch (state) {
    case 'listening': glowColor = 'rgba(0,212,255,0.18)'; break;
    case 'thinking': glowColor = 'rgba(255,255,255,0.15)'; break;
    case 'speaking': glowColor = 'rgba(52,211,153,0.18)'; break;
    default: glowColor = 'rgba(108,92,231,0.12)';
  }

  var glowSize = size * 1.5;

  var glowStyle = {
    position: 'absolute',
    width: glowSize + 'px',
    height: glowSize + 'px',
    borderRadius: '50%',
    background: glowColor,
    filter: 'blur(50px)',
    pointerEvents: 'none',
    transition: 'all 0.6s ease',
  };

  var orbFilter;
  switch (state) {
    case 'listening': orbFilter = 'drop-shadow(0 0 30px rgba(0,212,255,0.5))'; break;
    case 'thinking': orbFilter = 'drop-shadow(0 0 25px rgba(255,255,255,0.4))'; break;
    case 'speaking': orbFilter = 'drop-shadow(0 0 30px rgba(52,211,153,0.5))'; break;
    default: orbFilter = 'drop-shadow(0 0 20px rgba(108,92,231,0.3))';
  }

  var strokeColor;
  switch (state) {
    case 'listening': strokeColor = '#00D4FF'; break;
    case 'thinking': strokeColor = '#ffffff'; break;
    case 'speaking': strokeColor = '#34D399'; break;
    default: strokeColor = '#6C5CE7';
  }

  var reactStroke = state === 'idle' ? '#ffffff' : strokeColor;

  // Generate particles for activation
  var particles = [];
  if (activated) {
    for (var i = 0; i < 16; i++) {
      var angle = (i / 16) * Math.PI * 2;
      var dist = 60 + Math.random() * 80;
      particles.push({
        id: i,
        px: Math.cos(angle) * dist + 'px',
        py: Math.sin(angle) * dist + 'px',
        delay: (Math.random() * 0.3) + 's',
        color: i % 3 === 0 ? '#00D4FF' : i % 3 === 1 ? '#6C5CE7' : '#A78BFA',
        size: (2 + Math.random() * 4) + 'px',
      });
    }
  }

  // Ripple waves
  var ripples = activated ? [0, 1, 2] : [];

  return html`
    <div onClick=${onClick} style=${{
      position: 'relative',
      width: size + 'px',
      height: size + 'px',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      cursor: 'pointer',
      userSelect: 'none',
      zIndex: 10,
      flexShrink: 0,
    }}>
      <div class=${stateClass + (activated ? ' orb-breathe' : '')} style=${{
        position: 'relative',
        width: '100%',
        height: '100%',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        opacity: activated ? undefined : 1,
      }}>
        <div class="orb-ambient" style=${glowStyle} />

        ${ripples.map(function(delay) {
          return html`<div key=${'r' + delay} class="ripple" style=${{ animationDelay: (delay * 0.35) + 's' }} />`;
        })}

        ${particles.map(function(p) {
          return html`<div key=${'p' + p.id} class="particle" style=${{
            '--px': p.px,
            '--py': p.py,
            animationDelay: p.delay,
            width: p.size,
            height: p.size,
            background: p.color,
            boxShadow: '0 0 6px ' + p.color,
          }} />`;
        })}

        <svg viewBox="0 0 500 500" style=${{
          width: '100%',
          height: '100%',
          filter: orbFilter,
          transition: 'filter 0.6s ease',
        }}>
          <defs>
            <filter id="og1" x="-20%" y="-20%" width="140%" height="140%">
              <feGaussianBlur stdDeviation="12" result="b"/>
              <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
            </filter>
            <filter id="og2" x="-20%" y="-20%" width="140%" height="140%">
              <feGaussianBlur stdDeviation="4" result="b"/>
              <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
            </filter>
            <filter id="otg" x="-50%" y="-50%" width="200%" height="200%">
              <feGaussianBlur stdDeviation="4" result="b"/>
              <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
            </filter>
          </defs>

          <circle cx="250" cy="250" r="140" fill="#6C5CE7" fillOpacity="0.04" />

          <circle cx="250" cy="250" r="150" fill="none"
            stroke=${strokeColor}
            strokeWidth="10" filter="url(#og1)"
            class="orb-ring-ccw" strokeDasharray="940 2"
            style=${{ transformOrigin: '250px 250px', transition: 'stroke 0.6s ease' }} />

          <circle cx="250" cy="250" r="125" fill="none"
            stroke=${reactStroke}
            strokeWidth="5" filter="url(#og2)"
            class="orb-reactor orb-ring-cw" strokeDasharray="780 5"
            style=${{ transformOrigin: '250px 250px', transition: 'stroke 0.6s ease' }} />

          <text x="250" y="262" textAnchor="middle"
            fill=${reactStroke}
            filter="url(#otg)" class="orb-reactor"
            style=${{
              fontFamily: 'Orbitron,sans-serif',
              fontSize: '46px',
              fontWeight: 700,
              letterSpacing: '6px',
              textTransform: 'uppercase',
              userSelect: 'none',
              transformOrigin: '250px 250px',
              transition: 'fill 0.6s ease',
            }}>NALLY</text>

          <span style=${{ position: 'absolute', top: 0, left: '50%', transform: 'translateX(-50%)', width: '16px', height: '2px', background: strokeColor, borderRadius: '2px', opacity: 0.6, transition: 'background 0.6s ease' }} />
          <span style=${{ position: 'absolute', bottom: 0, left: '50%', transform: 'translateX(-50%)', width: '16px', height: '2px', background: strokeColor, borderRadius: '2px', opacity: 0.6, transition: 'background 0.6s ease' }} />
          <span style=${{ position: 'absolute', left: 0, top: '50%', transform: 'translateY(-50%)', width: '2px', height: '16px', background: strokeColor, borderRadius: '2px', opacity: 0.6, transition: 'background 0.6s ease' }} />
          <span style=${{ position: 'absolute', right: 0, top: '50%', transform: 'translateY(-50%)', width: '2px', height: '16px', background: strokeColor, borderRadius: '2px', opacity: 0.6, transition: 'background 0.6s ease' }} />
        </svg>
      </div>
    </div>
  `;
}
