"""Telegram Media Helpers — inbound/outbound for Bot + Telethon.

Handles:
- Download + classify inbound photos/documents (Telethon + PTB)
- Text extraction for docs (txt/md/csv/py/json) with size caps
- PDF text extract (optional pypdf)
- Outbound IMAGE_FILE:/SEND_FILE: marker parsing + send_file
"""

import asyncio
import io
import re
import time
from pathlib import Path
from typing import Optional

from ..config import DATA_DIR
from ..utils.logger import logger

# ── Limits ──
MAX_FILE_SIZE = 15 * 1024 * 1024  # 15 MB cap for downloads
MAX_TEXT_EXTRACT = 100 * 1024  # 100 KB cap for inline text
INBOX_ROOT = DATA_DIR / "telegram_inbox"
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
TEXT_EXTS = {".txt", ".md", ".csv", ".json", ".py", ".js", ".html", ".css", ".yaml", ".yml", ".toml", ".cfg", ".log", ".sql"}
PDF_EXT = ".pdf"

# ── Regex for outbound markers ──
IMAGE_FILE_RE = re.compile(r"IMAGE_FILE:\s*([^\n]+)")
IMAGE_URL_RE = re.compile(r"IMAGE_URL:\s*([^\n]+)")
SEND_FILE_RE = re.compile(r"SEND_FILE:\s*([^\n]+)")

def _get_inbox_dir(session_id: str) -> Path:
    # sanitize session_id for filesystem — Windows forbids : < > " / \ | ? * in folder names
    # previous regex kept ':' which breaks on Windows (C:\...\telegram:123); replace everything not alnum/_/-.
    safe = re.sub(r"[^a-zA-Z0-9_\-]", "_", session_id)
    # collapse consecutive underscores and strip edges for cleanliness
    safe = re.sub(r"_+", "_", safe).strip("_")
    if not safe:
        safe = "default"
    p = INBOX_ROOT / safe
    p.mkdir(parents=True, exist_ok=True)
    return p

def _is_image_path(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTS

def _extract_text_file(path: Path) -> Optional[str]:
    """Try to read text file up to MAX_TEXT_EXTRACT. Returns None if not text."""
    try:
        if path.suffix.lower() not in TEXT_EXTS:
            return None
        data = path.read_bytes()
        if len(data) > MAX_TEXT_EXTRACT:
            data = data[:MAX_TEXT_EXTRACT]
            truncated = True
        else:
            truncated = False
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("latin-1")
        # Strip large whitespace
        text = text.strip()
        if not text:
            return None
        if truncated:
            text += "\n\n[... truncated, file was larger than 100KB]"
        return text
    except Exception as e:
        logger.debug(f"extract_text_file failed for {path}: {e}")
        return None

def _extract_pdf_text(path: Path, max_pages: int = 3) -> Optional[str]:
    """Extract text from PDF via pypdf if available. Returns None if unavailable or empty."""
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:
        return None
    try:
        reader = PdfReader(str(path))
        pages = reader.pages[:max_pages]
        texts = []
        for p in pages:
            try:
                t = p.extract_text() or ""
                if t.strip():
                    texts.append(t.strip())
            except Exception:
                continue
        if not texts:
            return None
        combined = "\n\n".join(texts)
        if len(combined) > MAX_TEXT_EXTRACT:
            combined = combined[:MAX_TEXT_EXTRACT] + "\n\n[... PDF truncated]"
        return combined.strip()
    except Exception as e:
        logger.debug(f"PDF extract failed {path}: {e}")
        return None

def parse_outbound_files(text: str) -> list[Path]:
    """Find IMAGE_FILE:, IMAGE_URL:, and SEND_FILE: markers in agent response."""
    paths: list[Path] = []
    for m in IMAGE_FILE_RE.finditer(text):
        p = Path(m.group(1).strip().strip('"').strip("'"))
        if p.exists():
            paths.append(p)
        else:
            logger.warning(f"Outbound marker path not found: {p}")
    for m in IMAGE_URL_RE.finditer(text):
        url = m.group(1).strip().strip('"').strip("'")
        if url.startswith("http"):
            # Download URL to temp file for Telegram send
            try:
                import httpx
                resp = httpx.get(url, timeout=30.0, follow_redirects=True)
                resp.raise_for_status()
                ext = ".jpg"
                ctype = resp.headers.get("content-type", "").lower()
                if "png" in ctype:
                    ext = ".png"
                elif "webp" in ctype:
                    ext = ".webp"
                tmp = INBOX_ROOT / f"url_{int(time.time())}{ext}"
                tmp.write_bytes(resp.content)
                paths.append(tmp)
            except Exception as e:
                logger.warning(f"Failed to download IMAGE_URL {url[:80]}: {e}")
        else:
            logger.warning(f"IMAGE_URL not an HTTP URL: {url}")
    for m in SEND_FILE_RE.finditer(text):
        p = Path(m.group(1).strip().strip('"').strip("'"))
        if p.exists():
            paths.append(p)
        else:
            logger.warning(f"Outbound marker path not found: {p}")
    # deduplicate preserve order
    seen = set()
    uniq = []
    for p in paths:
        if str(p) not in seen:
            seen.add(str(p))
            uniq.append(p)
    return uniq

def strip_file_markers(text: str) -> str:
    """Remove IMAGE_FILE:/IMAGE_URL:/SEND_FILE: lines from text after sending."""
    text = IMAGE_FILE_RE.sub("", text)
    text = IMAGE_URL_RE.sub("", text)
    text = SEND_FILE_RE.sub("", text)
    # collapse multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text

def describe_inbound_file(path: Path, extract_text: bool = True) -> str:
    """Build a human-readable description for agent context."""
    try:
        size_kb = path.stat().st_size / 1024
    except Exception:
        size_kb = 0
    suffix = path.suffix.lower()
    desc = f"[User sent file: {path.name} ({suffix or 'no ext'}, {size_kb:.1f}KB) at {path}]"
    if extract_text and suffix in TEXT_EXTS:
        txt = _extract_text_file(path)
        if txt:
            # truncate for agent prompt (keep under 3000 chars)
            if len(txt) > 3000:
                txt = txt[:3000] + "\n[... truncated]"
            desc += f"\n--- File content ({path.name}) ---\n{txt}\n--- End file ---"
    elif suffix == PDF_EXT:
        txt = _extract_pdf_text(path)
        if txt:
            if len(txt) > 3000:
                txt = txt[:3000] + "\n[... truncated]"
            desc += f"\n--- PDF text ({path.name}) ---\n{txt}\n--- End PDF ---"
        else:
            desc += " (PDF text extraction unavailable — install pypdf or describe file)"
    elif suffix in IMAGE_EXTS:
        desc += " (image — use caption/vision if available)"
    else:
        desc += " (binary/other — describe what to do with it)"
    return desc

# ── Inbound — Telethon ──

async def save_telethon_media(client, message, session_id: str) -> tuple[Optional[Path], str]:
    """Download Telethon message media to inbox.

    Returns (saved_path or None, description_or_error).
    Handles photo, document (any).
    """
    try:
        inbox = _get_inbox_dir(session_id)
        # Quick size check if attribute exists
        # Telethon file.size may be available
        try:
            fsize = getattr(message.file, "size", None) if getattr(message, "file", None) else None
            if fsize and fsize > MAX_FILE_SIZE:
                return None, f"[User sent file too large: {fsize/1024/1024:.1f}MB > 15MB — ignored]"
        except Exception:
            pass

        # Determine extension
        ext = ""
        name = getattr(message.file, "name", None) if getattr(message, "file", None) else None
        if name and "." in name:
            ext = "." + name.rsplit(".", 1)[-1].lower()
            # sanitize name
            safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", name)
        elif message.photo:
            safe_name = f"photo_{int(time.time())}.jpg"
            ext = ".jpg"
        else:
            safe_name = f"file_{int(time.time())}{ext}"
            if not ext:
                safe_name += ".bin"

        # Ensure unique
        dest = inbox / safe_name
        counter = 1
        while dest.exists():
            stem = dest.stem
            dest = inbox / f"{stem}_{counter}{dest.suffix}"
            counter += 1

        # Download
        buf = io.BytesIO()
        await client.download_media(message, file=buf)
        data = buf.getvalue()
        if not data:
            return None, "[User sent file but download returned empty]"
        if len(data) > MAX_FILE_SIZE:
            return None, f"[User sent file too large: {len(data)/1024/1024:.1f}MB > 15MB — ignored]"

        dest.write_bytes(data)
        logger.info(f"Saved inbound Telethon media: {dest} ({len(data)} bytes)")
        desc = describe_inbound_file(dest)
        return dest, desc
    except Exception as e:
        logger.error(f"save_telethon_media failed: {e}")
        return None, f"[Failed to save inbound file: {e}]"

def build_agent_input(caption: str, media_desc: str) -> str:
    """Combine caption + media description into agent prompt."""
    caption = (caption or "").strip()
    if caption and media_desc:
        return f"{caption}\n\n{media_desc}"
    elif caption:
        return caption
    elif media_desc:
        # If no caption but we have a file, ask agent to acknowledge
        return f"{media_desc}\n\n[User sent this file — respond appropriately. If image, describe/acknowledge it.]"
    else:
        return ""

# ── Inbound — Bot (python-telegram-bot) ──

async def save_bot_media(bot, message, session_id: str) -> tuple[Optional[Path], str]:
    """Download PTB message media (photo/document) to inbox."""
    try:
        inbox = _get_inbox_dir(session_id)
        file_obj = None
        ext = ""
        name = ""

        if message.photo:
            # largest photo is last
            photo = message.photo[-1]
            file_obj = await photo.get_file()
            name = f"photo_{int(time.time())}.jpg"
            ext = ".jpg"
        elif message.document:
            doc = message.document
            if doc.file_size and doc.file_size > MAX_FILE_SIZE:
                return None, f"[User sent file too large: {doc.file_size/1024/1024:.1f}MB > 15MB — ignored]"
            file_obj = await doc.get_file()
            name = doc.file_name or f"file_{int(time.time())}.bin"
            if "." in name:
                ext = "." + name.rsplit(".", 1)[-1].lower()
            safe_name_input = name
            name = re.sub(r"[^a-zA-Z0-9._-]", "_", safe_name_input)
        else:
            return None, ""

        # unique path
        dest = inbox / name
        counter = 1
        while dest.exists():
            dest = inbox / f"{dest.stem}_{counter}{dest.suffix}"
            counter += 1

        # download as bytearray
        data = await file_obj.download_as_bytearray()
        b = bytes(data)
        if len(b) > MAX_FILE_SIZE:
            return None, f"[User sent file too large: {len(b)/1024/1024:.1f}MB > 15MB — ignored]"
        if not b:
            return None, "[Downloaded file was empty]"
        dest.write_bytes(b)
        logger.info(f"Saved inbound Bot media: {dest} ({len(b)} bytes)")
        desc = describe_inbound_file(dest)
        return dest, desc
    except Exception as e:
        logger.error(f"save_bot_media failed: {e}")
        return None, f"[Failed to save inbound file: {e}]"

# ── Outbound — Telethon ──

async def send_attachments_telethon(client, peer, paths: list[Path], caption: str = ""):
    """Send files via Telethon client."""
    for p in paths:
        try:
            is_image = _is_image_path(p)
            # Telethon: voice_note=False by default; for images, preview works.
            # For docs, force_document keeps original.
            await client.send_file(
                peer,
                str(p),
                caption=caption[:1024] if caption else None,
                force_document=not is_image,
            )
            logger.info(f"Sent attachment via Telethon: {p} to {peer}")
            # small gap to avoid flood
            await asyncio.sleep(0.3)
        except Exception as e:
            logger.error(f"Telethon send_file failed for {p}: {e}")
            try:
                await client.send_message(peer, f"Failed to send file {p.name}: {e}")
            except Exception:
                pass

# ── Outbound — Bot (PTB) ──

async def send_attachments_bot(bot, chat_id: int, paths: list[Path], caption: str = ""):
    """Send files via PTB Bot."""
    for p in paths:
        try:
            is_image = _is_image_path(p)
            cap = caption[:1024] if caption else None
            if is_image:
                with open(p, "rb") as f:
                    await bot.send_photo(chat_id=chat_id, photo=f, caption=cap)
            else:
                with open(p, "rb") as f:
                    await bot.send_document(chat_id=chat_id, document=f, caption=cap)
            logger.info(f"Sent attachment via Bot: {p} to {chat_id}")
            await asyncio.sleep(0.3)
        except Exception as e:
            logger.error(f"Bot send attachment failed for {p}: {e}")
            try:
                await bot.send_message(chat_id=chat_id, text=f"Failed to send file {p.name}: {e}")
            except Exception:
                pass

# ── Vision helper (optional) ──

def _should_use_vision() -> bool:
    """Check if current LLM likely supports vision (cheap heuristic)."""
    try:
        from ..config import ACTIVE_MODEL
        m = ACTIVE_MODEL.lower()
        vision_keywords = ("vision", "gpt-4", "claude", "gemini", "llava", "image", "muse-spark", "spark")
        if any(k in m for k in vision_keywords):
            return True
        # Muse Spark 1.2 family is multimodal (text+image+video+audio+pdf) per Meta
        if "muse" in m:
            return True
        return False
    except Exception:
        return False


def _try_ocr(image_path: Path) -> Optional[str]:
    """Try local OCR via pytesseract if installed. Returns extracted text or None."""
    try:
        from PIL import Image
        import pytesseract  # type: ignore

        # quick check: tesseract binary must be available
        try:
            pytesseract.get_tesseract_version()
        except Exception:
            return None

        # Enhance dark screenshots for OCR: convert to grayscale + contrast boost
        img = Image.open(image_path).convert("L")
        # Simple contrast stretch for dark images
        try:
            from PIL import ImageOps, ImageEnhance

            # Autocontrast + slight upscale for small UI text
            img = ImageOps.autocontrast(img, cutoff=2)
            img = ImageEnhance.Contrast(img).enhance(1.8)
            # Upscale if small
            if img.width < 800:
                img = img.resize((img.width * 2, img.height * 2), Image.LANCZOS)
        except Exception:
            pass

        # PsM 6 = assume single uniform block of text (good for UI), 11 = sparse text
        for psm in ("6", "11", "3"):
            try:
                txt = pytesseract.image_to_string(img, config=f"--psm {psm}").strip()
                if txt and len(txt) >= 4:
                    # Filter noise: keep if contains at least some alnum
                    if any(c.isalnum() for c in txt):
                        return txt[:2000]
            except Exception:
                continue
        return None
    except ImportError:
        return None
    except Exception as e:
        logger.debug(f"OCR failed for {image_path}: {e}")
        return None


async def describe_image_vision(image_path: Path, prompt: str = "Describe this image for the assistant in 2-3 sentences. What is shown?") -> Optional[str]:
    """Try to get a vision description via LLM. Returns None on failure / no vision."""
    if not _should_use_vision():
        return None
    try:
        import base64
        from ..agent.llm import llm as nally_llm

        b64 = base64.b64encode(image_path.read_bytes()).decode("utf-8")
        # detect mime
        mime = "image/jpeg"
        suf = image_path.suffix.lower()
        if suf == ".png":
            mime = "image/png"
        elif suf == ".webp":
            mime = "image/webp"
        elif suf == ".gif":
            mime = "image/gif"
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                ],
            }
        ]
        # Use NallyLLM wrapper so Muse Spark goes via responses API correctly (needs 2500 for vision+reasoning)
        resp = nally_llm.chat(messages, temperature=0.2, max_tokens=2500)
        text = (resp.choices[0].message.content or "").strip()
        if not text:
            return None
        logger.info(f"Vision description for {image_path.name}: {text[:150]}")
        return text
    except Exception as e:
        logger.debug(f"Vision describe failed for {image_path}: {e}")
        return None


async def analyze_image(image_path: Path, user_question: str = "") -> str:
    """
    Full image analysis: vision + OCR for any image.
    Handles: general description, text reading, object ID, and game/gun specifics.
    Returns a combined description string for agent context.
    """
    # OCR first (cheap, local, catches UI text). Vision model also does OCR, but local is a useful fallback.
    ocr_text = await asyncio.to_thread(_try_ocr, image_path) if image_path.exists() else None
    ocr_block = ""
    if ocr_text:
        ocr_block = f"\n[OCR extracted UI text: {ocr_text[:800].strip()}]"
        if len(ocr_text) > 800:
            ocr_block += " (truncated)"
    else:
        # Don't spam "not installed" every time if we have vision — vision will handle OCR anyway
        if _should_use_vision():
            ocr_block = "\n[OCR: vision model will also read text — local pytesseract not needed]"
        else:
            ocr_block = "\n[OCR: pytesseract not installed or no text detected — UI text not extracted]"

    q = (user_question or "").strip()
    q_lower = q.lower()

    # Choose prompt based on question intent
    is_gun_game = any(k in q_lower for k in ("gun", "weapon", "game", "m416", "ak", "rifle", "pistol", "shotgun", "sniper"))
    if is_gun_game or not q:
        vision_prompt = (
            "You are a game and image expert. Look at this screenshot/image and answer the user's question.\n"
            "If it's a weapon/gun screenshot:\n"
            "1) Exact gun/weapon name and variant if visible (e.g., M4A1 Custom, AKM, SCAR)\n"
            "2) Which game it is from (e.g., Garena Free Fire / Free Fire MAX, PUBG Mobile, CODM, etc.) and why (UI elements, art style, HUD, fonts)\n"
            "3) Key visual clues: color/skin, scope, stock, magazine, shape, attachments\n"
            "4) Any UI text you can read (ammo, weapon name in corner, kill feed, ARMORY, etc.)\n"
            "Otherwise, describe what you see, read any text, identify objects, people, scene, and answer the user's question directly.\n"
            "Be specific. If you cannot be certain, give 2-3 candidates with reasoning. Describe what you actually see; do not guess blindly.\n"
            f"\nUser question: {q or 'What is in this image? Describe it and read any text.'}"
        )
    else:
        vision_prompt = (
            "You are an expert image analyst. Look at this image and answer the user's question accurately.\n"
            "- Describe what you see in detail: objects, people, scene, colors, layout\n"
            "- Read and transcribe any text visible in the image (UI labels, signs, documents, captions)\n"
            "- If the question is specific (e.g., 'what gun', 'what text', 'where is this'), focus on that but also provide context\n"
            "- Be specific and cite visual evidence. If uncertain, give best candidates with reasoning.\n"
            f"\nUser question: {q}"
        )

    vision_text = await describe_image_vision(image_path, prompt=vision_prompt)
    if vision_text:
        return f"[Vision: {vision_text}]{ocr_block}"
    else:
        return f"[Vision unavailable — model may not support images or call failed]{ocr_block}"


async def analyze_image_for_game(image_path: Path, user_question: str = "") -> str:
    """Backward-compat alias for analyze_image (gun/game specific)."""
    return await analyze_image(image_path, user_question=user_question)


async def analyze_images(image_paths: list[Path], user_question: str = "") -> str:
    """Analyze multiple images (e.g., Telegram album). Returns combined vision blocks."""
    if not image_paths:
        return ""
    blocks = []
    for idx, p in enumerate(image_paths, 1):
        try:
            block = await analyze_image(p, user_question=user_question)
            blocks.append(f"--- Image {idx}/{len(image_paths)}: {p.name} ---\n{block}")
        except Exception as e:
            blocks.append(f"--- Image {idx}: {p.name} — failed: {e} ---")
    return "\n\n".join(blocks)


async def fetch_image_from_url(url: str, session_id: str = "web:default") -> tuple[Optional[Path], str]:
    """Fetch an image from a URL to inbox for analysis. Returns (path, desc)."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            ctype = resp.headers.get("content-type", "").lower()
            if "image" not in ctype and not url.lower().endswith(tuple(IMAGE_EXTS)):
                # Still try to treat as image if bytes look like image
                pass
            data = resp.content
            if len(data) > MAX_FILE_SIZE:
                return None, f"[Image URL too large: {len(data)/1024/1024:.1f}MB]"
            if len(data) < 100:
                return None, "[Image URL returned empty]"
            # Determine ext from content-type or url
            ext = ".jpg"
            if "png" in ctype:
                ext = ".png"
            elif "webp" in ctype:
                ext = ".webp"
            elif "gif" in ctype:
                ext = ".gif"
            inbox = _get_inbox_dir(session_id)
            name = f"url_{int(time.time())}{ext}"
            dest = inbox / name
            dest.write_bytes(data)
            desc = describe_inbound_file(dest)
            return dest, desc
    except Exception as e:
        return None, f"[Failed to fetch image URL: {e}]"
