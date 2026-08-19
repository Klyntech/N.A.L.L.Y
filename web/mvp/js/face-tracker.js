const FaceTracker = (() => {
  let faceLandmarker = null;
  let videoEl = null;
  let running = false;
  let onResults = null;
  let lastTime = -1;

  const BLEND_SHAPE_NAMES = [
    'browDownLeft', 'browDownRight', 'browInnerUp', 'browOuterUpLeft', 'browOuterUpRight',
    'cheekPuff', 'cheekSquintLeft', 'cheekSquintRight',
    'eyeBlinkLeft', 'eyeBlinkRight', 'eyeLookDownLeft', 'eyeLookDownRight',
    'eyeLookInLeft', 'eyeLookInRight', 'eyeLookOutLeft', 'eyeLookOutRight',
    'eyeLookUpLeft', 'eyeLookUpRight', 'eyeSquintLeft', 'eyeSquintRight',
    'eyeWideLeft', 'eyeWideRight',
    'jawForward', 'jawLeft', 'jawOpen', 'jawRight',
    'mouthClose', 'mouthDimpleLeft', 'mouthDimpleRight',
    'mouthFrownLeft', 'mouthFrownRight', 'mouthFunnel',
    'mouthLeft', 'mouthLowerDownLeft', 'mouthLowerDownRight',
    'mouthPressLeft', 'mouthPressRight', 'mouthPucker', 'mouthRight',
    'mouthRollLower', 'mouthRollUpper', 'mouthShrugLower', 'mouthShrugUpper',
    'mouthSmileLeft', 'mouthSmileRight', 'mouthStretchLeft', 'mouthStretchRight',
    'mouthUpperUpLeft', 'mouthUpperUpRight',
    'noseSneerLeft', 'noseSneerRight', 'tongueOut'
  ];

  async function init(callback) {
    onResults = callback;
    const { FaceLandmarker, FilesetResolver } = await import(
      'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.18/+esm'
    );
    const vision = await FilesetResolver.forVisionTasks(
      'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.18/wasm'
    );
    faceLandmarker = await FaceLandmarker.createFromOptions(vision, {
      baseOptions: {
        modelAssetPath: 'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task',
        delegate: 'GPU'
      },
      outputFaceBlendshapes: true,
      runningMode: 'VIDEO',
      numFaces: 1
    });
  }

  function start(videoElement) {
    if (!faceLandmarker) return;
    videoEl = videoElement;
    running = true;
    predictLoop();
  }

  function stop() {
    running = false;
  }

  function predictLoop() {
    if (!running || !videoEl) return;
    if (videoEl.readyState >= 2) {
      const now = performance.now();
      if (now !== lastTime) {
        lastTime = now;
        const results = faceLandmarker.detectForVideo(videoEl, now);
        if (onResults && results.faceBlendshapes && results.faceBlendshapes.length > 0) {
          const blendshapes = {};
          for (const shape of results.faceBlendshapes[0].categories) {
            blendshapes[shape.categoryName] = shape.score;
          }
          onResults(blendshapes, results.faceLandmarks);
        }
      }
    }
    requestAnimationFrame(predictLoop);
  }

  return { init, start, stop, BLEND_SHAPE_NAMES };
})();

window.FaceTracker = FaceTracker;
