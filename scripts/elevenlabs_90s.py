#!/usr/bin/env python3
"""Generate a 90s-style voice recording using ElevenLabs and save to desktop."""

import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def main():
    # 90s-style voice content
    text = """
    Welcome to the nineties! This is a totally rad voice recording.
    Remember when we had to rewind our VHS tapes before returning them to Blockbuster?
    Those were the days, my friend. Radical!
    """

    try:
        from nally.voice.tts import ElevenLabsBackend

        backend = ElevenLabsBackend()
        wav_bytes = backend.synthesize_to_wav(text.strip())

        if not wav_bytes:
            print("Failed to generate audio. Check your ElevenLabs API key.")
            return

        # Save to desktop
        desktop = Path.home() / "Desktop"
        output_path = desktop / "90s_voice_recording.wav"

        with open(output_path, "wb") as f:
            f.write(wav_bytes)

        print(f"Saved: {output_path}")

    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()
