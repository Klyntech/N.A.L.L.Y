"""Tests for the streaming voice pipeline, STT, TTS, barge-in, and metrics.

Run: pytest tests/test_voice_pipeline.py
"""

import asyncio
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from nally.voice.bargein import BargeInDetector, has_content_word
from nally.voice.metrics import init_telemetry, reset_telemetry
from nally.voice.pipeline import VoicePipeline, resample_pcm


# ── Barge-in ──


def test_has_content_word_basic():
    assert has_content_word("Please stop the music") is True
    assert has_content_word("uh") is False
    assert has_content_word("ok okay yeah") is False  # only fillers
    assert has_content_word("") is False


def test_bargein_requires_grace_period():
    det = BargeInDetector(grace_ms=200, vad_threshold=0.5)
    det.set_agent_speaking(True)

    # VAD onset now.
    det.on_vad(0.9)
    # Content word arrives immediately (within grace) -> not yet confirmed.
    assert det.on_partial("stop talking now") is False

    # Simulate time passing past grace period.
    det._grace_end_time = 0.0  # force grace elapsed
    assert det.on_partial("stop talking now") is True


def test_bargein_filler_does_not_confirm():
    det = BargeInDetector(grace_ms=0, vad_threshold=0.5)
    det.set_agent_speaking(True)
    det.on_vad(0.9)
    det._grace_end_time = 0.0
    # Only a backchannel -> no confirmation even after grace.
    assert det.on_partial("uh hmm okay") is False


def test_bargein_confirm_metrics():
    reset_telemetry()
    reader = init_telemetry_for_test()
    det = BargeInDetector(grace_ms=0)
    det.set_agent_speaking(True)
    det.on_vad(0.95)
    det._grace_end_time = 0.0
    assert det.on_partial("what time is it") is True
    det.confirm_interrupt()
    data = reader.get_metrics_data()
    names = [m.name for m in _summaries(data)]
    assert "bargein_events_total" in names


# ── metrics helper ──


def init_telemetry_for_test():
    """Init telemetry with an in-memory reader so tests can assert metrics."""
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader

    reset_telemetry()
    reader = InMemoryMetricReader()
    init_telemetry(
        service_name="nally-voice-test",
        metrics_port=0,
        metric_reader=reader,
        force=True,
    )
    return reader


def _summaries(data):
    out = []
    if data is None:
        return out
    for resource_metrics in data.resource_metrics:
        for scope_metrics in resource_metrics.scope_metrics:
            for metric in scope_metrics.metrics:
                out.append(metric)
    return out


# ── Deepgram streaming STT (mocked) ──


class FakeDeepgramSocket:
    def __init__(self):
        self.sent = []
        self.closed = False
        self._recv_queue = asyncio.Queue()

    def send_media(self, data: bytes):
        self.sent.append(data)

    async def recv(self):
        return await self._recv_queue.get()

    def send_close_stream(self):
        self.closed = True

    async def feed_result(self, transcript: str, is_final: bool = True):
        # Minimal fake Deepgram Results-style object.
        class Alt:
            transcript = transcript

        class Channel:
            alternatives = [Alt()]

        class Msg:
            type = "Results"
            is_final = is_final
            speech_final = is_final
            channel = Channel()

        await self._recv_queue.put(Msg())


class FakeDeepgramSTT:
    """Duck-typed stand-in for DeepgramStreamingSTT that records audio."""

    def __init__(self, *a, **k):
        self.connected = False
        self.sent = []
        self._final_q = asyncio.Queue()
        self._partial_q = asyncio.Queue()
        self._recv_task = None
        self._socket = FakeDeepgramSocket()

    async def connect(self):
        self.connected = True
        return True

    async def send_audio(self, data):
        self.sent.append(data)
        # Simulate the recv loop surfacing a final transcript.
        await self._final_q.put("hello there")

    async def get_final_transcript(self, timeout=None):
        try:
            if timeout is None:
                return await self._final_q.get()
            return await asyncio.wait_for(self._final_q.get(), timeout)
        except asyncio.TimeoutError:
            return None

    async def get_partial_transcript(self, timeout=0.05):
        try:
            return await asyncio.wait_for(self._partial_q.get(), timeout)
        except (asyncio.TimeoutError, asyncio.QueueEmpty):
            return None

    async def close(self):
        self.connected = False


# ── Fish Audio TTS (mocked) ──


class FakeFishTTS:
    """Stand-in exposing synthesize_stream_pcm yielding raw 48k PCM."""

    def __init__(self):
        self.calls = []

    async def synthesize_stream_pcm(self, text, target_sample_rate=48000):
        self.calls.append((text, target_sample_rate))
        # 0.1s of sine wave @ target_sample_rate as int16 PCM.
        n = int(target_sample_rate * 0.1)
        t = np.linspace(0, 1, n)
        pcm = (np.sin(2 * np.pi * 440 * t) * 32767 * 0.3).astype(np.int16)
        # Yield in two chunks to exercise the streaming path.
        yield pcm[: n // 2].tobytes()
        yield pcm[n // 2 :].tobytes()


# ── Pipeline integration ──


def test_resample_pcm_noop_same_rate():
    pcm = np.ones(100, dtype=np.int16).tobytes()
    assert resample_pcm(pcm, 48000, 48000) == pcm


def test_resample_pcm_changes_length():
    pcm = np.ones(16000, dtype=np.int16).tobytes()  # ~1s @16k
    out = resample_pcm(pcm, 16000, 48000)
    assert len(out) == 16000 * 3 * 2  # 48000 samples * 2 bytes


def test_voice_pipeline_produces_output_frames():
    async def _run():
        # Reinit telemetry with in-memory reader for assertion.
        reader = init_telemetry_for_test()

        stt = FakeDeepgramSTT()
        tts = FakeFishTTS()

        responses = []

        async def on_transcript(text):
            responses.append(text)
            yield f"reply to: {text}"

        pipe = VoicePipeline(
            stt=stt,
            tts=tts,
            sample_rate=48000,
            stt_sample_rate=16000,
            on_transcript=on_transcript,
        )
        await pipe.start()

        # Feed a couple of inbound frames (48k PCM). resample -> 16k -> send_audio.
        frame = np.zeros(480, dtype=np.int16).tobytes()
        pipe.feed_audio(frame)
        pipe.feed_audio(frame)

        # Let the pipeline process.
        produced = b""
        for _ in range(200):
            f = pipe.get_output_frame()
            if f:
                produced += f
            await asyncio.sleep(0.01)
            if produced and responses:
                break

        await pipe.stop()
        return reader, stt, tts, responses, produced

    reader, stt, tts, responses, produced = asyncio.run(_run())

    assert stt.connected is False
    assert len(responses) >= 1
    assert responses[0] == "hello there"
    # The agent reply was synthesized by TTS (overlapped streaming).
    synth_texts = [c[0] for c in tts.calls]
    assert "reply to: hello there" in synth_texts
    # Outbound audio was produced from the TTS stream.
    assert len(produced) > 0
    # TTS latency + pipeline latency metrics were recorded.
    names = [m.name for m in _summaries(reader.get_metrics_data())]
    assert "tts_latency_seconds" in names
    assert "pipeline_end_to_end_seconds" in names


def test_voice_pipeline_bargein_cancels_tts():
    async def _run():
        reader = init_telemetry_for_test()
        stt = FakeDeepgramSTT()
        tts = FakeFishTTS()
        barge_events = []

        pipe = VoicePipeline(
            stt=stt,
            tts=tts,
            on_bargein=lambda m: barge_events.append(m),
        )
        await pipe.start()

        # Simulate agent speaking.
        pipe.bargein.set_agent_speaking(True)
        pipe.bargein.on_vad(0.95)
        pipe.bargein._grace_end_time = 0.0
        # A content-word partial arrives -> barge-in confirmed.
        await stt._partial_q.put("hey stop that")
        await asyncio.sleep(0.2)

        await pipe.stop()
        return reader, barge_events

    reader, barge_events = asyncio.run(_run())
    assert len(barge_events) >= 1
    names = [m.name for m in _summaries(reader.get_metrics_data())]
    assert "bargein_events_total" in names
