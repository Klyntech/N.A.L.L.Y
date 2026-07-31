---
name: image-gen
description: Generate images from text prompts with auto-enhancement and upscaling. Use when asked to create, draw, or generate images, illustrations, art, logos, or visual content.
allowed-tools: generate_image
---

# Image Generation

Generate high-quality images from text descriptions using AI.

## Prompt Writing Rules

### Be Specific, Not Vague
```
Bad:  "a cat"
Good: "a fluffy orange tabby cat sitting on a windowsill, looking out at rain, warm indoor lighting, photorealistic"
```

### Structure Your Prompts
1. **Subject** — what is the main focus?
2. **Action/Pose** — what is it doing?
3. **Environment** — where is it?
4. **Lighting** — what's the lighting like?
5. **Style** — what aesthetic?
6. **Quality** — resolution/quality boosters

### Style Keywords

| Style | Keywords |
|-------|----------|
| Photorealistic | photorealistic, hyperrealistic, DSLR photo, 85mm lens, bokeh |
| Anime | anime style, studio ghibli, vibrant colors, cel shading |
| 3D Render | octane render, cinema 4d, volumetric lighting, ray tracing |
| Digital Art | digital painting, concept art, artstation, deviantart |
| Oil Painting | oil on canvas, classical painting, renaissance style |
| Watercolor | watercolor painting, soft edges, pastel colors |
| Pixel Art | pixel art, 16-bit, retro game style, sprite |
| Logo | minimalist logo, flat design, vector style, clean lines |

### Lighting Keywords
- Golden hour, blue hour, studio lighting, dramatic lighting
- Neon glow, bioluminescent, candlelight, moonlight
- Backlit, rim lighting, soft diffused, harsh shadows

### Quality Boosters
- 8k, 4k, ultra detailed, sharp focus, professional
- Masterpiece, best quality, award winning, highly detailed

## Upscaling

Use the `upscale` parameter to generate at higher resolution:
- `upscale: 2048` — 2K output (good for social media, prints)
- `upscale: 4096` — 4K output (high detail, large prints)

Default generates at 1024x1024. Upscaling takes extra time but produces sharper results.

## Common Requests

### Product Photography
```
product photography of [item], studio lighting, white background, 
high-end commercial photography, 8k, sharp focus
```

### Logo Design
```
minimalist logo design for [brand], flat vector style, clean lines, 
simple color palette, professional, white background
```

### Character Art
```
character concept art of [description], full body, dynamic pose, 
detailed costume, [style] style, artstation quality
```

### Landscape
```
breathtaking landscape of [location], golden hour, dramatic sky, 
ultra wide angle, National Geographic photography, 8k
```

### Abstract/Artistic
```
abstract art of [concept], [color palette] colors, [style] style, 
high resolution, gallery quality
```

## Output

The tool returns:
- Generated image file path
- Image preview in the tool card
- Click to open full resolution

## Tips
- The system auto-enhances your prompts for better quality
- Use `seed` parameter for reproducible results
- Be specific about what you WANT, not what you DON'T want
- For multiple variations, generate with different seeds
- Upscale when quality matters more than speed
