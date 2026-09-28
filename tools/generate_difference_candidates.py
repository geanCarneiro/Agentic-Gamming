"""Generate reversible bbox candidates by comparing positives with negatives.

The output is intentionally pseudo-label data. A difference can contain a
character, a shadow, a light effect, a door animation, or several of them, so
every candidate remains reviewable before it becomes training ground truth.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

POSITIVE_ROLES = {
    "character_positive",
    "interaction_positive",
    "special_evidence_positive",
}
NEGATIVE_ROLES = {"negative_candidate"}


def load_inventory(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def load_baseline_overrides(path: Path) -> dict[int, str]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {int(asset): str(baseline) for asset, baseline in payload.items()}


def read_image(path: Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"could not read image: {path}")
    return image


def resized_gray(image: np.ndarray, size: tuple[int, int] = (96, 48)) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return cv2.resize(gray, size, interpolation=cv2.INTER_AREA).astype(np.float32)


def choose_baseline(
    positive: np.ndarray,
    negative_paths: list[Path],
) -> tuple[Path | None, float | None]:
    if not negative_paths:
        return None, None
    positive_small = resized_gray(positive)
    candidates: list[tuple[float, Path]] = []
    for path in negative_paths:
        negative = read_image(path)
        negative_small = resized_gray(negative)
        score = float(np.mean(np.abs(positive_small - negative_small)))
        candidates.append((score, path))
    score, path = min(candidates, key=lambda item: item[0])
    return path, score


def difference_boxes(
    positive: np.ndarray,
    negative: np.ndarray,
) -> tuple[np.ndarray, list[list[float]]]:
    if negative.shape[:2] != positive.shape[:2]:
        negative = cv2.resize(
            negative,
            (positive.shape[1], positive.shape[0]),
            interpolation=cv2.INTER_AREA,
        )
    positive_gray = cv2.cvtColor(positive, cv2.COLOR_BGR2GRAY)
    negative_gray = cv2.cvtColor(negative, cv2.COLOR_BGR2GRAY)
    positive_gray = cv2.GaussianBlur(positive_gray, (5, 5), 0)
    negative_gray = cv2.GaussianBlur(negative_gray, (5, 5), 0)
    difference = cv2.absdiff(positive_gray, negative_gray)
    threshold = max(18.0, float(np.percentile(difference, 97.0)))
    mask = np.where(difference >= threshold, 255, 0).astype(np.uint8)
    kernel = np.ones((5, 5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    mask = cv2.dilate(mask, np.ones((9, 9), np.uint8), iterations=1)

    components, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    min_area = max(40, int(positive.shape[0] * positive.shape[1] * 0.00008))
    boxes: list[list[float]] = []
    for component in range(1, components):
        x, y, width, height, area = stats[component]
        if area < min_area:
            continue
        boxes.append([int(x), int(y), int(width), int(height), int(area)])
    boxes.sort(key=lambda box: box[4], reverse=True)
    return difference, boxes[:8]


def write_preview(
    positive: np.ndarray,
    negative: np.ndarray,
    difference: np.ndarray,
    boxes: list[list[float]],
    path: Path,
) -> None:
    negative = cv2.resize(negative, (positive.shape[1], positive.shape[0]))
    diff_bgr = cv2.cvtColor(difference, cv2.COLOR_GRAY2BGR)
    annotated = positive.copy()
    for x, y, width, height, _ in boxes:
        cv2.rectangle(
            annotated,
            (int(x), int(y)),
            (int(x + width), int(y + height)),
            (0, 220, 0),
            3,
        )
    preview = np.concatenate([negative, positive, diff_bgr, annotated], axis=1)
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), preview, [cv2.IMWRITE_JPEG_QUALITY, 88])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--assets", type=Path, default=Path("data/games/FNAF1/assets")
    )
    parser.add_argument(
        "--inventory",
        type=Path,
        default=Path("data/games/FNAF1/training-work/asset_inventory.jsonl"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/games/FNAF1/training-work/difference-candidates"),
    )
    parser.add_argument(
        "--baseline-overrides",
        type=Path,
        default=Path("data/games/FNAF1/training-work/baseline_overrides.json"),
    )
    args = parser.parse_args()

    records = load_inventory(args.inventory)
    baseline_overrides = load_baseline_overrides(args.baseline_overrides)
    records_by_asset = {str(record["asset"]): record for record in records}
    by_dimensions: dict[tuple[int, int], list[dict]] = {}
    for record in records:
        dimensions = (int(record["width"]), int(record["height"]))
        by_dimensions.setdefault(dimensions, []).append(record)

    candidates: list[dict] = []
    for record in records:
        if record.get("training_role") not in POSITIVE_ROLES:
            continue
        dimensions = (int(record["width"]), int(record["height"]))
        negatives = [
            other
            for other in by_dimensions.get(dimensions, [])
            if other.get("training_role") in NEGATIVE_ROLES
        ]
        positive_path = args.assets / str(record["asset"])
        positive = read_image(positive_path)
        baseline_record, baseline_score = None, None
        asset_id = int(Path(str(record["asset"])).stem)
        override_asset = baseline_overrides.get(asset_id)
        if override_asset is not None and f"{override_asset}.png" in records_by_asset:
            baseline_record = records_by_asset[f"{override_asset}.png"]
            baseline_path = args.assets / str(baseline_record["asset"])
            baseline_selection = "manual_override"
        else:
            baseline_path, baseline_score = choose_baseline(
                positive,
                [args.assets / str(other["asset"]) for other in negatives],
            )
            baseline_selection = "nearest_negative" if baseline_path else None
        if baseline_path is not None:
            if baseline_record is None:
                baseline_record = next(
                    other for other in negatives if str(other["asset"]) == baseline_path.name
                )
            negative = read_image(baseline_path)
            difference, boxes = difference_boxes(positive, negative)
            preview_path = args.output / "previews" / (
                f"positive-{record['asset'].replace('.png', '')}"
                f"_negative-{baseline_record['asset'].replace('.png', '')}.jpg"
            )
            write_preview(positive, negative, difference, boxes, preview_path)
        else:
            boxes = []
            preview_path = None

        candidates.append(
            {
                "asset": record["asset"],
                "surface_label": record.get("surface_label"),
                "training_role": record.get("training_role"),
                "baseline_asset": baseline_record["asset"] if baseline_record else None,
                "baseline_selection": baseline_selection,
                "baseline_similarity_score": baseline_score,
                "candidate_bboxes": boxes,
                "preview": str(preview_path).replace("\\", "/")
                if preview_path
                else None,
                "status": "pseudo_bbox_needs_review" if boxes else "no_matching_negative",
            }
        )

    args.output.mkdir(parents=True, exist_ok=True)
    output_path = args.output / "difference_candidates.jsonl"
    with output_path.open("w", encoding="utf-8", newline="\n") as target:
        for candidate in candidates:
            target.write(json.dumps(candidate, ensure_ascii=False) + "\n")
    print(json.dumps({"candidates": len(candidates), "output": str(output_path)}))


if __name__ == "__main__":
    main()
