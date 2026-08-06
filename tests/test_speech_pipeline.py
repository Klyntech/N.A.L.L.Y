"""Tests for the speech pipeline — sentence splitting, preprocessing, prosody."""

import pytest
from nally.voice.speech_pipeline import (
    split_into_sentences,
    preprocess_for_speech,
    check_sentence_boundary,
    detect_emotion,
    detect_user_sentiment,
    process_for_speech,
    process_for_speech_flat,
    SentenceStream,
    SpeechSegment,
    smooth_prosody,
    apply_voice_profile,
    VOICE_PROFILES,
    EMOTION_PROSODY,
)


# ════════════════════════════════════════════════════════════════
#  Sentence Boundary Detection
# ════════════════════════════════════════════════════════════════

class TestSentenceBoundary:
    def test_simple_period(self):
        assert check_sentence_boundary("Hello world.", 11) is True

    def test_abbreviation_dr(self):
        assert check_sentence_boundary("Hello Dr. Smith", 10) is False

    def test_abbreviation_mr(self):
        assert check_sentence_boundary("Mr. Smith said", 2) is False

    def test_question_mark(self):
        assert check_sentence_boundary("Hello?", 5) is True

    def test_exclamation(self):
        assert check_sentence_boundary("Hello!", 5) is True

    def test_decimal_number(self):
        assert check_sentence_boundary("The value is 3.5 kg", 17) is False

    def test_ellipsis(self):
        assert check_sentence_boundary("Wait\u2026", 4) is True


class TestSplitSentences:
    def test_simple(self):
        result = split_into_sentences("Hello world. How are you?")
        assert result == ["Hello world.", "How are you?"]

    def test_abbreviations(self):
        result = split_into_sentences("Dr. Smith went to the U.S.A. He was happy.")
        assert len(result) == 1
        assert "Dr. Smith" in result[0]
        assert "U.S.A." in result[0]

    def test_empty(self):
        assert split_into_sentences("") == []
        assert split_into_sentences("   ") == []

    def test_paragraph_break(self):
        result = split_into_sentences("First paragraph.\n\nSecond paragraph.")
        assert len(result) == 2

    def test_question_and_exclamation(self):
        result = split_into_sentences("Hello? Yes! OK.")
        assert len(result) == 3


# ════════════════════════════════════════════════════════════════
#  Text Preprocessing
# ════════════════════════════════════════════════════════════════

class TestPreprocessForSpeech:
    def test_url_normalization(self):
        result = preprocess_for_speech("Visit https://example.com/path")
        assert "example dot com" in result

    def test_email_normalization(self):
        result = preprocess_for_speech("Email test@example.com")
        assert "test at example dot com" in result

    def test_percentage(self):
        result = preprocess_for_speech("90% complete")
        assert "90 percent" in result

    def test_code_block_removal(self):
        result = preprocess_for_speech("```python\nprint('hi')\n```")
        assert "print" not in result

    def test_inline_code_removal(self):
        result = preprocess_for_speech("Use `pip install`")
        assert "`" not in result

    def test_bold_removal(self):
        result = preprocess_for_speech("**Important**")
        assert "**" not in result

    def test_empty(self):
        assert preprocess_for_speech("") == ""
        assert preprocess_for_speech(None) == ""


# ════════════════════════════════════════════════════════════════
#  Emotion Detection
# ════════════════════════════════════════════════════════════════

class TestEmotionDetection:
    def test_urgent(self):
        assert detect_emotion("Warning! This is critical.") == "urgent"

    def test_empathetic(self):
        assert detect_emotion("I'm sorry, that's unfortunate.") == "empathetic"

    def test_curious(self):
        assert detect_emotion("How does this work?") == "curious"

    def test_confident(self):
        assert detect_emotion("Confirmed, the answer is 42.") == "confident"

    def test_informative(self):
        assert detect_emotion("The cost is 50 million dollars.") == "informative"

    def test_neutral(self):
        assert detect_emotion("The file was created.") == "neutral"


class TestUserSentiment:
    def test_urgent(self):
        assert detect_user_sentiment("Help! I need this now!") == "urgent"

    def test_empathetic(self):
        assert detect_user_sentiment("I'm worried about this.") == "empathetic"

    def test_curious(self):
        assert detect_user_sentiment("How does this work?") == "curious"


# ════════════════════════════════════════════════════════════════
#  Voice Profiles & Prosody
# ════════════════════════════════════════════════════════════════

class TestVoiceProfiles:
    def test_all_profiles_exist(self):
        assert "nally" in VOICE_PROFILES
        assert "narrator" in VOICE_PROFILES
        assert "concise" in VOICE_PROFILES
        assert "warm" in VOICE_PROFILES

    def test_apply_profile(self):
        segments = [SpeechSegment(text="Hello", rate=1.0, pitch=1.0, volume=1.0)]
        result = apply_voice_profile(segments, "nally")
        assert result[0].rate < 1.0  # nally is slower

    def test_smooth_prosody(self):
        segments = [
            SpeechSegment(text="First", rate=1.2, pitch=1.0, volume=1.0),
            SpeechSegment(text="Second", rate=0.8, pitch=1.0, volume=1.0),
        ]
        result = smooth_prosody(segments)
        # Second segment should be smoothed toward first
        assert result[1].rate > 0.8
        assert result[1].rate < 1.2


# ════════════════════════════════════════════════════════════════
#  Full Pipeline
# ════════════════════════════════════════════════════════════════

class TestFullPipeline:
    def test_process_for_speech(self):
        result = process_for_speech("Hello Dr. Smith. Check https://example.com!")
        assert len(result) >= 1
        assert all(isinstance(s, SpeechSegment) for s in result)

    def test_process_for_speech_flat(self):
        result = process_for_speech_flat("Hello Dr. Smith. Check https://example.com!")
        assert len(result) >= 1
        assert all(isinstance(s, str) for s in result)


# ════════════════════════════════════════════════════════════════
#  Streaming Sentence Detector
# ════════════════════════════════════════════════════════════════

class TestSentenceStream:
    def test_feed_partial(self):
        stream = SentenceStream()
        result = stream.feed("Hello ")
        assert result == []

    def test_feed_complete_sentence(self):
        stream = SentenceStream()
        result = stream.feed("Hello world. ")
        assert result == ["Hello world."]

    def test_flush(self):
        stream = SentenceStream()
        stream.feed("Hello world")
        result = stream.flush()
        assert result == "Hello world"
