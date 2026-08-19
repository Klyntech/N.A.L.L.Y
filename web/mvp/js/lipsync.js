const LipSync = (() => {
  let audioCtx = null;
  let analyser = null;
  let source = null;
  let dataArray = null;
  let running = false;

  const VISEME_MAP = {
    aa: { jawOpen: 0.7, mouthOpen: 0.5 },
    OO: { mouthPucker: 0.8, jawOpen: 0.2 },
    E:  { mouthSmileLeft: 0.5, mouthSmileRight: 0.5, jawOpen: 0.25 },
    oh: { mouthFunnel: 0.7, jawOpen: 0.3 },
    u:  { mouthPucker: 0.6, mouthFunnel: 0.4 },
    PP: { mouthRollLower: 0.6, mouthRollUpper: 0.6, mouthClose: 0.8 },
    FF: { mouthShrugUpper: 0.8, mouthPucker: 0.6, mouthRollLower: 0.5 },
    TH: { tongueOut: 0.4, jawOpen: 0.2 },
    DD: { mouthPressLeft: 0.5, mouthPressRight: 0.5, jawOpen: 0.15 },
    SS: { mouthPressLeft: 0.6, mouthPressRight: 0.6, mouthLowerDownLeft: 0.3, mouthLowerDownRight: 0.3 },
    CH: { mouthPucker: 0.4, jawOpen: 0.15 },
    kk: { mouthLowerDownLeft: 0.3, mouthLowerDownRight: 0.3, mouthFunnel: 0.2 },
    nn: { mouthLowerDownLeft: 0.3, mouthLowerDownRight: 0.3, tongueOut: 0.15 },
    RR: { mouthPucker: 0.35, jawOpen: 0.15 },
    sil: {}
  };

  function init() {
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    analyser = audioCtx.createAnalyser();
    analyser.fftSize = 2048;
    analyser.smoothingTimeConstant = 0.5;
    dataArray = new Float32Array(analyser.fftSize);
  }

  async function startFromMic() {
    if (!audioCtx) init();
    if (audioCtx.state === 'suspended') await audioCtx.resume();
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    source = audioCtx.createMediaStreamSource(stream);
    source.connect(analyser);
    running = true;
  }

  function startFromElement(audioElement) {
    if (!audioCtx) init();
    if (audioCtx.state === 'suspended') audioCtx.resume();
    source = audioCtx.createMediaElementSource(audioElement);
    source.connect(analyser);
    analyser.connect(audioCtx.destination);
    running = true;
  }

  function stop() {
    running = false;
    if (source) {
      try { source.disconnect(); } catch(e) {}
    }
  }

  function analyze() {
    if (!running || !analyser) return { weights: {}, volume: 0 };
    analyser.getFloatTimeDomainData(dataArray);

    let sum = 0;
    for (let i = 0; i < dataArray.length; i++) sum += dataArray[i] * dataArray[i];
    const rms = Math.sqrt(sum / dataArray.length);
    const volume = Math.min(rms * 4, 1.0);

    const freqData = new Float32Array(analyser.frequencyBinCount);
    analyser.getFloatFrequencyData(freqData);

    const bands = getFrequencyBands(freqData);
    const viseme = classifyViseme(bands, volume);
    const weights = VISEME_MAP[viseme] || {};

    return { weights, volume, viseme };
  }

  function getFrequencyBands(freqData) {
    const sampleRate = audioCtx.sampleRate;
    const binSize = sampleRate / analyser.fftSize;

    function bandPower(low, high) {
      const lowBin = Math.floor(low / binSize);
      const highBin = Math.ceil(high / binSize);
      let sum = 0, count = 0;
      for (let i = lowBin; i <= highBin && i < freqData.length; i++) {
        sum += Math.pow(10, freqData[i] / 20);
        count++;
      }
      return count > 0 ? sum / count : 0;
    }

    return {
      low: bandPower(80, 250),
      mid: bandPower(250, 500),
      highMid: bandPower(500, 1500),
      high: bandPower(1500, 4000),
      veryHigh: bandPower(4000, 8000)
    };
  }

  function classifyViseme(bands, volume) {
    if (volume < 0.02) return 'sil';

    const { low, mid, highMid, high, veryHigh } = bands;
    const total = low + mid + highMid + high + veryHigh + 0.001;

    const lowRatio = low / total;
    const highRatio = (high + veryHigh) / total;

    if (lowRatio > 0.5 && volume > 0.3) return 'aa';
    if (highRatio > 0.4) return 'SS';
    if (lowRatio > 0.4 && volume > 0.2) return 'oh';
    if (mid > highMid && volume > 0.15) return 'E';
    if (highMid > mid && volume > 0.1) return 'FF';
    if (lowRatio < 0.2 && volume < 0.15) return 'PP';
    if (volume > 0.2) return 'aa';
    return 'sil';
  }

  return { init, startFromMic, startFromElement, stop, analyze };
})();

window.LipSync = LipSync;
