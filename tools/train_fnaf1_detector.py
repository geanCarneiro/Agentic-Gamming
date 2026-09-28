"""Train and export the FNAF1 bootstrap detector."""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

os.environ.setdefault(
    "YOLO_CONFIG_DIR",
    str(Path("Ultralytics").resolve()),
)
os.environ.setdefault(
    "MPLCONFIGDIR",
    str(Path("data/games/FNAF1/training-work/matplotlib").resolve()),
)

import ultralytics.data.dataset as dataset_module
import ultralytics.utils as ultralytics_utils

from ultralytics import YOLO

ultralytics_utils.NUM_THREADS = 1
dataset_module.NUM_THREADS = 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data",
        type=Path,
        default=Path(
            "data/games/FNAF1/training-work/yolo-character-bootstrap-v2/dataset.yaml"
        ),
    )
    parser.add_argument("--model", default="yolo26n.pt")
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--imgsz", type=int, default=960)
    parser.add_argument("--export-imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=4)
    parser.add_argument("--device", default="0")
    parser.add_argument("--mosaic", type=float, default=0.0)
    parser.add_argument("--fliplr", type=float, default=0.0)
    parser.add_argument(
        "--run-name",
        default="fnaf1-yolo26n-character-bootstrap-v2",
    )
    parser.add_argument(
        "--project",
        type=Path,
        default=Path("data/games/FNAF1/training-work/runs"),
    )
    parser.add_argument(
        "--destination",
        type=Path,
        default=Path("game-packs/fnaf1/models/fnaf1-yolo26n.onnx"),
    )
    args = parser.parse_args()

    model = YOLO(args.model)
    result = model.train(
        data=str(args.data.resolve()),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        workers=0,
        cache=False,
        patience=12,
        mosaic=args.mosaic,
        fliplr=args.fliplr,
        project=str(args.project.resolve()),
        name=args.run_name,
        exist_ok=True,
        plots=True,
        verbose=True,
    )
    best_path = Path(result.save_dir) / "weights" / "best.pt"
    best_model = YOLO(str(best_path))
    exported = best_model.export(
        format="onnx",
        imgsz=args.export_imgsz,
        nms=True,
        simplify=True,
        opset=12,
        device=args.device,
    )
    args.destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(exported, args.destination)
    print(f"best_pt={best_path}")
    print(f"onnx={args.destination.resolve()}")


if __name__ == "__main__":
    main()
