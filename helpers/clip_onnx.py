"""ONNX-CLIP — lean-альтернатива sentence-transformers + PyTorch.

Stub-модуль для будущего перехода с PyTorch CLIP на ONNX Runtime CLIP.
По рекомендации Gemini Deep Research:
  - 15 МБ зависимостей вместо 2 ГБ
  - 1.5× быстрее на Intel CPU за счёт лучшей утилизации AVX2
  - Работает с Python 3.13 (PyTorch — нет)

ПОДГОТОВКА (один раз):
  1. uv sync --extra clip-onnx
  2. python helpers/clip_onnx.py --setup
     → конвертирует CLIP-ViT-B-32 из HuggingFace в .onnx
     → сохраняет в edit/models/clip-vit-b32.onnx + tokenizer.json
  3. После этого match_video_to_audio.py --backend clip-onnx работает.

ИСПОЛЬЗОВАНИЕ (из других helpers):
    from clip_onnx import CLIPOnnx
    clip = CLIPOnnx(model_dir="edit/models/")
    img_emb = clip.encode_image("frame.jpg")    # (512,) numpy
    text_emb = clip.encode_text("city at night") # (512,) numpy
    similarity = float(img_emb @ text_emb)       # cosine (normalized)

Реализация WIP — фокус MVP сейчас на tt-describe backend.
Подключим когда понадобится on-device CLIP без PyTorch.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


class CLIPOnnx:
    """Stub-класс. Реальная реализация — после первого реального запроса."""

    def __init__(self, model_dir: str | Path):
        self.model_dir = Path(model_dir)
        raise NotImplementedError(
            "ONNX-CLIP пока не подключён. Используй tt-describe backend "
            "в match_video_to_audio.py или ставь clip-pytorch extra."
        )

    def encode_image(self, image_path: str | Path):
        raise NotImplementedError

    def encode_text(self, text: str):
        raise NotImplementedError


def setup_onnx_model(out_dir: Path) -> None:
    """Конвертация CLIP-ViT-B-32 из HuggingFace в .onnx.

    Делается один раз при подготовке среды. Требует временно установленные
    torch + transformers для самой конвертации (потом их можно снести).

    Roadmap:
      - использовать `optimum[exporters]` для автоматической ONNX-конвертации
      - сохранить image_encoder.onnx + text_encoder.onnx раздельно
      - сохранить tokenizer.json
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    print("⚠️ ONNX-конвертация WIP. Шаги для ручной подготовки:\n")
    print("  pip install 'optimum[exporters]'")
    print("  optimum-cli export onnx --model openai/clip-vit-base-patch32 \\")
    print(f"      --task feature-extraction-with-past {out_dir}/")
    print("\nПосле этого — в onnxruntime InferenceSession + tokenizers для encode.")


def main() -> None:
    ap = argparse.ArgumentParser(description="ONNX-CLIP setup/check")
    ap.add_argument("--setup", action="store_true",
                    help="Конвертировать CLIP-ViT-B-32 в .onnx (один раз)")
    ap.add_argument("--out-dir", type=Path, default=Path("edit/models"))
    args = ap.parse_args()

    if args.setup:
        setup_onnx_model(args.out_dir)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
