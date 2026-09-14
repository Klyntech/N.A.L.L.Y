#!/usr/bin/env python3
"""Bake ONNX model into image at Docker build time.

Downloads pre-exported ONNX from HuggingFace Hub (no torch export needed).
Xenova/all-MiniLM-L6-v2 has community-maintained ONNX files.

Produces /app/model/ with tokenizer + model.onnx (~90MB float32).
"""
import os
import shutil
import subprocess
import sys

MODEL_NAME = os.getenv("EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
MODEL_PATH = os.getenv("EMBED_MODEL_PATH", "/app/model")

# Pre-exported ONNX sources (no torch needed at build time)
ONNX_SOURCES = [
    "Xenova/all-MiniLM-L6-v2",
    "optimum/all-MiniLM-L6-v2",
]


def download_onnx():
    """Download pre-exported ONNX model from HuggingFace."""
    from huggingface_hub import snapshot_download

    for source in ONNX_SOURCES:
        try:
            print(f"[embed-api bake] Trying pre-exported ONNX from {source} ...")
            path = snapshot_download(
                source,
                allow_patterns=["*.onnx", "*.json", "*.txt", "*.model", "*.tiktoken"],
                ignore_patterns=["*.bin", "*.safetensors", "*.h5", "*.msgpack", "*.ot"],
            )
            print(f"[embed-api bake] Downloaded to {path}")
            return path
        except Exception as e:
            print(f"[embed-api bake] {source} failed: {e}")
            continue
    return None


def export_onnx_fallback():
    """Fallback: export via sentence-transformers + torch.onnx.export."""
    import torch
    from sentence_transformers import SentenceTransformer

    print(f"[embed-api bake] Fallback: exporting {MODEL_NAME} via torch.onnx.export ...")
    model = SentenceTransformer(MODEL_NAME)

    # Get the transformer model
    inner_model = model[0]  # Transformer object
    tokenizer = inner_model.tokenizer

    # Dummy input
    dummy = tokenizer("hello world", return_tensors="pt", padding=True, truncation=True, max_length=128)

    class SentenceTransformerWrapper(torch.nn.Module):
        def __init__(self, model):
            super().__init__()
            self.model = model

        def forward(self, input_ids, attention_mask=None, token_type_ids=None):
            out = self.model({"input_ids": input_ids, "attention_mask": attention_mask, "token_type_ids": token_type_ids})
            # SentenceTransformer outputs: {'token_embeddings': tensor, 'attention_mask': tensor}
            return out["token_embeddings"]

    wrapper = SentenceTransformerWrapper(inner_model.auto_model)
    wrapper.eval()

    onnx_path = os.path.join(MODEL_PATH, "model.onnx")
    torch.onnx.export(
        wrapper,
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

    # Save tokenizer
    tokenizer.save_pretrained(MODEL_PATH)
    print(f"[embed-api bake] ONNX exported to {onnx_path}")

    del model, wrapper, torch
    import gc
    gc.collect()

    return True


def main():
    print(f"[embed-api bake] Baking ONNX model to {MODEL_PATH}")

    os.makedirs(MODEL_PATH, exist_ok=True)

    # Try downloading pre-exported ONNX first (fastest, no torch needed)
    source_path = download_onnx()

    if source_path:
        # Copy ONNX files to MODEL_PATH
        onnx_copied = False
        for item in os.listdir(source_path):
            src = os.path.join(source_path, item)
            if item.endswith(".onnx") or item.endswith(".json") or item.endswith(".txt") or item.endswith(".model"):
                dst = os.path.join(MODEL_PATH, item)
                if os.path.isdir(src):
                    if os.path.exists(dst):
                        shutil.rmtree(dst)
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)
                if item.endswith(".onnx"):
                    onnx_copied = True

        if onnx_copied:
            print(f"[embed-api bake] Pre-exported ONNX copied from {source_path}")
        else:
            print(f"[embed-api bake] No .onnx files found in {source_path}, falling back to export")
            source_path = None

    # Fallback: export via torch
    if not source_path or not onnx_copied:
        try:
            export_onnx_fallback()
        except Exception as e:
            print(f"[embed-api bake] Export failed: {e}", file=sys.stderr)
            sys.exit(1)

    # Report what we have
    print(f"[embed-api bake] Files in {MODEL_PATH}:")
    for f in sorted(os.listdir(MODEL_PATH)):
        fpath = os.path.join(MODEL_PATH, f)
        if os.path.isfile(fpath):
            size = os.path.getsize(fpath)
            print(f"  {f}: {size / 1024 / 1024:.1f}MB" if size > 1024 * 1024 else f"  {f}: {size / 1024:.0f}KB")

    print("[embed-api bake] Bake complete")


if __name__ == "__main__":
    main()
