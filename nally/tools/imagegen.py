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
from PIL import Image, ImageEnhance, ImageFilter

from .registry import Tool, registry

logger = logging.getLogger("nally.tools.imagegen")

DATA_DIR = Path(__file__).parent.parent.parent / "data" / "generated"

# ── Content-Type Prompt Router (with smart model selection) ──

CONTENT_ROUTER = {
    "logo": {
        "model": "flux",
        "add": ["flat design", "vector style", "clean lines", "minimalist", "simple", "white background"],
        "remove": ["photorealistic", "detailed", "8k", "texture", "shadows", "depth of field"],
        "negative": "realistic, 3d, texture, photo, shadows, complex, busy, blurry",
    },
    "photo": {
        "model": "gpt-image-2",
        "add": ["photorealistic", "DSLR photo", "85mm lens", "natural lighting", "bokeh", "sharp focus"],
        "remove": ["cartoon", "anime", "painting", "illustration", "flat"],
        "negative": "cartoon, anime, painting, illustration, flat, drawing, sketch, blurry",
    },
    "art": {
        "model": "flux",
        "add": ["masterpiece", "artstation", "digital painting", "concept art", "highly detailed", "professional"],
        "remove": ["photo", "realistic", "camera", "DSLR"],
        "negative": "photo, realistic, camera, DSLR, photograph, bad anatomy, blurry",
    },
    "anime": {
        "model": "flux",
        "add": ["anime style", "studio ghibli", "vibrant colors", "cel shading", "clean lines", "high quality"],
        "remove": ["realistic", "photo", "3d", "texture"],
        "negative": "realistic, photo, 3d, texture, blurry, low quality, bad anatomy",
    },
    "3d": {
        "model": "gptimage-large",
        "add": ["octane render", "cinema 4d", "volumetric lighting", "ray tracing", "high detail", "8k"],
        "remove": ["photo", "2d", "flat", "sketch"],
        "negative": "2d, flat, sketch, drawing, low poly, blurry, low quality",
    },
    "painting": {
        "model": "flux",
        "add": ["oil painting", "canvas texture", "brush strokes", "classical", "museum quality", "masterpiece"],
        "remove": ["photo", "digital", "3d", "render"],
        "negative": "photo, digital, 3d, render, camera, realistic, blurry",
    },
    "product": {
        "model": "gptimage",
        "add": ["product photography", "studio lighting", "white background", "commercial", "high-end", "sharp focus"],
        "remove": ["outdoor", "natural", "messy", "busy"],
        "negative": "outdoor, natural, messy, busy, blurry, text, watermark, low quality",
    },
    "text": {
        "model": "gptimage-large",
        "add": ["clear text", "readable typography", "professional layout", "high resolution"],
        "remove": ["blurry", "distorted", "abstract"],
        "negative": "blurry, distorted, unreadable text, misspelled, low quality",
    },
    "default": {
        "model": "zimage",
        "add": ["high quality", "detailed", "sharp focus", "professional"],
        "remove": [],
        "negative": "blurry, low quality, watermark, text",
    },
}


def detect_content_type(prompt: str) -> str:
    lower = prompt.lower()
    # Text-in-image detection (check before other categories)
    if any(
        w in lower
        for w in [
            "text says",
            "text:",
            "write",
            "sign says",
            "label says",
            "with text",
            "typography",
            "lettering",
            "font",
        ]
    ):
        return "text"
    if any(w in lower for w in ["logo", "icon", "brand", "emblem", "symbol"]):
        return "logo"
    if any(
        w in lower
        for w in ["photo", "realistic", "portrait", "landscape", "camera", "dslr", "photograph", "hyperrealistic"]
    ):
        return "photo"
    if any(w in lower for w in ["anime", "cartoon", "manga", "ghibli", "chibi"]):
        return "anime"
    if any(w in lower for w in ["3d", "render", "blender", "octane", "cinema"]):
        return "3d"
    if any(w in lower for w in ["painting", "oil", "watercolor", "canvas", "brush", "acrylic", "pastel"]):
        return "painting"
    if any(w in lower for w in ["product", "commercial", "studio", "white background", "ecommerce", "e-commerce"]):
        return "product"
    if any(w in lower for w in ["art", "illustration", "concept", "digital"]):
        return "art"
    return "default"


def get_model_for_content(content_type: str) -> str:
    """Return the best free Pollinations model for this content type."""
    return CONTENT_ROUTER.get(content_type, CONTENT_ROUTER["default"])["model"]


def enhance_prompt(prompt: str, content_type: str = None) -> str:
    """Natural-language prompt enhancement for Flux (not tag lists)."""
    if content_type is None:
        content_type = detect_content_type(prompt)

    # Flux uses a T5 encoder — write natural sentences, not tag soup
    style_map = {
        "logo": "A clean minimalist logo design with flat vector style and simple color palette on a white background",
        "photo": "A photorealistic image shot on a DSLR with an 85mm lens, natural lighting with soft bokeh, sharp focus",
        "art": "A detailed digital painting in concept art style, rich colors and intricate details, artstation quality",
        "anime": "An anime illustration with vibrant colors and clean cel-shaded lines, studio ghibli inspired",
        "3d": "A 3D render with volumetric lighting and ray tracing, cinema 4d style, high detail",
        "painting": "An oil painting on canvas with visible brush strokes, classical museum quality masterpiece",
        "product": "Product photography with studio lighting on a clean white background, commercial high-end look",
        "text": "A design with clear readable text and professional typography layout",
        "default": "A highly detailed, sharp, professional image with excellent composition",
    }

    style = style_map.get(content_type, style_map["default"])

    # Build a natural sentence prompt
    enhanced = f"{prompt}. {style}, beautiful lighting, detailed, sharp focus, 8k resolution"
    return enhanced


# ── LLM-Powered Prompt Enhancement ────────────────────────


def enhance_prompt_llm(prompt: str, content_type: str = None) -> str:
    """Use Pollinations free text model to expand short prompts into detailed natural-language descriptions."""
    if content_type is None:
        content_type = detect_content_type(prompt)

    # Only expand short prompts — long ones are already detailed enough
    if len(prompt) > 40:
        return enhance_prompt(prompt, content_type)

    try:
        system = (
            "You are an expert prompt engineer for AI image generation using Flux. "
            "Rewrite this short idea into a detailed, natural-language image prompt. "
            "Structure: subject detail, composition, camera/lens, lighting, color palette, mood, art style. "
            "One flowing paragraph. No bullet points, no tags, no preamble."
        )
        full_prompt = f"{system}\n\nEnhance: {prompt}"
        encoded = urllib.parse.quote(full_prompt)
        url = f"https://text.pollinations.ai/{encoded}"

        logger.info(f"Expanding prompt via Pollinations text: '{prompt}'")
        req = urllib.request.Request(url, headers={"User-Agent": "NALLY/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            enhanced = resp.read().decode("utf-8").strip()

        # Clean up the response
        enhanced = enhanced.strip('"').strip("'")
        # Remove any markdown formatting
        if enhanced.startswith("```"):
            enhanced = enhanced.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        if enhanced and len(enhanced) > 15 and len(enhanced) < 300:
            logger.info(f"LLM prompt: '{prompt}' -> '{enhanced[:100]}...'")
            return enhanced

    except Exception as e:
        logger.warning(f"Pollinations text expansion failed: {e}")

    return enhance_prompt(prompt, content_type)


# ── Aesthetic Quality Scoring (expanded) ───────────────────


def score_aesthetics(image_bytes: bytes) -> dict:
    """Score image on 8 aesthetic qualities. Returns dict with scores and total (0-100)."""
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    arr = np.array(img, dtype=np.float64)

    scores = {}

    # 1. Color Harmony (0-15) — hue variety + saturation balance
    hsv = img.convert("HSV")
    hsv_arr = np.array(hsv)
    hue_std = float(np.std(hsv_arr[:, :, 0]))
    sat_mean = float(np.mean(hsv_arr[:, :, 1]))
    color_score = min(15, int(hue_std / 10 + sat_mean / 25))
    scores["color_harmony"] = color_score

    # 2. Composition (0-20) — rule of thirds + center interest
    gray = np.mean(arr, axis=2)
    h, w = gray.shape
    third_h, third_w = h // 3, w // 3
    # Edge regions should have some content (not blank)
    edge_density = (
        float(
            np.mean(gray[:third_h, :] > 30)
            + np.mean(gray[-third_h:, :] > 30)
            + np.mean(gray[:, :third_w] > 30)
            + np.mean(gray[:, -third_w:] > 30)
        )
        / 4
    )
    # Center region should be the focal point
    center_density = float(np.mean(gray[third_h : 2 * third_h, third_w : 2 * third_w] > 50))
    # Golden ratio check — subject near 0.618 intersection
    golden_h, golden_w = int(h * 0.618), int(w * 0.618)
    golden_region = float(np.mean(gray[golden_h - 20 : golden_h + 20, golden_w - 20 : golden_w + 20] > 50))
    comp_score = min(20, int(edge_density * 6 + center_density * 8 + golden_region * 6))
    scores["composition"] = comp_score

    # 3. Detail Density (0-15) — Laplacian variance (sharpness)
    gray_img = img.convert("L")
    gray_arr = np.array(gray_img, dtype=np.float64)
    laplacian = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], dtype=np.float64)
    lap = gray_arr[1:-1, 1:-1] * laplacian[1, 1]
    lap += gray_arr[:-2, 1:-1] * laplacian[0, 1]
    lap += gray_arr[2:, 1:-1] * laplacian[2, 1]
    lap += gray_arr[1:-1, :-2] * laplacian[1, 0]
    lap += gray_arr[1:-1, 2:] * laplacian[1, 2]
    lap_var = float(np.var(lap))
    detail_score = min(15, int(lap_var / 12))
    scores["detail"] = detail_score

    # 4. Brightness Balance (0-10)
    brightness = float(np.mean(arr))
    if 50 < brightness < 210:
        bright_score = 10
    elif 25 < brightness < 235:
        bright_score = 6
    else:
        bright_score = 2
    scores["brightness"] = bright_score

    # 5. Contrast (0-10)
    contrast = float(np.std(gray))
    contrast_score = min(10, int(contrast / 7))
    scores["contrast"] = contrast_score

    # 6. Color Palette Coherence (0-10) — k-means-like clustering
    # Reshape to list of pixels, sample for speed
    pixels = arr.reshape(-1, 3)
    if len(pixels) > 10000:
        indices = np.random.choice(len(pixels), 10000, replace=False)
        pixels = pixels[indices]
    # Find unique color clusters by rounding to nearest 32
    rounded = (pixels / 32).astype(int) * 32
    unique_colors = len(np.unique(rounded, axis=0))
    # Fewer unique colors = more coherent palette (but not too few = boring)
    if 5 <= unique_colors <= 30:
        palette_score = 10
    elif 3 <= unique_colors <= 50:
        palette_score = 7
    elif unique_colors <= 80:
        palette_score = 4
    else:
        palette_score = 2
    scores["palette_coherence"] = palette_score

    # 7. Noise Level (0-10) — low noise = good
    # Estimate noise from high-frequency content
    noise_region = gray_arr[10:30, 10:30]  # corner sample
    noise_std = float(np.std(noise_region))
    if noise_std < 10:
        noise_score = 10  # clean
    elif noise_std < 20:
        noise_score = 7
    elif noise_std < 35:
        noise_score = 4
    else:
        noise_score = 1  # noisy
    scores["noise"] = noise_score

    # 8. Dynamic Range (0-10) — using full tonal range
    p5 = float(np.percentile(gray, 5))
    p95 = float(np.percentile(gray, 95))
    dynamic_range = p95 - p5
    if dynamic_range > 150:
        dynamic_score = 10
    elif dynamic_range > 100:
        dynamic_score = 7
    elif dynamic_range > 60:
        dynamic_score = 4
    else:
        dynamic_score = 1
    scores["dynamic_range"] = dynamic_score

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

        b64 = base64.b64encode(image_bytes).decode("utf-8")

        critique_prompt = f"""You are an expert art director critiquing an AI-generated image.

The image was generated with this prompt: "{prompt}"

Quality metrics:
- Color harmony: {scores.get("color_harmony", 0)}/15
- Composition: {scores.get("composition", 0)}/20
- Detail: {scores.get("detail", 0)}/15
- Brightness: {scores.get("brightness", 0)}/10
- Contrast: {scores.get("contrast", 0)}/10
- Palette coherence: {scores.get("palette_coherence", 0)}/10
- Noise: {scores.get("noise", 0)}/10
- Dynamic range: {scores.get("dynamic_range", 0)}/10
- Total: {scores.get("total", 0)}/100

Your task:
1. Look at the image and identify what's wrong (blurry, bad composition, missing elements, wrong style, artifacts, text errors, etc.)
2. Be specific about what needs to change
3. Suggest exactly how to fix the prompt
4. If the image is good, say "pass"

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
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                ],
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
    width: int = 1344,
    height: int = 1344,
    seed: int = None,
    model: str = "flux",
) -> bytes:
    """Generate image via Pollinations API."""
    enhanced = enhance_prompt(prompt)
    encoded = urllib.parse.quote(enhanced)
    params = {"width": width, "height": height, "model": model, "nologo": "true"}
    if seed is not None and seed >= 0:
        params["seed"] = seed

    query = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"https://image.pollinations.ai/prompt/{encoded}?{query}"

    logger.info(f"Generating: {enhanced[:80]}... ({width}x{height}, model={model})")
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

    # Unsharp mask (more natural than basic sharpen)
    upscaled = upscaled.filter(ImageFilter.UnsharpMask(radius=2, percent=150, threshold=3))

    # Subtle contrast boost
    enhancer = ImageEnhance.Contrast(upscaled)
    upscaled = enhancer.enhance(1.08)

    # Subtle color saturation boost
    enhancer = ImageEnhance.Color(upscaled)
    upscaled = enhancer.enhance(1.05)

    if upscaled.mode == "RGBA":
        bg = Image.new("RGB", upscaled.size, (0, 0, 0))
        bg.paste(upscaled, mask=upscaled.split()[3])
        upscaled = bg
    elif upscaled.mode != "RGB":
        upscaled = upscaled.convert("RGB")

    buf = io.BytesIO()
    upscaled.save(buf, format="PNG", quality=95)
    return buf.getvalue()


# ── Smart Seed Strategy ───────────────────────────────────


def pick_seeds(best_seed: int = None, attempt: int = 1) -> list:
    """Return a list of seeds to try. Uses fixed seed for consistency, random on retry."""
    if attempt == 1:
        return [42]  # Fixed seed for consistent, reproducible results
    elif attempt == 2:
        return [random.randint(1, 999999)]  # Random on second try
    elif best_seed is not None:
        # Explore nearby variations of the best seed
        offset = random.randint(-50, 50)
        return [best_seed + offset]
    else:
        return [random.randint(1, 999999)]


# ── Main Tool ─────────────────────────────────────────────


class ImageGen(Tool):
    """Generate images with vision-guided quality loop. NALLY sees and critiques her own work."""

    def __init__(self):
        super().__init__(
            name="generate_image",
            description="Generate an image from a text description. NALLY generates, SEES the result, critiques it, and regenerates until quality is good. Supports upscaling and img2img refinement.",
            permission="safe",
            parameters={
                "prompt": {
                    "type": "string",
                    "description": "Description of the image to generate",
                    "required": True,
                },
                "width": {
                    "type": "integer",
                    "description": "Image width (default 1344)",
                    "default": 1344,
                },
                "height": {
                    "type": "integer",
                    "description": "Image height (default 1344)",
                    "default": 1344,
                },
                "model": {
                    "type": "string",
                    "description": "Model: auto (default, picks best for content), flux, zimage, dreamshaper, klein, gptimage, gptimage-large, gpt-image-2, kontext, nova-canvas",
                    "default": "auto",
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
                "enhance": {
                    "type": "boolean",
                    "description": "Use LLM to enhance prompt (default true). Set false for raw prompt.",
                    "default": True,
                },
            },
        )

    def execute(
        self,
        prompt: str,
        width: int = 1344,
        height: int = 1344,
        model: str = "auto",
        upscale: int = 0,
        max_attempts: int = 3,
        enhance: bool = True,
    ) -> str:
        width = max(256, min(2048, width))
        height = max(256, min(2048, height))
        max_attempts = max(1, min(5, max_attempts))

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = int(time.time())

        # Detect content type and pick model
        content_type = detect_content_type(prompt)
        if model == "auto":
            model = get_model_for_content(content_type)
            logger.info(f"Auto-selected model: {model} for content type: {content_type}")

        # Enhance prompt
        if enhance:
            current_prompt = enhance_prompt_llm(prompt, content_type)
        else:
            current_prompt = enhance_prompt(prompt, content_type)

        best_image = None
        best_score = 0
        best_file = None
        best_critique = ""
        best_seed = None
        logs = []

        logs.append(f"Content type: {content_type} | Model: {model}")
        logs.append(f"Enhanced prompt: {current_prompt[:120]}...")

        for attempt in range(1, max_attempts + 1):
            # 1. Pick seed
            seeds = pick_seeds(best_seed, attempt)
            seed = seeds[0]

            # 2. Generate
            try:
                image_bytes = generate_pollinations(
                    prompt=current_prompt,
                    width=width,
                    height=height,
                    model=model,
                    seed=seed,
                )
            except Exception as e:
                logger.error(f"Attempt {attempt} generation failed: {e}")
                logs.append(f"Attempt {attempt}: FAILED — {e}")
                continue

            # 3. Score aesthetics
            scores = score_aesthetics(image_bytes)
            total = scores["total"]

            # 4. Save attempt
            attempt_file = DATA_DIR / f"img_{timestamp}_{attempt}.png"
            attempt_file.write_bytes(image_bytes)

            score_parts = " ".join(f"{k}:{v}" for k, v in scores.items() if k not in ("total", "max"))
            log_entry = f"Attempt {attempt}: {total}/100 ({score_parts})"
            logs.append(log_entry)
            logger.info(log_entry)

            # 5. Vision critique (if score < 80 and more attempts remain)
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
                        best_seed = seed
                    break
                elif parsed.get("improved_prompt"):
                    improved_prompt = parsed["improved_prompt"]
                    logs.append(f"  Vision: FAIL — {parsed.get('issues', [])}")
                    logs.append(f"  New prompt: {improved_prompt[:100]}...")

            # 6. Track best
            if total > best_score:
                best_image = image_bytes
                best_score = total
                best_file = attempt_file
                best_critique = critique
                best_seed = seed

            # 7. Check if good enough
            if total >= 80:
                logs.append(f"Quality passed at attempt {attempt}")
                break

            # 8. Prepare next attempt
            if improved_prompt:
                current_prompt = improved_prompt
            elif attempt < max_attempts:
                refinements = ["extremely detailed", "high quality", "sharp focus", "professional"]
                current_prompt = f"{prompt}, {random.choice(refinements)}"

            time.sleep(1)

        # 9. Upscale best if requested
        if best_image and upscale and upscale > max(width, height):
            try:
                best_image = upscale_image(best_image, target_size=upscale)
                final_file = DATA_DIR / f"img_{timestamp}_final.png"
                final_file.write_bytes(best_image)
                best_file = final_file
            except Exception as e:
                logger.warning(f"Upscaling failed: {e}")

        # 11. Build output
        if not best_image:
            return "Error: All generation attempts failed"

        best_size_kb = len(best_image) / 1024

        result = f"Image generated (score {best_score}/100)\n"
        result += f"Model: {model}\n"
        result += f"Saved to: {best_file}\n"
        result += f"Size: {best_size_kb:.1f} KB\n"
        result += f"Attempts: {len([l for l in logs if l.startswith('Attempt')])}\n\n"

        result += "--- Quality Log ---\n"
        for log in logs:
            result += f"{log}\n"

        if best_critique:
            result += f"\n--- Vision Critique ---\n{best_critique[:500]}\n"

        result += f"\nIMAGE_FILE:{best_file}"
        return result


def register():
    registry.register(ImageGen())
