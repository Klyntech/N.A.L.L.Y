#!/usr/bin/env python3
"""Bake ONNX model into image at Docker build time.

Called by Dockerfile after pip install. Produces /app/model/ with
tokenizer files + model.onnx. No torch required at runtime.
"""
import os
import shutil
import subprocess
import sys

MODEL_NAME = os.getenv("EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
MODEL_PATH = os.getenv("EMBED_MODEL_PATH", "/app/model")
EXPORT_DIR = "/tmp/onnx-export"


def main():
    print(f"[embed-api bake] Exporting {MODEL_NAME} to ONNX ...")

    # Clean any previous export
    if os.path.exists(EXPORT_DIR):
        shutil.rmtree(EXPORT_DIR)
    os.makedirs(EXPORT_DIR, exist_ok=True)
    os.makedirs(MODEL_PATH, exist_ok=True)

    # Use optimum-cli export — handles external data, quantization, all edge cases
    cmd = [
        sys.executable, "-m", "optimum.exporters.onnx",
        "--model", MODEL_NAME,
        "--task", "feature-extraction",
        "--framework", "pt",
        EXPORT_DIR,
    ]
    print(f"[embed-api bake] Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[embed-api bake] STDOUT:\n{result.stdout}")
        print(f"[embed-api bake] STDERR:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)

    print(f"[embed-api bake] ONNX export done")
    print(f"[embed-api bake] Export output:\n{result.stdout[-500:]}" if result.stdout else "")

    # Copy everything from export dir to model path
    for item in os.listdir(EXPORT_DIR):
        src = os.path.join(EXPORT_DIR, item)
        dst = os.path.join(MODEL_PATH, item)
        if os.path.isdir(src):
            if os.path.exists(dst):
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)

    # Report what we have
    print(f"[embed-api bake] Files in {MODEL_PATH}:")
    for f in sorted(os.listdir(MODEL_PATH)):
        size = os.path.getsize(os.path.join(MODEL_PATH, f))
        print(f"  {f}: {size / 1024 / 1024:.1f}MB" if size > 1024 * 1024 else f"  {f}: {size / 1024:.0f}KB")

    # Clean up
    shutil.rmtree(EXPORT_DIR, ignore_errors=True)

    # Try dynamic quantization
    try:
        from optimum.onnxruntime import ORTQuantizer
        from optimum.onnxruntime.configuration import AutoQuantizationConfig

        onnx_file = os.path.join(MODEL_PATH, "model.onnx")
        if os.path.exists(onnx_file):
            print(f"[embed-api bake] Quantizing {onnx_file} ...")
            qconfig = AutoQuantizationConfig.avx512_vnni(
                is_static=False, per_channel=True,
                operators_to_quantize=["MatMul", "Add"],
            )
            quantizer = ORTQuantizer.from_pretrained(onnx_file)
            quantizer.quantize(save_dir=MODEL_PATH, quantization_config=qconfig)
            print("[embed-api bake] Quantized ONNX done")

            # Report final size
            q_file = os.path.join(MODEL_PATH, "model_quantized.onnx")
            if os.path.exists(q_file):
                q_size = os.path.getsize(q_file)
                print(f"[embed-api bake] Quantized model: {q_size / 1024 / 1024:.1f}MB")
    except Exception as e:
        print(f"[embed-api bake] Quantization skipped: {e} (will use float32 ONNX)")

    print("[embed-api bake] Bake complete")


if __name__ == "__main__":
    main()
