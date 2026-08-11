window.NALLY = window.NALLY || {};

NALLY.toggleRecording = function() {
  if (NALLY.state.isRecording) {
    NALLY.stopRecording();
  } else {
    NALLY.startRecording();
  }
};

NALLY.startRecording = function() {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    console.error('[mic] getUserMedia not available');
    NALLY.addChatMsg('Voice not supported. Check browser permissions and ensure you are on localhost or HTTPS.', true);
    return;
  }

  navigator.mediaDevices.getUserMedia({ audio: true }).then(function(stream) {
    NALLY.state.micStream = stream;
    NALLY.state.audioChunks = [];
    var mimeType = 'audio/webm;codecs=opus';
    if (!MediaRecorder.isTypeSupported(mimeType)) mimeType = 'audio/webm';
    if (!MediaRecorder.isTypeSupported(mimeType)) mimeType = 'audio/ogg;codecs=opus';

    NALLY.state.mediaRecorder = new MediaRecorder(stream, { mimeType: mimeType });
    NALLY.state.mediaRecorder.ondataavailable = function(e) {
      if (e.data.size > 0) NALLY.state.audioChunks.push(e.data);
    };
    NALLY.state.mediaRecorder.onstop = function() {
      var blob = new Blob(NALLY.state.audioChunks, { type: mimeType });
      NALLY.sendAudioBlob(blob);
      NALLY._cleanupMic();
    };

    NALLY.state.mediaRecorder.start();
    NALLY.state.isRecording = true;
    var micBtn = document.getElementById('mic-btn');
    micBtn.classList.add('recording');
    micBtn.title = 'Click to stop recording';
  }).catch(function(err) {
    console.error('[mic] access denied:', err.name, err.message, err);
    if (err.name === 'NotAllowedError') {
      NALLY.addChatMsg('Microphone blocked by browser. Click the lock/tune icon in the address bar and allow microphone, or check chrome://settings/content/microphone', true);
    } else if (err.name === 'NotFoundError') {
      NALLY.addChatMsg('No microphone found. Plug in a mic and try again.', true);
    } else {
      NALLY.addChatMsg('Mic error: ' + err.name + ' — ' + err.message, true);
    }
  });
};

NALLY.stopRecording = function() {
  if (NALLY.state.mediaRecorder && NALLY.state.mediaRecorder.state !== 'inactive') {
    NALLY.state.mediaRecorder.stop();
  }
  NALLY.state.isRecording = false;
  var micBtn = document.getElementById('mic-btn');
  micBtn.classList.remove('recording');
  micBtn.title = 'Toggle voice input';
};

NALLY._cleanupMic = function() {
  if (NALLY.state.micStream) {
    NALLY.state.micStream.getTracks().forEach(function(t) { t.stop(); });
    NALLY.state.micStream = null;
  }
  NALLY.state.mediaRecorder = null;
  NALLY.state.audioChunks = [];
};

NALLY.sendAudioBlob = function(blob) {
  if (!blob || blob.size < 100) return;

  var reader = new FileReader();
  reader.onloadend = function() {
    var arrayBuffer = reader.result;
    var audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    audioCtx.decodeAudioData(arrayBuffer, function(decoded) {
      var src = decoded;
      var targetRate = 16000;
      var offCtx = new OfflineAudioContext(1, Math.ceil(src.duration * targetRate), targetRate);
      var srcNode = offCtx.createBufferSource();
      srcNode.buffer = src;
      srcNode.connect(offCtx.destination);
      srcNode.start(0);
      offCtx.startRendering().then(function(resampled) {
        var channelData = resampled.getChannelData(0);
        var int16 = new Int16Array(channelData.length);
        for (var i = 0; i < channelData.length; i++) {
          var s = Math.max(-1, Math.min(1, channelData[i]));
          int16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
        }
        var bytes = new Uint8Array(int16.buffer);
        var binary = '';
        for (var i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
        var b64 = btoa(binary);
        if (NALLY.state.useWebSocket && NALLY.state.ws && NALLY.state.ws.connected) {
          NALLY.state.ws.sendAudio(b64, NALLY.state.tabId, 'pcm_s16le');
        }
        audioCtx.close();
      });
    }, function(e) {
      console.warn('[mic] decode failed, sending raw:', e);
      var rawReader = new FileReader();
      rawReader.onloadend = function() {
        var base64 = rawReader.result.split(',')[1];
        if (NALLY.state.useWebSocket && NALLY.state.ws && NALLY.state.ws.connected) {
          NALLY.state.ws.sendAudio(base64, NALLY.state.tabId);
        }
      };
      rawReader.readAsDataURL(blob);
    });
  };
  reader.readAsArrayBuffer(blob);
};
