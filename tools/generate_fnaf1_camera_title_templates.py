from __future__ import annotations

import json
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
PIPELINE = ROOT / "game-packs/fnaf1/vision/pipeline.json"
SAMPLES = ROOT / "game-packs/fnaf1/vision/ingame-eval.json"
ASSET_ROOT = ROOT / "data/games/FNAF1/assets"
OUTPUT = ASSET_ROOT / "camera_titles"
TEMPLATE_SIZE = (300, 100)


def main() -> int:
    pipeline = json.loads(PIPELINE.read_text(encoding="utf-8"))
    evaluation = json.loads(SAMPLES.read_text(encoding="utf-8"))
    camera_samples = {
        sample["camera_id"]: ROOT / sample["image"]
        for sample in evaluation["samples"]
        if sample.get("camera_id")
    }
    x, y, width, height = pipeline["camera_title_detection"]["roi"]
    threshold = pipeline["camera_title_detection"]["threshold"]
    roi_width, roi_height = TEMPLATE_SIZE
    OUTPUT.mkdir(parents=True, exist_ok=True)

    for template in pipeline["camera_title_detection"]["templates"]:
        camera_id = template["camera_id"]
        source = camera_samples.get(camera_id)
        if source is None:
            raise ValueError(f"No in-game evaluation sample is registered for {camera_id}")
        image = cv2.imread(str(source), cv2.IMREAD_GRAYSCALE)
        if image is None:
            raise FileNotFoundError(source)
        source_height, source_width = image.shape[:2]
        left, top = round(x * source_width), round(y * source_height)
        right, bottom = round((x + width) * source_width), round((y + height) * source_height)
        crop = image[top:bottom, left:right]
        resized = cv2.resize(crop, (roi_width, roi_height), interpolation=cv2.INTER_AREA)
        _, mask = cv2.threshold(resized, threshold, 255, cv2.THRESH_BINARY)
        mask = cv2.morphologyEx(
            mask,
            cv2.MORPH_OPEN,
            cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2)),
        )
        target = ASSET_ROOT / template["asset"]
        target.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(target), mask):
            raise OSError(f"Could not write camera title template: {target}")
        print(f"{camera_id}: {target.relative_to(ROOT)} from {source.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
