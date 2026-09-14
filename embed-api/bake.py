#!/usr/bin/env python3
"""Bake ONNX model into image at Docker build time.

Called by Dockerfile after pip install. Produces /app/model/ with
tokenizer files + model.onnx (float32) or model_quantized.onnx (int8).
No torch required.
"""
import os
import sys

MODEL_NAME = os.getenv("EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
MODEL_PATH = os.getenv("EMBED_MODEL_PATH", "/app/model")


def main():
    print(f"[embed-api bake] Exporting {MODEL_NAME} to ONNX ...")
    try:
        from optimum.onnxruntime import ORTModelForFeatureExtraction
        from transformers import AutoTokenizer

        os.makedirs(MODEL_PATH, exist_ok=True)

        # Export tokenizer
        tok = AutoTokenizer.from_pretrained(MODEL_NAME)
        tok.save_pretrained(MODEL_PATH)
        print(f"[embed-api bake] Tokenizer saved to {MODEL_PATH}")

        # Export ONNX
        mdl = ORTModelForFeatureExtraction.from_pretrained(MODEL_NAME, export=True)
        mdl.save_pretrained(MODEL_PATH)
        print(f"[embed-api bake] ONNX export done")

        # Try dynamic quantization (reduces 80MB float32 → 22MB int8)
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
            else:
                print(f"[embed-api bake] model.onnx not found — skipped quantization")
        except Exception as e:
            print(f"[embed-api bake] Quantization skipped: {e} (will use float32 ONNX)")

        # Report size
        import subprocess
        result = subprocess.run(["du", "-sh", MODEL_PATH], capture_output=True, text=True)
        print(f"[embed-api bake] Model size: {result.stdout.strip()}")

    except Exception as e:
        print(f"[embed-api bake] ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
