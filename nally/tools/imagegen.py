"""Image Generation Tool — Vision-guided quality loop with MIMO critique."""
import base64
import io
import json
import logging
import random
import time
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter, ImageEnhance
from .registry import Tool, registry

logger = logging.getLogger("nally.tools.imagegen")

DATA_DIR = Path(__file__).parent.parent.parent / "data" / "generated"

# ── Content-Type Prompt Router ────────────────────────────

CONTENT_ROUTER = {
    "logo": {
        "add": ["flat design", "vector style", "clean lines", "minimalist", "simple", "white background"],
        "remove": ["photorealistic", "detailed", "8k", "texture", "shadows", "depth of field"],
        "negative": "realistic, 3d, texture, photo, shadows, complex, busy, blurry",
    },
    "photo": {
        "add": ["photorealistic", "DSLR photo", "85mm lens", "natural lighting", "bokeh"],
        "remove": ["cartoon", "anime", "painting", "illustration", "flat"],
        "negative": "cartoon, anime, painting, illustration, flat, drawing, sketch",
    },
    "art": {
        "add": ["masterpiece", "artstation", "digital painting", "concept art", "highly detailed"],
        "remove": ["photo", "realistic", "camera", "DSLR"],
        "negative": "photo, realistic, camera,DSLR, photograph, bad anatomy",
    },
    "anime": {
        "add": ["anime style", "studio ghibli", "vibrant colors", "cel shading", "clean lines"],
        "remove": ["realistic", "photo", "3d", "texture"],
        "negative": "realistic, photo, 3d, texture, blurry, low quality",
    },
    "3d": {
        "add": ["octane render", "cinema 4d", "volumetric lighting", "ray tracing", "high detail"],
        "remove": ["photo", "2d", "flat", "sketch"],
        "negative": "2d, flat, sketch, drawing, low poly, blurry",
    },
    "painting": {
        "add": ["oil painting", "canvas texture", "brush strokes", "classical", "museum quality"],
        "remove": ["photo", "digital", "3d", "render"],
        "negative": "photo, digital, 3d, render, camera, realistic",
    },
    "product": {
        "add": ["product photography", "studio lighting", "white background", "commercial", "high-end"],
        "remove": ["outdoor", "natural", "messy", "busy"],
        "negative": "outdoor, natural, messy, busy, blurry, text, watermark",
    },
}


def detect_content_type(prompt: str) -> str:
    lower = prompt.lower()
    if any(w in lower for w in ["logo", "icon", "brand", "emblem", "symbol"]):
        return "logo"
    if any(w in lower for w in ["photo", "realistic", "portrait", "landscape", "camera"]):
        return "photo"
    if any(w in lower for w in ["anime", "cartoon", "manga", "ghibli"]):
        return "anime"
    if any(w in lower for w in ["3d", "render", "blender", "octane", "cinema"]):
        return "3d"
    if any(w in lower for w in ["painting", "oil", "watercolor", "canvas", "brush"]):
        return "painting"
    if any(w in lower for w in ["product", "commercial", "studio", "white background"]):
        return "product"
    if any(w in lower for w in ["art", "illustration", "concept", "digital"]):
        return "art"
    return "photo"  # default


def enhance_prompt(prompt: str) -> str:
    content_type = detect_content_type(prompt)
    route = CONTENT_ROUTER[content_type]
    lower = prompt.lower()

    enhancements = [kw for kw in route["add"] if kw.lower() not in lower]

    if enhancements:
        enhanced = f"{prompt}, {', '.join(enhancements)}"
    else:
        enhanced = prompt

    enhanced += f" (avoid: {route['negative']})"
    return enhanced


# ── Aesthetic Quality Scoring ─────────────────────────────

def score_aesthetics(image_bytes: bytes) -> dict:
    """Score image on aesthetic qualities. Returns dict with scores and total."""
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    arr = np.array(img, dtype=np.float64)

    scores = {}

    # 1. Color Harmony (0-20) — variance in hue indicates variety
    hsv = img.convert("HSV")
    hsv_arr = np.array(hsv)
    hue_std = float(np.std(hsv_arr[:, :, 0]))
    sat_mean = float(np.mean(hsv_arr[:, :, 1]))
    color_score = min(20, int(hue_std / 8 + sat_mean / 30))
    scores["color_harmony"] = color_score

    # 2. Composition (0-20) — rule of thirds check
    gray = np.mean(arr, axis=2)
    h, w = gray.shape
    # Divide into 3x3 grid
    third_h, third_w = h // 3, w // 3
    # Check if edges have detail (not blank)
    edge_density = float(np.mean(gray[:third_h, :] > 30) + np.mean(gray[-third_h:, :] > 30) +
                         np.mean(gray[:, :third_w] > 30) + np.mean(gray[:, -third_w:] > 30)) / 4
    # Check center has content
    center_density = float(np.mean(gray[third_h:2*third_h, third_w:2*third_w] > 50))
    comp_score = min(20, int(edge_density * 8 + center_density * 12))
    scores["composition"] = comp_score

    # 3. Detail Density (0-20) — Laplacian variance
    gray_img = img.convert("L")
    gray_arr = np.array(gray_img, dtype=np.float64)
    laplacian = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], dtype=np.float64)
    lap = gray_arr[1:-1, 1:-1] * laplacian[1, 1]
    lap += gray_arr[:-2, 1:-1] * laplacian[0, 1]
    lap += gray_arr[2:, 1:-1] * laplacian[2, 1]
    lap += gray_arr[1:-1, :-2] * laplacian[1, 0]
    lap += gray_arr[1:-1, 2:] * laplacian[1, 2]
    lap_var = float(np.var(lap))
    detail_score = min(20, int(lap_var / 10))
    scores["detail"] = detail_score

    # 4. Brightness Balance (0-20)
    brightness = float(np.mean(arr))
    if 40 < brightness < 220:
        bright_score = 20
    elif 20 < brightness < 240:
        bright_score = 12
    else:
        bright_score = 4
    scores["brightness"] = bright_score

    # 5. Contrast (0-20) — standard deviation of luminance
    contrast = float(np.std(gray))
    contrast_score = min(20, int(contrast / 8))
    scores["contrast"] = contrast_score

    total = sum(scores.values())
    scores["total"] = total
    scores["max"] = 100

    return scores


# ── Vision Critique (MIMO) ────────────────────────────────

def vision_critique(image_bytes: bytes, prompt: str, scores: dict) -> str:
    """Send image to MIMO for visual critique. Returns critique text."""
    try:
        from ..agent.llm import NallyLLM
        llm = NallyLLM()
        llm._ensure_client()

        # Encode image to base64
        b64 = base64.b64encode(image_bytes).decode("utf-8")

        critique_prompt = f"""You are an expert art director critiquing an AI-generated image.

The image was generated with this prompt: "{prompt}"

Quality metrics:
- Color harmony: {scores.get('color_harmony', 0)}/20
- Composition: {scores.get('composition', 0)}/20
- Detail: {scores.get('detail', 0)}/20
- Brightness: {scores.get('brightness', 0)}/20
- Contrast: {scores.get('contrast', 0)}/20
- Total: {scores.get('total', 0)}/100

Your task:
1. Look at the image and identify what's wrong (blurry, bad composition, missing elements, wrong style, etc.)
2. Be specific about what needs to change
3. Suggest exactly how to fix the prompt

Respond in this EXACT JSON format:
{{
    "issues": ["issue 1", "issue 2"],
    "verdict": "pass" or "fail",
    "improved_prompt": "the complete improved prompt to generate a better image"
}}

Be concise. Max 3 issues. The improved prompt should be ready to use directly."""

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": critique_prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"}
                    }
                ]
            }
        ]

        response = llm.client.chat.completions.create(
            model=llm.model,
            messages=messages,
            temperature=0.3,
            max_tokens=500,
        )

        return response.choices[0].message.content

    except Exception as e:
        logger.warning(f"Vision critique failed: {e}")
        return ""


def parse_critique(critique_text: str) -> dict:
    """Parse MIMO's critique response into structured data."""
    try:
        # Try to extract JSON from response
        if "```json" in critique_text:
            json_str = critique_text.split("```json")[1].split("```")[0].strip()
        elif "```" in critique_text:
            json_str = critique_text.split("```")[1].split("```")[0].strip()
        else:
            # Try to find JSON object
            start = critique_text.find("{")
            end = critique_text.rfind("}") + 1
            if start >= 0 and end > start:
                json_str = critique_text[start:end]
            else:
                return {"issues": ["Unable to parse critique"], "verdict": "fail", "improved_prompt": ""}

        return json.loads(json_str)
    except Exception as e:
        logger.warning(f"Failed to parse critique: {e}")
        return {"issues": ["Parse error"], "verdict": "fail", "improved_prompt": ""}


# ── Pollinations API ──────────────────────────────────────

def generate_pollinations(
    prompt: str,
    width: int = 1024,
    height: int = 1024,
    seed: int = None,
    model: str = "flux",
) -> bytes:
    enhanced = enhance_prompt(prompt)
    encoded = urllib.parse.quote(enhanced)
    params = {"width": width, "height": height, "model": model, "nologo": "true"}
    if seed is not None:
        params["seed"] = seed

    query = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"https://image.pollinations.ai/prompt/{encoded}?{query}"

    logger.info(f"Generating: {enhanced[:80]}... ({width}x{height})")
    req = urllib.request.Request(url, headers={"User-Agent": "NALLY/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


# ── Upscaling ─────────────────────────────────────────────

def upscale_image(image_bytes: bytes, target_size: int = 2048) -> bytes:
    img = Image.open(io.BytesIO(image_bytes))
    orig_w, orig_h = img.size

    if orig_w >= orig_h:
        new_w, new_h = target_size, int(orig_h * (target_size / orig_w))
    else:
        new_w, new_h = int(orig_w * (target_size / orig_h)), target_size

    upscaled = img.resize((new_w, new_h), Image.LANCZOS)

    # Sharpen after upscale
    upscaled = upscaled.filter(ImageFilter.SHARPEN)
    enhancer = ImageEnhance.Contrast(upscaled)
    upscaled = enhancer.enhance(1.1)

    if upscaled.mode == "RGBA":
        bg = Image.new("RGB", upscaled.size, (0, 0, 0))
        bg.paste(upscaled, mask=upscaled.split()[3])
        upscaled = bg
    elif upscaled.mode != "RGB":
        upscaled = upscaled.convert("RGB")

    buf = io.BytesIO()
    upscaled.save(buf, format="PNG", quality=95)
    return buf.getvalue()


# ── Main Tool ─────────────────────────────────────────────

class ImageGen(Tool):
    """Generate images with vision-guided quality loop. NALLY sees and critiques her own work."""

    def __init__(self):
        super().__init__(
            name="generate_image",
            description="Generate an image from a text description. NALLY generates, SEES the result, critiques it, and regenerates until quality is good. Supports upscaling.",
            permission="safe",
            parameters={
                "prompt": {
                    "type": "string",
                    "description": "Description of the image to generate",
                    "required": True,
                },
                "width": {
                    "type": "integer",
                    "description": "Image width (default 1024)",
                    "default": 1024,
                },
                "height": {
                    "type": "integer",
                    "description": "Image height (default 1024)",
                    "default": 1024,
                },
                "model": {
                    "type": "string",
                    "description": "Model: flux (default), turbo, klein",
                    "default": "flux",
                },
                "upscale": {
                    "type": "integer",
                    "description": "Upscale target (0=off, 2048=2K, 4096=4K)",
                    "default": 0,
                },
                "max_attempts": {
                    "type": "integer",
                    "description": "Max attempts with vision critique (1-5, default 3)",
                    "default": 3,
                },
            },
        )

    def execute(
        self,
        prompt: str,
        width: int = 1024,
        height: int = 1024,
        model: str = "flux",
        upscale: int = 0,
        max_attempts: int = 3,
    ) -> str:
        width = max(256, min(2048, width))
        height = max(256, min(2048, height))
        max_attempts = max(1, min(5, max_attempts))

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = int(time.time())

        best_image = None
        best_score = 0
        best_file = None
        best_critique = ""
        current_prompt = prompt
        logs = []

        for attempt in range(1, max_attempts + 1):
            # 1. Generate
            try:
                image_bytes = generate_pollinations(
                    prompt=current_prompt,
                    width=width,
                    height=height,
                    model=model,
                    seed=random.randint(1, 999999),
                )
            except Exception as e:
                logger.error(f"Attempt {attempt} generation failed: {e}")
                logs.append(f"Attempt {attempt}: FAILED — {e}")
                continue

            # 2. Score aesthetics
            scores = score_aesthetics(image_bytes)
            total = scores["total"]

            # 3. Save attempt
            attempt_file = DATA_DIR / f"img_{timestamp}_{attempt}.png"
            attempt_file.write_bytes(image_bytes)

            log_entry = f"Attempt {attempt}: {total}/100 (color:{scores['color_harmony']} comp:{scores['composition']} detail:{scores['detail']} bright:{scores['brightness']} contrast:{scores['contrast']})"
            logs.append(log_entry)
            logger.info(log_entry)

            # 4. Vision critique (if score < 80 and more attempts remain)
            critique = ""
            improved_prompt = ""
            if total < 80 and attempt < max_attempts:
                critique = vision_critique(image_bytes, current_prompt, scores)
                parsed = parse_critique(critique)
                if parsed.get("verdict") == "pass":
                    logs.append(f"  Vision: PASS — {parsed.get('issues', [])}")
                    if total > best_score:
                        best_image = image_bytes
                        best_score = total
                        best_file = attempt_file
                        best_critique = critique
                    break
                elif parsed.get("improved_prompt"):
                    improved_prompt = parsed["improved_prompt"]
                    logs.append(f"  Vision: FAIL — {parsed.get('issues', [])}")
                    logs.append(f"  New prompt: {improved_prompt[:100]}...")

            # 5. Track best
            if total > best_score:
                best_image = image_bytes
                best_score = total
                best_file = attempt_file
                best_critique = critique

            # 6. Check if good enough
            if total >= 80:
                logs.append(f"Quality passed at attempt {attempt}")
                break

            # 7. Prepare next attempt
            if improved_prompt:
                current_prompt = improved_prompt
            elif attempt < max_attempts:
                # Fallback: add refinement keywords
                refinements = ["extremely detailed", "high quality", "sharp focus", "professional"]
                current_prompt = f"{prompt}, {random.choice(refinements)}"

            time.sleep(1)

        # 8. Upscale best if requested
        if best_image and upscale and upscale > max(width, height):
            try:
                best_image = upscale_image(best_image, target_size=upscale)
                final_file = DATA_DIR / f"img_{timestamp}_final.png"
                final_file.write_bytes(best_image)
                best_file = final_file
            except Exception as e:
                logger.warning(f"Upscaling failed: {e}")

        # 9. Build output
        if not best_image:
            return "Error: All generation attempts failed"

        best_size_kb = len(best_image) / 1024

        result = f"Image generated (score {best_score}/100)\n"
        result += f"Saved to: {best_file}\n"
        result += f"Size: {best_size_kb:.1f} KB\n"
        result += f"Attempts: {len(logs)}\n\n"

        result += "--- Quality Log ---\n"
        for log in logs:
            result += f"{log}\n"

        if best_critique:
            result += f"\n--- Vision Critique ---\n{best_critique[:500]}\n"

        result += f"\nIMAGE_FILE:{best_file}"
        return result


def register():
    registry.register(ImageGen())
