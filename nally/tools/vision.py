"""Vision Tool — analyze any image with Muse Spark vision + OCR.

Provides the agent a callable tool to "see" images, not just rely on
pre-injected Telegram handler vision. This is the full-capability path:
- image_path: local file (e.g., data/telegram_inbox/.../photo.jpg)
- image_url: remote URL (fetched to inbox, then analyzed)
- question: what to answer about the image

Uses the same analyze_image() helper as Telegram handlers (vision + OCR)
so results are consistent and grounded via receipt for the verifier.
"""

import asyncio
import re
from pathlib import Path
from typing import Optional

from .registry import Tool, registry
from ..utils.logger import logger

DATA_DIR = Path(__file__).parent.parent.parent / "data"

class AnalyzeImage(Tool):
    def __init__(self):
        super().__init__(
            name="analyze_image",
            description="Analyze an image and answer a question about it. Uses vision model (Muse Spark) plus OCR. Provide either image_path (local file) or image_url. Use this whenever the user sends an image, asks about an image, or you need to see what's in a picture/screenshot. Returns a detailed description and answer.",
            permission="safe",
            parameters={
                "image_path": {
                    "type": "string",
                    "description": "Local path to image file (e.g., data/telegram_inbox/.../photo.jpg or data/generated/.../img_....png). Preferred if you already have a file.",
                    "required": False,
                },
                "image_url": {
                    "type": "string",
                    "description": "Remote image URL to fetch and analyze (e.g., https://.../image.jpg). Will be downloaded to inbox first.",
                    "required": False,
                },
                "question": {
                    "type": "string",
                    "description": "Question to answer about the image. Be specific: e.g., 'What gun is this from what game?', 'Read all text in this image', 'Describe what you see'",
                    "required": False,
                    "default": "Describe this image in detail and read any text visible.",
                },
            },
        )

    def execute(self, image_path: str = "", image_url: str = "", question: str = "") -> str:
        # Normalize
        question = (question or "").strip() or "Describe this image in detail and read any text visible."
        image_path = (image_path or "").strip()
        image_url = (image_url or "").strip()

        if not image_path and not image_url:
            return "Error: Provide either image_path or image_url."

        # Resolve path
        target: Optional[Path] = None
        desc = ""

        # If URL, fetch first
        if image_url and not image_path:
            try:
                from ..telegram.media import fetch_image_from_url
                # Run async fetch in sync context
                try:
                    loop = asyncio.get_running_loop()
                    # If we're already in an event loop (e.g., from async handler), run in thread
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        future = pool.submit(asyncio.run, fetch_image_from_url(image_url, session_id="tool:vision"))
                        target, desc = future.result(timeout=40)
                except RuntimeError:
                    # No running loop, safe to run directly
                    target, desc = asyncio.run(fetch_image_from_url(image_url, session_id="tool:vision"))
                if not target or not target.exists():
                    return f"Failed to fetch image URL: {desc}"
                image_path = str(target)
            except Exception as e:
                return f"Error fetching image_url: {e}"

        # Validate local path
        if image_path:
            p = Path(image_path)
            # Allow relative paths; try to resolve
            if not p.exists():
                # Try common prefixes
                candidates = [
                    Path(image_path),
                    DATA_DIR / image_path,
                    DATA_DIR / "telegram_inbox" / image_path,
                    DATA_DIR / "generated" / image_path,
                    Path.cwd() / image_path,
                ]
                found = None
                for c in candidates:
                    if c.exists():
                        found = c
                        break
                if not found:
                    # Try glob search by name
                    name = Path(image_path).name
                    matches = list(DATA_DIR.rglob(name))
                    if matches:
                        found = matches[0]
                    else:
                        return f"Error: image_path not found: {image_path}. Tried: {[str(c) for c in candidates]}"
                p = found
            target = p

        if not target or not target.exists():
            return f"Error: image file not found after resolve: {image_path or image_url}"

        # Check that it's actually an image (by extension or try open)
        try:
            from PIL import Image
            with Image.open(target) as im:
                im.verify()
        except Exception:
            # Not a valid image, but still try vision (might be misnamed)
            pass

        # Run vision + OCR analysis (reuse Telegram helper for consistency)
        try:
            from ..telegram.media import analyze_image

            # analyze_image is async, so we need to run it
            try:
                loop = asyncio.get_running_loop()
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, analyze_image(target, user_question=question))
                    result = future.result(timeout=60)
            except RuntimeError:
                result = asyncio.run(analyze_image(target, user_question=question))

            # Also include basic file info
            try:
                size_kb = target.stat().st_size / 1024
                dims = ""
                try:
                    from PIL import Image
                    with Image.open(target) as im2:
                        dims = f"{im2.width}x{im2.height} {im2.mode}"
                except Exception:
                    pass
                header = f"Image: {target.name} ({size_kb:.1f}KB, {dims}) at {target}\nQuestion: {question}\n"
                full = header + result
                # Add hint for sending back if it's a generated image?
                # The result already contains vision + OCR
                return full[:8000]  # cap for tool output limit
            except Exception:
                return result[:8000]

        except Exception as e:
            logger.error(f"analyze_image tool failed for {target}: {e}")
            return f"Error analyzing image {target}: {e}"


class EditImage(Tool):
    """Basic image editing via PIL — resize, enhance, convert, etc. (no external API)."""

    def __init__(self):
        super().__init__(
            name="edit_image",
            description="Edit an image locally: resize, enhance brightness/contrast, convert format, etc. Works offline via PIL. Provide image_path and operation. Returns path to edited image (which can then be sent).",
            permission="safe",
            parameters={
                "image_path": {
                    "type": "string",
                    "description": "Local path to image file to edit",
                    "required": True,
                },
                "operation": {
                    "type": "string",
                    "description": "Operation: 'enhance' (auto-brightness/contrast for dark images, good for screenshots), 'resize' (requires width/height), 'grayscale', 'rotate' (degrees), 'crop' (requires box as 'left,upper,right,lower')",
                    "required": True,
                },
                "width": {
                    "type": "integer",
                    "description": "For resize: target width in pixels",
                    "required": False,
                },
                "height": {
                    "type": "integer",
                    "description": "For resize: target height in pixels",
                    "required": False,
                },
                "degrees": {
                    "type": "integer",
                    "description": "For rotate: degrees clockwise",
                    "required": False,
                    "default": 90,
                },
                "box": {
                    "type": "string",
                    "description": "For crop: 'left,upper,right,lower' in pixels",
                    "required": False,
                },
            },
        )

    def execute(self, image_path: str, operation: str, width: int = 0, height: int = 0, degrees: int = 90, box: str = "") -> str:
        p = Path(image_path)
        if not p.exists():
            # try to find by name
            name = p.name
            matches = list(DATA_DIR.rglob(name))
            if matches:
                p = matches[0]
            else:
                return f"Error: image_path not found: {image_path}"

        try:
            from PIL import Image, ImageEnhance, ImageOps

            with Image.open(p) as im:
                orig_w, orig_h = im.size
                out = im

                op = operation.lower().strip()
                if op == "enhance":
                    # Good for dark screenshots like the gun case: autocontrast + brightness
                    out = ImageOps.autocontrast(out, cutoff=2)
                    out = ImageEnhance.Contrast(out).enhance(1.8)
                    out = ImageEnhance.Brightness(out).enhance(1.15)
                    out = ImageEnhance.Color(out).enhance(1.05)
                elif op == "resize":
                    if not width or not height:
                        return "Error: resize requires width and height"
                    width = max(16, min(4096, width))
                    height = max(16, min(4096, height))
                    out = out.resize((width, height), Image.LANCZOS)
                elif op == "grayscale":
                    out = ImageOps.grayscale(out)
                elif op == "rotate":
                    out = out.rotate(-degrees, expand=True)  # PIL rotates counter-clockwise, so negate
                elif op == "crop":
                    if not box:
                        return "Error: crop requires box as 'left,upper,right,lower'"
                    try:
                        l, u, r, b = map(int, box.split(","))
                        out = out.crop((l, u, r, b))
                    except Exception as e:
                        return f"Error parsing box: {e}"
                else:
                    return f"Error: unknown operation '{operation}'. Use enhance/resize/grayscale/rotate/crop."

                # Save to generated dir
                out_dir = DATA_DIR / "generated"
                out_dir.mkdir(parents=True, exist_ok=True)
                suffix = p.suffix or ".png"
                if suffix.lower() not in [".png", ".jpg", ".jpeg", ".webp"]:
                    suffix = ".png"
                out_name = f"edited_{p.stem}_{operation}{suffix}"
                out_path = out_dir / out_name
                # Handle format
                if out.mode in ("RGBA", "LA") and suffix.lower() in [".jpg", ".jpeg"]:
                    bg = Image.new("RGB", out.size, (255, 255, 255))
                    bg.paste(out, mask=out.split()[-1] if out.mode == "RGBA" else None)
                    out = bg
                out.save(out_path)

                w2, h2 = out.size
                return f"Edited {p.name} ({orig_w}x{orig_h}) -> {out_path.name} ({w2}x{h2}) via {operation}\nSaved to: {out_path}\nIMAGE_FILE:{out_path}"
        except Exception as e:
            return f"Error editing image: {e}"


def register():
    registry.register(AnalyzeImage())
    registry.register(EditImage())
