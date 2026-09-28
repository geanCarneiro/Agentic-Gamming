"""Build a conservative YOLO bootstrap dataset from reviewed difference boxes."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

CLASS_IDS = {
    "chica": 0,
    "bonnie": 1,
    "foxy": 2,
    "freddy": 3,
}

CLASS_NAMES = [
    "chica",
    "bonnie",
    "foxy",
    "freddy",
]

# Explicit full-frame negatives confirmed during the visual review. Keep this
# list conservative: animation frames and camera effects are not negatives.
NEGATIVE_ASSET_IDS = {
    0,
    39,
    41,
    48,
    49,
    58,
    62,
    66,
    67,
    83,
    145,
    240,
    484,
    571,
}


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def class_id(label: str) -> int | None:
    for name, identifier in CLASS_IDS.items():
        if label.startswith(name):
            return identifier
    return None


def conservative_bbox(
    boxes: list[list[float]], width: int, height: int
) -> tuple[float, float, float, float] | None:
    if not boxes:
        return None
    x, y, box_width, box_height, _ = max(boxes, key=lambda box: box[4])
    margin_x = max(8, int(box_width * 0.12))
    margin_y = max(8, int(box_height * 0.12))
    left = max(0, int(x) - margin_x)
    top = max(0, int(y) - margin_y)
    right = min(width, int(x + box_width) + margin_x)
    bottom = min(height, int(y + box_height) + margin_y)
    actual_width = right - left
    actual_height = bottom - top
    if actual_width <= 2 or actual_height <= 2:
        return None
    center_x = (left + right) / 2 / width
    center_y = (top + bottom) / 2 / height
    normalized_width = actual_width / width
    normalized_height = actual_height / height
    return center_x, center_y, normalized_width, normalized_height


def assign_stratified_splits(items: list[dict]) -> None:
    """Assign deterministic train/val/test splits with every class represented."""

    by_group: dict[str, list[dict]] = {}
    for item in items:
        by_group.setdefault(item["class_name"], []).append(item)

    for group_items in by_group.values():
        group_items.sort(key=lambda item: int(Path(item["asset"]).stem))
        total = len(group_items)
        val_count = max(1, round(total * 0.10))
        test_count = max(1, round(total * 0.15))
        for index, item in enumerate(group_items):
            if index < val_count:
                item["split"] = "val"
            elif index < val_count + test_count:
                item["split"] = "test"
            else:
                item["split"] = "train"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", type=Path, default=Path("data/games/FNAF1/assets"))
    parser.add_argument(
        "--inventory",
        type=Path,
        default=Path("data/games/FNAF1/training-work/asset_inventory.jsonl"),
    )
    parser.add_argument(
        "--candidates",
        type=Path,
        default=Path(
            "data/games/FNAF1/training-work/difference-candidates/"
            "difference_candidates.jsonl"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "data/games/FNAF1/training-work/yolo-character-bootstrap-v2"
        ),
    )
    args = parser.parse_args()

    inventory = {
        record["asset"]: record for record in read_jsonl(args.inventory)
    }
    candidates = read_jsonl(args.candidates)
    selected: list[dict] = []
    for candidate in candidates:
        record = inventory.get(candidate["asset"])
        if record is None:
            continue
        identifier = class_id(str(candidate.get("surface_label", "")))
        if identifier is None or not candidate.get("candidate_bboxes"):
            continue
        bbox = conservative_bbox(
            candidate["candidate_bboxes"],
            int(record["width"]),
            int(record["height"]),
        )
        if bbox is None:
            continue
        selected.append(
            {
                "asset": candidate["asset"],
                "class_id": identifier,
                "class_name": CLASS_NAMES[identifier],
                "bbox": bbox,
                "surface_label": candidate["surface_label"],
                "baseline_asset": candidate.get("baseline_asset"),
                "source_status": candidate["status"],
                "split": "train",
            }
        )

    # Include confirmed empty scenes as background examples. Empty YOLO label
    # files teach the detector that a valid frame may contain no character.
    for asset_id in sorted(NEGATIVE_ASSET_IDS):
        asset = f"{asset_id}.png"
        record = inventory.get(asset)
        if record is None or not (args.assets / asset).exists():
            continue
        selected.append(
            {
                "asset": asset,
                "class_id": None,
                "class_name": "__background__",
                "bbox": None,
                "surface_label": record.get("surface_label", "scene_negative_or_empty"),
                "baseline_asset": None,
                "source_status": "user_confirmed_negative",
                "split": "train",
            }
        )

    assign_stratified_splits(selected)

    for split in ("train", "val", "test"):
        (args.output / "images" / split).mkdir(parents=True, exist_ok=True)
        (args.output / "labels" / split).mkdir(parents=True, exist_ok=True)

    for item in selected:
        split = item["split"]
        source = args.assets / item["asset"]
        image_target = args.output / "images" / split / item["asset"]
        label_target = args.output / "labels" / split / (
            Path(item["asset"]).stem + ".txt"
        )
        shutil.copy2(source, image_target)
        if item["bbox"] is None:
            label_target.write_text("", encoding="utf-8")
        else:
            center_x, center_y, box_width, box_height = item["bbox"]
            label_target.write_text(
                f"{item['class_id']} {center_x:.6f} {center_y:.6f} "
                f"{box_width:.6f} {box_height:.6f}\n",
                encoding="utf-8",
            )

    dataset_yaml = "\n".join(
        [
            f"path: {args.output.resolve().as_posix()}",
            "train: images/train",
            "val: images/val",
            "test: images/test",
            f"nc: {len(CLASS_NAMES)}",
            "names:",
            *[f"  {index}: {name}" for index, name in enumerate(CLASS_NAMES)],
            "",
        ]
    )
    (args.output / "dataset.yaml").write_text(dataset_yaml, encoding="utf-8")
    with (args.output / "bootstrap_manifest.jsonl").open(
        "w", encoding="utf-8", newline="\n"
    ) as target:
        for item in selected:
            target.write(json.dumps(item, ensure_ascii=False) + "\n")

    counts = {
        split: sum(item["split"] == split for item in selected)
        for split in ("train", "val", "test")
    }
    print(json.dumps({"selected": len(selected), "splits": counts}, ensure_ascii=False))


if __name__ == "__main__":
    main()
