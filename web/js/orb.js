// ─── Orb Component ──────────────────────────────────
// States: idle, listening, thinking, speaking
// activated: triggers breathe-to-life entrance animation with particles
var _orbIdCounter = 0;
function Orb(props) {
  var state = props.state || 'idle';
  var onClick = props.onClick;
  var size = props.size || 200;
  var activated = props.activated || false;
  var tiltRef = useRef(null);
  var orbId = useRef('orb-' + (_orbIdCounter++));
  var f1 = orbId.current + '-f1';
  var f2 = orbId.current + '-f2';
  var ft = orbId.current + '-ft';

  // Mouse-tracking tilt (1.5° max, disabled on touch)
  useEffect(function() {
    var el = tiltRef.current;
    if (!el || window.matchMedia('(pointer: coarse)').matches) return;
    function onMove(e) {
      var rect = el.getBoundingClientRect();
      var cx = rect.left + rect.width / 2;
      var cy = rect.top + rect.height / 2;
      var dx = (e.clientX - cx) / (rect.width / 2);
      var dy = (e.clientY - cy) / (rect.height / 2);
      var clampX = Math.max(-1, Math.min(1, dx));
      var clampY = Math.max(-1, Math.min(1, dy));
      el.style.transform = 'perspective(600px) rotateY(' + (clampX * 1.5) + 'deg) rotateX(' + (-clampY * 1.5) + 'deg)';
    }
    function onLeave() { el.style.transform = 'perspective(600px) rotateY(0deg) rotateX(0deg)'; }
    el.addEventListener('mousemove', onMove);
    el.addEventListener('mouseleave', onLeave);
    return function() {
      el.removeEventListener('mousemove', onMove);
      el.removeEventListener('mouseleave', onLeave);
    };
  }, []);

  var stateClass = 'orb-state-' + state;

  var glowColor;
  switch (state) {
    case 'listening': glowColor = 'rgba(62,207,184,0.15)'; break;
    case 'thinking': glowColor = 'rgba(255,255,255,0.12)'; break;
    case 'speaking': glowColor = 'rgba(52,211,153,0.15)'; break;
    default: glowColor = 'rgba(124,106,239,0.1)';
  }

  var glowSize = size * 1.5;

  var glowStyle = {
    position: 'absolute',
    width: glowSize + 'px',
    height: glowSize + 'px',
    borderRadius: '50%',
    background: glowColor,
    filter: 'blur(40px)',
    pointerEvents: 'none',
    transition: 'all 0.6s ease',
  };

  var orbFilter;
  switch (state) {
    case 'listening': orbFilter = 'drop-shadow(0 0 25px rgba(62,207,184,0.45))'; break;
    case 'thinking': orbFilter = 'drop-shadow(0 0 20px rgba(255,255,255,0.35))'; break;
    case 'speaking': orbFilter = 'drop-shadow(0 0 25px rgba(52,211,153,0.45))'; break;
    default: orbFilter = 'drop-shadow(0 0 15px rgba(124,106,239,0.25))';
  }

  var strokeColor;
  switch (state) {
    case 'listening': strokeColor = '#3ECFB8'; break;
    case 'thinking': strokeColor = '#ffffff'; break;
    case 'speaking': strokeColor = '#34D399'; break;
    default: strokeColor = '#7C6AEF';
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
        color: i % 3 === 0 ? '#3ECFB8' : i % 3 === 1 ? '#7C6AEF' : '#A78BFA',
        size: (2 + Math.random() * 4) + 'px',
      });
    }
  }

  // Ripple waves
  var ripples = activated ? [0, 1, 2] : [];

  return html`
    <div ref=${tiltRef} onClick=${onClick} style=${{
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
      transition: 'transform 0.15s ease-out',
      transformStyle: 'preserve-3d',
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
            <filter id=${f1} x="-20%" y="-20%" width="140%" height="140%">
              <feGaussianBlur stdDeviation="12" result="b"/>
              <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
            </filter>
            <filter id=${f2} x="-20%" y="-20%" width="140%" height="140%">
              <feGaussianBlur stdDeviation="4" result="b"/>
              <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
            </filter>
            <filter id=${ft} x="-50%" y="-50%" width="200%" height="200%">
              <feGaussianBlur stdDeviation="4" result="b"/>
              <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
            </filter>
          </defs>

          <circle cx="250" cy="250" r="140" fill="#7C6AEF" fillOpacity="0.03" />

          <circle cx="250" cy="250" r="150" fill="none"
            stroke=${strokeColor}
            strokeWidth="10" filter=${'url(#' + f1 + ')'}
            class="orb-ring-ccw" strokeDasharray="940 2"
            style=${{ transformOrigin: '250px 250px', transition: 'stroke 0.6s ease' }} />

          <circle cx="250" cy="250" r="125" fill="none"
            stroke=${reactStroke}
            strokeWidth="5" filter=${'url(#' + f2 + ')'}
            class="orb-reactor orb-ring-cw" strokeDasharray="780 5"
            style=${{ transformOrigin: '250px 250px', transition: 'stroke 0.6s ease' }} />

          <text x="250" y="262" textAnchor="middle"
            fill=${reactStroke}
            filter=${'url(#' + ft + ')'} class="orb-reactor"
            style=${{
              fontFamily: '"Space Grotesk",sans-serif',
              fontSize: '46px',
              fontWeight: 700,
              letterSpacing: '6px',
              textTransform: 'uppercase',
              userSelect: 'none',
              transformOrigin: '250px 250px',
              transition: 'fill 0.6s ease',
            }}>NALLY</text>

          <line x1="250" y1="100" x2="250" y2="116" stroke=${strokeColor} strokeWidth="2" opacity="0.6" style=${{ transition: 'stroke 0.6s ease' }} />
          <line x1="250" y1="384" x2="250" y2="400" stroke=${strokeColor} strokeWidth="2" opacity="0.6" style=${{ transition: 'stroke 0.6s ease' }} />
          <line x1="100" y1="250" x2="116" y2="250" stroke=${strokeColor} strokeWidth="2" opacity="0.6" style=${{ transition: 'stroke 0.6s ease' }} />
          <line x1="384" y1="250" x2="400" y2="250" stroke=${strokeColor} strokeWidth="2" opacity="0.6" style=${{ transition: 'stroke 0.6s ease' }} />
        </svg>
      </div>
    </div>
  `;
}
