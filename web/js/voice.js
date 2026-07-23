// ─── Voice Input (Web Speech API) ───────────────────
function useVoiceInput(onResult, onEnd) {
  var recognizing = useRef(false);
  var recognition = useRef(null);
  var _listening = useState(false);
  var listening = _listening[0], setListening = _listening[1];
  var _transcript = useState('');
  var transcript = _transcript[0], setTranscript = _transcript[1];
  var _keywordMode = useState(false);
  var keywordMode = _keywordMode[0], setKeywordMode = _keywordMode[1];
  var keywordCallback = useRef(null);

  useEffect(function() {
    var SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) return;

    var rec = new SpeechRecognition();
    rec.continuous = true;
    rec.interimResults = true;
    rec.lang = 'en-US';

    rec.onresult = function(event) {
      var final = '';
      var interim = '';
      for (var i = event.resultIndex; i < event.results.length; i++) {
        var t = event.results[i][0].transcript;
        if (event.results[i].isFinal) {
          final += t;
        } else {
          interim += t;
        }
      }

      // Check for "hey nally" keyword in final or interim
      var combined = (final + ' ' + interim).toLowerCase();
      if (combined.match(/\b(hey\s*nally|hey\s*nali|hey\s*nal)\b/)) {
        // Keyword detected — strip it and fire callback
        var cleaned = final.replace(/hey\s*nally/gi, '').trim();
        if (keywordCallback.current) {
          keywordCallback.current(cleaned || null);
        }
        return;
      }

      if (final) {
        setTranscript('');
        if (onResult) onResult(final.trim());
      } else {
        setTranscript(interim);
      }
    };

    rec.onend = function() {
      recognizing.current = false;
      setListening(false);
      setTranscript('');
      if (onEnd) onEnd();
    };

    rec.onerror = function(e) {
      if (e.error === 'no-speech' || e.error === 'aborted') return;
      console.error('[NALLY] Speech error:', e.error);
      recognizing.current = false;
      setListening(false);
      setTranscript('');
    };

    recognition.current = rec;

    return function() {
      if (recognition.current) {
        try { recognition.current.stop(); } catch(e) {}
      }
    };
  }, []);

  function start() {
    if (!recognition.current) return;
    if (recognizing.current) return;
    try {
      recognition.current.start();
      recognizing.current = true;
      setListening(true);
    } catch(e) {}
  }

  function stop() {
    if (!recognition.current) return;
    try {
      recognition.current.stop();
      recognizing.current = false;
      setListening(false);
      setTranscript('');
    } catch(e) {}
  }

  function toggle() {
    if (listening) stop();
    else start();
  }

  // Background keyword detection — listens passively for "Hey Nally"
  function startKeywordDetection(callback) {
    keywordCallback.current = callback;
    setKeywordMode(true);
    start();
  }

  function stopKeywordDetection() {
    keywordCallback.current = null;
    setKeywordMode(false);
    stop();
  }

  var supported = !!(window.SpeechRecognition || window.webkitSpeechRecognition);

  return {
    start: start,
    stop: stop,
    toggle: toggle,
    listening: listening,
    transcript: transcript,
    supported: supported,
    keywordMode: keywordMode,
    startKeywordDetection: startKeywordDetection,
    stopKeywordDetection: stopKeywordDetection,
  };
}
