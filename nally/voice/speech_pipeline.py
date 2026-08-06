"""Speech Pipeline — Text preprocessing, sentence splitting, prosody, and emotion detection.

Inspired by Jarvis (Iron Man) and KlynJarvis voice engine.
Converts written text into natural spoken form with proper pronunciation,
sentence boundaries, and emotional prosody.

Usage:
    from nally.voice.speech_pipeline import split_into_sentences, preprocess_for_speech
    from nally.voice.speech_pipeline import detect_emotion, smooth_prosody, apply_voice_profile
"""

import re
from dataclasses import dataclass

# ════════════════════════════════════════════════════════════════
#  Pronunciation Dictionary — Tech, Finance, Common Symbols
# ════════════════════════════════════════════════════════════════

PRONUNCIATION_MAP: dict[str, str] = {
    # Tech abbreviations — spell out for clarity
    "AI": "A.I.",
    "API": "A.P.I.",
    "GPT": "G.P.T.",
    "LLM": "L.L.M.",
    "URL": "U.R.L.",
    "HTTP": "H.T.T.P.",
    "HTML": "H.T.M.L.",
    "CSS": "C.S.S.",
    "GPU": "G.P.U.",
    "CPU": "C.P.U.",
    "iOS": "i.O.S.",
    "STT": "S.T.T.",
    "TTS": "T.T.S.",
    "MCP": "M.C.P.",
    "NLP": "N.L.P.",
    "VPN": "V.P.N.",
    "SSH": "S.S.H.",
    "SQL": "S.Q.L.",
    "UI": "U.I.",
    "UX": "U.X.",
    "AR": "A.R.",
    "VR": "V.R.",
    "MR": "M.R.",
    "XR": "X.R.",
    "RAG": "R.A.G.",
    "VAD": "V.A.D.",
    "ASR": "A.S.R.",
    "NLU": "N.L.U.",
    "SOTA": "S.O.T.A.",
    "ROI": "R.O.I.",
    "KPI": "K.P.I.",
    "CRUD": "C.R.U.D.",
    "REST": "R.E.S.T.",
    "WebSocket": "Web Socket",
    "WebRTC": "Web R.T.C.",
    "OpenAI": "Open A.I.",
    "ChatGPT": "Chat G.P.T.",
    "GitHub": "Git Hub",
    "StackOverflow": "Stack Overflow",
    "YouTube": "You Tube",
    "LinkedIn": "Linked In",
    "TypeScript": "Type Script",
    "JavaScript": "Java Script",
    "NodeJS": "Node J.S.",
    "NextJS": "Next J.S.",
    "ReactJS": "React J.S.",
    "Python": "Pie-thon",
    "Docker": "Docker",
    "Kubernetes": "Koo-ber-NET-eez",
    "Linux": "Lin-ux",
    "MacOS": "Mac O.S.",
    "Windows": "Windows",
    "Claude": "Claude",
    "Groq": "Grok",
    "ElevenLabs": "Eleven Labs",
    "OpenCode": "Open Code",

    # Financial abbreviations
    "IPO": "I.P.O.",
    "ETF": "E.T.F.",
    "SaaS": "Sass",
    "B2B": "B to B",
    "B2C": "B to C",

    # Common symbols
    "%": " percent",
    "&": " and",
    "+": " plus",
    "=": " equals",
    "#": " number ",
    "@": " at ",
    "->": " leading to ",
    "=>": " resulting in ",

    # Common mispronunciations
    "Cupertino": "Coo-per-tee-no",
    "Dijkstra": "Dike-struh",
    "Debian": "Deb-ee-an",
    "Ubuntu": "Oo-BOON-too",
    "Arch": "Ark",
    "GNU": "Guh-noo",
}

# Abbreviations that should NOT trigger sentence boundaries
ABBREVIATIONS: set[str] = {
    "Mr", "Mrs", "Ms", "Dr", "Prof", "Sr", "Jr", "Inc", "Ltd", "Corp",
    "vs", "etc", "approx", "apt", "dept", "est", "gov", "misc", "tech",
    "temp", "vet", "vol", "avg", "max", "min", "seq", "ref", "fig",
    "e.g", "i.e", "a.m", "p.m", "St", "Ave", "Blvd", "Rd",
    "U.S", "U.K", "E.U", "N.A.S.A", "F.B.I", "C.I.A",
    "No", "Nos", "Op", "pp", "ch", "sec", "def", "resp",
}


# ════════════════════════════════════════════════════════════════
#  Sentence Boundary Detection
# ════════════════════════════════════════════════════════════════

def check_sentence_boundary(text: str, pos: int) -> bool:
    """Check if the character at pos is a real sentence boundary.

    Handles abbreviations, decimal numbers, initials, and quoted speech.
    """
    char = text[pos]

    # ! and ? are always sentence boundaries (unless inside quotes with continuation)
    if char in ("!", "?"):
        after = text[pos + 1 :].lstrip()
        if after and after[0] in ('"', "'", "\u300d"):
            first_letter = re.search(r"[a-zA-Z]", after)
            if first_letter and first_letter.group().islower():
                return False
        return True

    if char == "\u2026":  # ellipsis
        return True

    # For periods: check if it's an abbreviation
    if char == ".":
        before = text[:pos]

        # Look backwards through dots to detect full dotted abbreviations like "U.S.A"
        dotted_match = re.search(r"([A-Za-z](?:\.[A-Za-z])+)$", before)
        if dotted_match:
            full_dotted = dotted_match.group(1)  # e.g. "U.S.A"
            full_dotted_stripped = full_dotted.replace(".", "")
            full_with_dot = full_dotted + "."
            if full_dotted in ABBREVIATIONS or full_with_dot in ABBREVIATIONS or full_dotted_stripped in ABBREVIATIONS:
                return False
            # Also check common multi-dot abbreviations not in the set
            if re.match(r"^[A-Z](?:\.[A-Z])+$", full_dotted):
                return False

        word_match = re.search(r"([A-Za-z]+)$", before)

        if word_match:
            word = word_match.group(1)
            if word in ABBREVIATIONS or f"{word}." in ABBREVIATIONS:
                return False
            if len(word) == 1 and word.isupper():
                return False
            if re.match(r"^(Mr|Mrs|Ms|Dr|Prof|Sr|Jr)$", word):
                return False

        after = text[pos + 1 :].lstrip()
        if after:
            first_char = after[0]
            if first_char.islower():
                if re.search(r"\d$", before):
                    return False
                return False

        return True

    return False


def split_into_sentences(text: str) -> list[str]:
    """Split text into sentences with proper boundary detection.

    Character-by-character walk that handles abbreviations, decimal numbers,
    initials, and quoted speech. Returns list of sentence strings.
    """
    if not text or not text.strip():
        return []

    results: list[str] = []
    current = ""
    i = 0

    while i < len(text):
        current += text[i]

        # Check sentence-ending punctuation
        if text[i] in (".", "!", "?", "\u2026"):
            if check_sentence_boundary(text, i):
                while i + 1 < len(text) and text[i + 1] == " ":
                    i += 1
                    current += " "
                trimmed = current.strip()
                if trimmed:
                    results.append(trimmed)
                current = ""
                i += 1
                continue

        # Split on double newlines (paragraph breaks)
        if text[i] == "\n" and i + 1 < len(text) and text[i + 1] == "\n":
            trimmed = current.strip()
            if trimmed:
                results.append(trimmed)
            current = ""
            i += 2
            continue

        i += 1

    # Flush remaining text
    trimmed = current.strip()
    if trimmed:
        results.append(trimmed)

    return results


# ════════════════════════════════════════════════════════════════
#  Text Preprocessing — Written → Spoken Form
# ════════════════════════════════════════════════════════════════

def _escape_regex(s: str) -> str:
    return re.escape(s)


def preprocess_for_speech(raw_text: str) -> str:
    """Convert written text into natural spoken form.

    21-step normalization pipeline:
    - Strip markdown formatting
    - Normalize URLs, emails, phone numbers
    - Convert dates, equations, percentages, monetary amounts
    - Expand pronunciation dictionary
    - Handle temperatures, time, years, version numbers
    - Clean up residual artifacts
    """
    if not raw_text:
        return ""

    text = raw_text

    # 1. Strip markdown code blocks
    text = re.sub(r"```[\s\S]*?```", "", text)
    # 2. Strip inline code
    text = re.sub(r"`([^`]+)`", r"\1", text)
    # 3. Strip bold
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    # 4. Strip italic
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    # 5. Strip strikethrough
    text = re.sub(r"~~([^~]+)~~", r"\1", text)
    # 6. Strip headers
    text = re.sub(r"##?\s+", "", text)
    # 7. Strip list bullets
    text = re.sub(r"[-*]\s+", "", text)

    # 8. Remove citations [1], [2]
    text = re.sub(r"\[\d+\]", "", text)
    # 9. Markdown links [text](url) — keep text
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # 10. Remove Sources section
    text = re.sub(r"Sources?:[\s\S]*$", "", text, flags=re.IGNORECASE)
    # 11. Strip hashtags
    text = re.sub(r"#(\w+)", r"\1", text)

    # 12. Normalize URLs: https://example.com/path → "example dot com"
    text = re.sub(
        r"https?://(?:www\.)?([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})(?:/[^\s]*)?",
        lambda m: m.group(1).replace(".", " dot "),
        text,
    )

    # 13. Normalize emails: test@example.com → "test at example dot com"
    text = re.sub(
        r"([a-zA-Z0-9._%+-]+)@([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})",
        lambda m: f"{m.group(1)} at {m.group(2).replace('.', ' dot ')}",
        text,
    )

    # 14. Normalize phone numbers: (123) 456-7891 → digit by digit
    def _phone_to_digits(match: re.Match) -> str:
        digits = re.sub(r"\D", "", match.group())
        if len(digits) == 10:
            return " ".join(digits)
        return match.group()

    text = re.sub(r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}", _phone_to_digits, text)

    # 15. Normalize dates: 5/6/2025 → "may sixth twenty twenty five"
    MONTHS = [
        "january", "february", "march", "april", "may", "june",
        "july", "august", "september", "october", "november", "december",
    ]

    def _date_to_spoken(match: re.Match) -> str:
        m, d, y = int(match.group(1)), int(match.group(2)), int(match.group(3))
        month = MONTHS[m - 1] if 1 <= m <= 12 else str(m)
        if d == 1:
            day = "first"
        elif d == 2:
            day = "second"
        elif d == 3:
            day = "third"
        elif d == 21:
            day = "twenty first"
        elif d == 22:
            day = "twenty second"
        elif d == 23:
            day = "twenty third"
        elif d == 31:
            day = "thirty first"
        else:
            day = f"{d}th"
        century, rem = divmod(y, 100)
        if rem == 0:
            year = f"{century} hundred"
        elif rem < 10:
            year = f"{century} oh {rem}"
        else:
            year = f"{century} {rem}"
        return f"{month} {day} {year}"

    text = re.sub(r"(\d{1,2})/(\d{1,2})/(\d{4})", _date_to_spoken, text)

    # 16. Normalize equations: 2+2=4 → "two plus two equals four"
    def _equation_to_spoken(match: re.Match) -> str:
        a, op, b = match.group(1), match.group(2), match.group(3)
        result = match.group(4)
        ops = {"+": "plus", "-": "minus", "*": "times", "/": "divided by",
               "\u00d7": "times", "\u00f7": "divided by", "=": "equals"}
        eq = f"{a} {ops.get(op, op)} {b}"
        if result:
            eq += f" equals {result}"
        return eq

    text = re.sub(
        r"(\d+)\s*([+\-*/\u00d7\u00f7=])\s*(\d+)(?:\s*=\s*(\d+))?",
        _equation_to_spoken,
        text,
    )

    # 17. Expand pronunciation dictionary (case-sensitive for acronyms)
    for abbr, expansion in PRONUNCIATION_MAP.items():
        if len(abbr) <= 6 and abbr.isupper():
            text = re.sub(rf"\b{re.escape(abbr)}\b", expansion, text)
        elif len(abbr) > 1:
            text = text.replace(abbr, expansion)

    # 18. Monetary amounts: $200M → "200 million dollars"
    text = re.sub(
        r"\$(\d+(?:\.\d+)?)([MBK])",
        lambda m: f"{m.group(1)} {{'M': 'million', 'B': 'billion', 'K': 'thousand'}}.get(m.group(2), m.group(2)) dollars",
        text,
    )
    text = re.sub(r"\$(\d+(?:,\d{3})*(?:\.\d+)?)", r"\1 dollars", text)
    text = re.sub(r"\u20ac(\d+(?:,\d{3})*(?:\.\d+)?)", r"\1 euros", text)
    text = re.sub(r"\u00a3(\d+(?:,\d{3})*(?:\.\d+)?)", r"\1 pounds", text)

    # 19. Percentages: 90% → "90 percent"
    text = re.sub(r"(\d+(?:\.\d+)?)%", r"\1 percent", text)

    # 20. Temperatures: 72°F → "72 degrees Fahrenheit"
    text = re.sub(r"(\d+(?:\.\d+)?)\u00b0F", r"\1 degrees Fahrenheit", text)
    text = re.sub(r"(\d+(?:\.\d+)?)\u00b0C", r"\1 degrees Celsius", text)

    # 21. Time: 3:30pm → "3 30 pm"
    text = re.sub(
        r"(\d{1,2}):(\d{2})\s*(am|pm|AM|PM)",
        lambda m: (
            f"{m.group(1)} {m.group(2)} {m.group(3).lower()}"
            if int(m.group(2)) > 0
            else f"{m.group(1)} {m.group(3).lower()}"
        ),
        text,
    )

    # 22. Years: 2024 → "twenty twenty four"
    def _year_to_spoken(match: re.Match) -> str:
        y = int(match.group(1))
        first, last = divmod(y, 100)
        if last == 0:
            return f"{first} hundred"
        if last < 10:
            return f"{first} oh {last}"
        return f"{first} {last}"

    text = re.sub(r"\b(20\d{2})\b", _year_to_spoken, text)

    # 23. Version numbers: v2.0 → "version two point oh"
    text = re.sub(r"v(\d+(?:\.\d+)+)", lambda m: "version " + m.group(1).replace(".", " point "), text, flags=re.IGNORECASE)

    # 24. Clean up residual markdown artifacts
    text = re.sub(r"[#*_~`|<>]", "", text)
    text = re.sub(r"\s+", " ", text).strip()

    # 25. Normalize ellipsis
    text = re.sub(r"\s*\.\s*\.\s*\.\s*", "\u2026", text)

    # 26. Remove emotion tags
    text = re.sub(r"\[(?:confident|curious|urgent|empathetic|informative|neutral|excited|calm|serious)\]", "", text, flags=re.IGNORECASE)

    # 27. Final cleanup
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


# ════════════════════════════════════════════════════════════════
#  Emotion Detection
# ════════════════════════════════════════════════════════════════

EMOTION_PROSODY: dict[str, dict[str, float]] = {
    "confident":   {"rate": 0.93, "pitch": 0.85, "volume": 1.0},
    "curious":     {"rate": 0.92, "pitch": 0.92, "volume": 0.95},
    "urgent":      {"rate": 1.05, "pitch": 0.93, "volume": 1.1},
    "empathetic":  {"rate": 0.88, "pitch": 0.84, "volume": 0.9},
    "informative": {"rate": 0.90, "pitch": 0.86, "volume": 0.98},
    "neutral":     {"rate": 0.95, "pitch": 0.88, "volume": 1.0},
}


def detect_emotion(text: str, user_sentiment: str | None = None) -> str:
    """Detect emotional tone from text content.

    Uses regex keyword matching. Optionally carries forward user sentiment.
    Returns one of: neutral, confident, curious, urgent, empathetic, informative.
    """
    lower = text.lower().strip()

    # Carry forward user sentiment unless response is clearly different
    if user_sentiment == "urgent" and not re.search(r"\b(?:great|good|excellent|perfect|resolved)\b", lower):
        return "urgent"
    if user_sentiment == "empathetic" and not re.search(r"\b(?:great|good|excellent|perfect|resolved)\b", lower):
        return "empathetic"

    # Urgent / time-sensitive
    if re.search(r"\b(?:warning|alert|critical|urgent|immediately|danger|emergency)\b", lower):
        return "urgent"

    # Empathetic / negative
    if re.search(r"\b(?:sorry|unfortunately|apologize|regret|sad|difficult|problem|issue|error|fail|trouble)\b", lower):
        return "empathetic"

    # Curious / questioning
    if text.endswith("?") or re.search(r"\b(?:wonder|curious|interesting|hmm|let me check)\b", lower):
        return "curious"

    # Confident / authoritative
    if re.search(r"\b(?:verified|confirmed|found|identified|here's what|the answer is|definitely|exactly|precisely)\b", lower):
        return "confident"

    # Informative / data-heavy
    if re.search(r"\b(?:percent|million|billion|degrees|dollars|sources|findings|results|data|statistics)\b", lower):
        return "informative"

    return user_sentiment if user_sentiment in EMOTION_PROSODY else "neutral"


def detect_user_sentiment(user_message: str) -> str:
    """Analyze user input for emotional context."""
    lower = user_message.lower().strip()

    if re.search(r"\b(?:urgent|emergency|asap|help\s*!|need\s+now|right\s+now|immediately|hurry)", lower):
        return "urgent"
    if re.search(r"\b(?:worried|scared|afraid|sad|upset|frustrated|annoyed|angry|disappointed|hate|terrible|awful)\b", lower):
        return "empathetic"
    if re.search(r"\b(?:wonder|curious|interesting|how\s+come|why\s+do|what\s+if|hmm)\b", lower) or user_message.strip().endswith("?"):
        return "curious"

    return "neutral"


# ════════════════════════════════════════════════════════════════
#  Voice Profiles
# ════════════════════════════════════════════════════════════════

@dataclass
class VoiceProfile:
    """A named voice profile with prosody multipliers."""
    name: str
    rate_mult: float = 1.0
    pitch_mult: float = 1.0
    volume_mult: float = 1.0
    pause_mult: float = 1.0


VOICE_PROFILES: dict[str, VoiceProfile] = {
    "nally":    VoiceProfile("nally",    0.97, 0.95, 1.0,  1.1),   # Confident, measured
    "narrator": VoiceProfile("narrator", 1.0,  0.98, 1.0,  1.0),   # Steady, expressive
    "concise":  VoiceProfile("concise",  1.1,  0.9,  0.92, 0.5),   # Fast, minimal pauses
    "warm":     VoiceProfile("warm",     1.02, 1.03, 1.0,  0.85),  # Lighter, warmer
}


# ════════════════════════════════════════════════════════════════
#  Speech Segments & Prosody Smoothing
# ════════════════════════════════════════════════════════════════

@dataclass
class SpeechSegment:
    """A single speech segment with prosody parameters."""
    text: str
    rate: float = 0.95
    pitch: float = 0.88
    volume: float = 1.0
    pause_after_ms: int = 350
    emotion: str = "neutral"


def _analyze_prosody(sentence: str, emotion: str) -> SpeechSegment:
    """Determine prosody for a sentence based on content and emotion."""
    prosody = EMOTION_PROSODY.get(emotion, EMOTION_PROSODY["neutral"])
    rate = prosody["rate"]
    pitch = prosody["pitch"]
    volume = prosody["volume"]

    # Punctuation adjustments
    if sentence.endswith("?"):
        pitch = min(pitch + 0.04, 1.2)
        rate = max(rate - 0.03, 0.7)
    if sentence.endswith("!"):
        pitch = min(pitch + 0.03, 1.2)
        rate = min(rate + 0.05, 1.3)
        volume = min(volume + 0.05, 1.2)

    # Pause duration based on ending
    if sentence.endswith("?"):
        pause = 400
    elif sentence.endswith("!"):
        pause = 300
    elif sentence.endswith("\u2026"):
        pause = 500
    elif sentence.endswith(","):
        pause = 150
    elif sentence.endswith(":"):
        pause = 250
    elif sentence.endswith("\u2014"):
        pause = 200
    else:
        pause = 350

    # Content-based adjustments
    if re.match(r"^(?:Searching|Analyzing|Verifying|Checking|Running)", sentence, re.IGNORECASE):
        rate = 1.08
        pitch = 0.83
        volume = 0.92

    if re.search(r"\d+ percent|\d+ (?:million|billion|thousand)|\d+ degrees|\$|\u20ac|\u00a3", sentence):
        rate = max(rate - 0.07, 0.78)

    if len(sentence) > 120:
        rate = max(rate - 0.05, 0.75)

    return SpeechSegment(
        text=sentence,
        rate=max(0.7, min(rate, 1.3)),
        pitch=max(0.7, min(pitch, 1.2)),
        volume=max(0.7, min(volume, 1.2)),
        pause_after_ms=pause,
        emotion=emotion,
    )


def smooth_prosody(segments: list[SpeechSegment]) -> list[SpeechSegment]:
    """Apply exponential moving average to prevent jarring rate/pitch jumps."""
    if len(segments) <= 1:
        return segments

    SMOOTHING = 0.3
    result = list(segments)

    for i in range(1, len(result)):
        prev = result[i - 1]
        curr = result[i]
        result[i] = SpeechSegment(
            text=curr.text,
            rate=prev.rate * SMOOTHING + curr.rate * (1 - SMOOTHING),
            pitch=prev.pitch * SMOOTHING + curr.pitch * (1 - SMOOTHING),
            volume=prev.volume * SMOOTHING + curr.volume * (1 - SMOOTHING),
            pause_after_ms=curr.pause_after_ms,
            emotion=curr.emotion,
        )

    return result


def apply_voice_profile(
    segments: list[SpeechSegment],
    profile_name: str = "nally",
) -> list[SpeechSegment]:
    """Apply a voice profile's multipliers to all segments."""
    profile = VOICE_PROFILES.get(profile_name, VOICE_PROFILES["nally"])
    return [
        SpeechSegment(
            text=s.text,
            rate=max(0.7, min(s.rate * profile.rate_mult, 1.3)),
            pitch=max(0.7, min(s.pitch * profile.pitch_mult, 1.2)),
            volume=max(0.7, min(s.volume * profile.volume_mult, 1.2)),
            pause_after_ms=int(s.pause_after_ms * profile.pause_mult),
            emotion=s.emotion,
        )
        for s in segments
    ]


# ════════════════════════════════════════════════════════════════
#  Full Pipeline — One-Shot Processing
# ════════════════════════════════════════════════════════════════

def process_for_speech(
    text: str,
    profile: str = "nally",
    user_sentiment: str | None = None,
) -> list[SpeechSegment]:
    """Full pipeline: preprocess → split → detect emotion → prosody → smooth → profile.

    Returns a list of SpeechSegment objects ready for TTS.
    """
    if not text or not text.strip():
        return []

    # Step 1: Preprocess text for speech
    preprocessed = preprocess_for_speech(text)
    if not preprocessed:
        return []

    # Step 2: Split into sentences
    sentences = split_into_sentences(preprocessed)
    if not sentences:
        return []

    # Step 3: Detect emotion for each sentence and build segments
    segments = []
    for sentence in sentences:
        emotion = detect_emotion(sentence, user_sentiment)
        segment = _analyze_prosody(sentence, emotion)
        segments.append(segment)

    # Step 4: Smooth prosody between segments
    segments = smooth_prosody(segments)

    # Step 5: Apply voice profile
    segments = apply_voice_profile(segments, profile)

    return segments


def process_for_speech_flat(
    text: str,
    profile: str = "nally",
    user_sentiment: str | None = None,
) -> list[str]:
    """Same as process_for_speech but returns plain text strings (for TTS backends that don't support prosody)."""
    segments = process_for_speech(text, profile, user_sentiment)
    return [s.text for s in segments]


# ════════════════════════════════════════════════════════════════
#  Streaming Sentence Detector
# ════════════════════════════════════════════════════════════════

class SentenceStream:
    """Streaming sentence detector for real-time TTS.

    Feed tokens as they arrive from the LLM. When a complete sentence
    is detected, it's yielded for immediate synthesis.
    """

    def __init__(self):
        self._buffer = ""

    def feed(self, text: str) -> list[str]:
        """Feed a chunk of text. Returns any complete sentences detected."""
        self._buffer += text
        sentences = split_into_sentences(self._buffer)

        if not sentences:
            return []

        # Check if the last sentence is complete (ends with sentence punctuation)
        last = sentences[-1]
        is_complete = last and last[-1] in ".!?\u2026"

        if is_complete:
            # All sentences are complete — clear buffer
            self._buffer = ""
            return sentences
        elif len(sentences) > 1:
            # All but the last are complete
            complete = sentences[:-1]
            self._buffer = sentences[-1]
            return complete

        return []

    def flush(self) -> str:
        """Flush remaining buffer as a final sentence."""
        remaining = self._buffer.strip()
        self._buffer = ""
        return remaining
