window.NALLY = window.NALLY || {};

NALLY.thinkPhrases = [
  "Processing your request...",
  "Analyzing input...",
  "Connecting to server...",
  "Retrieving data...",
  "Formulating response...",
  "Almost ready...",
];

NALLY.think = function(text) {
  var s = NALLY.state;
  var d = NALLY.dom;
  s.thinkTimers.forEach(clearTimeout);
  s.thinkTimers = [];
  if (text === null || text === undefined) {
    d.thoughtContent.textContent = '';
    d.thoughtWrap.classList.remove('visible');
    NALLY.orb.setState('idle');
    d.statusEl.textContent = '';
    d.statusEl.style.color = 'rgba(228,226,220,0.25)';
    return;
  }
  NALLY.orb.setState('thinking');
  d.statusEl.textContent = 'Thinking';
  d.statusEl.style.color = 'var(--iris-glow)';
  d.thoughtContent.textContent = '';
  d.thoughtWrap.classList.add('visible');
  var i = 0;
  var typeTimer = setInterval(function() {
    if (i < text.length) {
      d.thoughtContent.textContent += text[i];
      i++;
    } else {
      clearInterval(typeTimer);
    }
  }, 30);
  s.thinkTimers.push(typeTimer);
};

NALLY.speak = function(text) {
  var s = NALLY.state;
  var d = NALLY.dom;
  s.speakTimers.forEach(clearTimeout);
  s.speakTimers = [];

  var phrase = NALLY.thinkPhrases[Math.floor(Math.random() * NALLY.thinkPhrases.length)];
  NALLY.think(phrase);

  var thinkTime = 600 + Math.random() * 600;
  var t = setTimeout(function() {
    d.thoughtContent.textContent = '';
    d.thoughtWrap.classList.remove('visible');
    NALLY.orb.setState('speaking');
    d.statusEl.textContent = 'Speaking';
    d.statusEl.style.color = 'rgba(52,211,153,0.5)';

    var tokens = text.match(/[\w']+|[^\w\s]|\s+/g) || [];
    var delay = 0;

    for (var i = 0; i < tokens.length; i++) {
      var token = tokens[i];
      var isWord = /[\w']/.test(token);
      var isEmphasis = /[!?]/.test(token);
      var isPause = /[.,;:]/.test(token);
      var isSpace = /^\s+$/.test(token);

      if (isWord) {
        (function(w, d, emph) {
          var timer = setTimeout(function() {
            NALLY.orb.pulseWord(emph);
            if (emph) NALLY.orb.burstParticles(6, '#34D399');
          }, d);
          s.speakTimers.push(timer);
        })(token, delay, isEmphasis);
        delay += Math.max(120, token.length * 45);
      } else if (isEmphasis) {
        (function(d) {
          var timer = setTimeout(function() {
            NALLY.orb.pulseWord(true);
            NALLY.orb.burstParticles(10, '#34D399');
          }, d);
          s.speakTimers.push(timer);
        })(delay);
        delay += 300;
      } else if (isPause) {
        delay += 200;
      } else if (isSpace) {
        delay += 30;
      }
    }

    var doneTimer = setTimeout(function() {
      NALLY.orb.setState('idle');
      d.statusEl.textContent = '';
      d.statusEl.style.color = 'rgba(228,226,220,0.25)';
      d.thoughtContent.textContent = '';
      d.thoughtWrap.classList.remove('visible');
    }, delay + 200);
    s.speakTimers.push(doneTimer);
  }, thinkTime);
  s.speakTimers.push(t);
};
