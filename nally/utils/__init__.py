import shutil

from .logger import logger

_ffmpeg_checked = False
_ffmpeg_available = False


def ffmpeg_available() -> bool:
    """Check if ffmpeg is available (cached after first call)."""
    global _ffmpeg_checked, _ffmpeg_available
    if not _ffmpeg_checked:
        _ffmpeg_available = shutil.which("ffmpeg") is not None
        _ffmpeg_checked = True
    return _ffmpeg_available


__all__ = ["logger", "ffmpeg_available"]
