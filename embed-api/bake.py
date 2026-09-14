#!/usr/bin/env python3
"""Bake ONNX model into image at Docker build time.

Strategy:
1. Download pre-exported ONNX from Xenova/all-MiniLM-L6-v2 (fastest)
2. Fallback: export via torch.onnx.export + sentence-transformers

Produces /app/model/ with tokenizer + model.onnx.
"""
import os
import shutil
import sys


MODEL_NAME = os.getenv("EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
MODEL_PATH = os.getenv("EMBED_MODEL_PATH", "/app/model")


def download_onnx():
    """Download pre-exported ONNX from HuggingFace."""
    from huggingface_hub import snapshot_download

    sources = ["Xenova/all-MiniLM-L6-v2", "optimum/all-MiniLM-L6-v2"]
    for source in sources:
        try:
            print(f"[embed-api bake] Downloading pre-exported ONNX from {source} ...")
            path = snapshot_download(source)
            print(f"[embed-api bake] Downloaded to {path}")

            # Recursively find all .onnx files and copy them + tokenizer files
            onnx_files = []
            for root, dirs, files in os.walk(path):
                for f in files:
                    src = os.path.join(root, f)
                    rel = os.path.relpath(src, path)
                    dst = os.path.join(MODEL_PATH, rel)
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy2(src, dst)
                    if f.endswith(".onnx"):
                        onnx_files.append(dst)
                        print(f"[embed-api bake] Found ONNX: {rel} ({os.path.getsize(src) / 1024 / 1024:.1f}MB)")

            if onnx_files:
                print(f"[embed-api bake] Copied {len(onnx_files)} ONNX file(s) to {MODEL_PATH}")
                return True
            else:
                print(f"[embed-api bake] No .onnx files found in {source}")
                # Clean up non-ONNX files we may have copied
                for item in os.listdir(MODEL_PATH):
                    if item.endswith(".onnx"):
                        continue
                    p = os.path.join(MODEL_PATH, item)
                    if os.path.isdir(p):
                        shutil.rmtree(p)
                    else:
                        os.remove(p)
        except Exception as e:
            print(f"[embed-api bake] {source} failed: {e}")
    return False


def export_onnx():
    """Export via torch.onnx.export (needs torch + sentence-transformers)."""
    import gc
    import torch
    from sentence_transformers import SentenceTransformer

    print(f"[embed-api bake] Exporting {MODEL_NAME} via torch.onnx.export ...")
    model = SentenceTransformer(MODEL_NAME)
    tokenizer = model.tokenizer

    # Get the transformer auto_model
    auto_model = model[0].auto_model
    auto_model.eval()

    dummy = tokenizer("hello world", return_tensors="pt", padding=True, truncation=True, max_length=128)

    onnx_path = os.path.join(MODEL_PATH, "model.onnx")

    # Use torch.onnx.export directly (no onnxscript needed for opset 14)
    torch.onnx.export(
        auto_model,
        (dummy["input_ids"], dummy["attention_mask"]),
        onnx_path,
        input_names=["input_ids", "attention_mask"],
        output_names=["token_embeddings"],
        dynamic_axes={
            "input_ids": {0: "batch", 1: "seq"},
            "attention_mask": {0: "batch", 1: "seq"},
            "token_embeddings": {0: "batch", 1: "seq"},
        },
        opset_version=14,
    )

    tokenizer.save_pretrained(MODEL_PATH)
    print(f"[embed-api bake] ONNX exported to {onnx_path}")

    # Free memory
    del model, auto_model, tokenizer, torch
    gc.collect()
    return True


def main():
    print(f"[embed-api bake] Baking ONNX model to {MODEL_PATH}")
    os.makedirs(MODEL_PATH, exist_ok=True)

    # Try 1: download pre-exported ONNX
    if download_onnx():
        pass
    # Try 2: export via torch
    elif export_onnx():
        pass
    else:
        print("[embed-api bake] FAILED: all methods failed", file=sys.stderr)
        sys.exit(1)

    # Report
    print(f"[embed-api bake] Files in {MODEL_PATH}:")
    for f in sorted(os.listdir(MODEL_PATH)):
        fpath = os.path.join(MODEL_PATH, f)
        if os.path.isfile(fpath):
            size = os.path.getsize(fpath)
            print(f"  {f}: {size / 1024 / 1024:.1f}MB" if size > 1024 * 1024 else f"  {f}: {size / 1024:.0f}KB")

    print("[embed-api bake] Bake complete")


if __name__ == "__main__":
    main()
