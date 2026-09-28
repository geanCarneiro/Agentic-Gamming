"""Import a CVAT Ultralytics YOLO export and pair it with FNAF1 assets."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import zipfile
from collections import defaultdict
from pathlib import Path

CLASS_NAMES = [
    "bonnie",
    "chica",
    "freddy",
    "foxy",
    "bonnie_shadow",
]


def read_text(archive: zipfile.ZipFile, name: str) -> str:
    return archive.read(name).decode("utf-8")


def parse_frame_id(path: str) -> int:
    match = re.search(r"/(\d+)\.png$", path.replace("\\", "/"))
    if match is None:
        raise ValueError(f"Could not extract frame id from {path}")
    return int(match.group(1))


def parse_labels(raw: str) -> list[dict[str, float | int]]:
    labels = []
    for line in raw.splitlines():
        values = line.split()
        if not values:
            continue
        if len(values) != 5:
            raise ValueError(f"Invalid YOLO label line: {line!r}")
        class_id, center_x, center_y, width, height = values
        class_index = int(class_id)
        if class_index < 0 or class_index >= len(CLASS_NAMES):
            raise ValueError(f"Unknown CVAT class id: {class_index}")
        labels.append(
            {
                "class_id": class_index,
                "center_x": float(center_x),
                "center_y": float(center_y),
                "width": float(width),
                "height": float(height),
            }
        )
    return labels


def assign_splits(items: list[dict]) -> None:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        signature = ",".join(str(label["class_id"]) for label in item["labels"])
        grouped[signature or "background"].append(item)

    for group in grouped.values():
        group.sort(key=lambda item: item["frame_id"])
        total = len(group)
        # Keep rare classes, especially bonnie_shadow, in training. A one-frame
        # class cannot provide a meaningful validation or test measurement.
        val_count = max(1, round(total * 0.10)) if total >= 8 else 0
        test_count = max(1, round(total * 0.15)) if total >= 8 else 0
        for index, item in enumerate(group):
            if index < val_count:
                item["split"] = "val"
            elif index < val_count + test_count:
                item["split"] = "test"
            else:
                item["split"] = "train"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--zip",
        dest="archive_path",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--assets",
        type=Path,
        default=Path("data/games/FNAF1/assets"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/games/FNAF1/training-work/yolo-cvat-task1"),
    )
    args = parser.parse_args()

    if not args.archive_path.exists():
        raise SystemExit(f"CVAT archive does not exist: {args.archive_path}")
    if not args.assets.exists():
        raise SystemExit(f"FNAF1 assets directory does not exist: {args.assets}")

    with zipfile.ZipFile(args.archive_path) as archive:
        members = set(archive.namelist())
        train_file = "train.txt"
        if train_file not in members:
            raise SystemExit("CVAT export does not contain train.txt")
        image_entries = [
            line.strip()
            for line in read_text(archive, train_file).splitlines()
            if line.strip()
        ]
        items: list[dict] = []
        for image_entry in image_entries:
            frame_id = parse_frame_id(image_entry)
            asset_name = f"{frame_id}.png"
            asset_path = args.assets / asset_name
            if not asset_path.exists():
                raise SystemExit(f"Missing original asset: {asset_path}")
            label_member = f"labels/train/{frame_id}.txt"
            labels = (
                parse_labels(read_text(archive, label_member))
                if label_member in members
                else []
            )
            items.append(
                {
                    "frame_id": frame_id,
                    "asset": asset_name,
                    "labels": labels,
                    "source_label_member": label_member if label_member in members else None,
                }
            )

    assign_splits(items)
    for split in ("train", "val", "test"):
        (args.output / "images" / split).mkdir(parents=True, exist_ok=True)
        (args.output / "labels" / split).mkdir(parents=True, exist_ok=True)

    for item in items:
        split = item["split"]
        image_target = args.output / "images" / split / item["asset"]
        label_target = args.output / "labels" / split / f"{item['frame_id']}.txt"
        shutil.copy2(args.assets / item["asset"], image_target)
        label_text = "\n".join(
            "{class_id} {center_x:.6f} {center_y:.6f} {width:.6f} {height:.6f}".format(**label)
            for label in item["labels"]
        )
        label_target.write_text(label_text + ("\n" if label_text else ""), encoding="utf-8")

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
    manifest_path = args.output / "cvat_manifest.jsonl"
    with manifest_path.open("w", encoding="utf-8", newline="\n") as manifest:
        for item in items:
            manifest.write(json.dumps(item, ensure_ascii=False) + "\n")

    counts = {
        split: sum(item["split"] == split for item in items)
        for split in ("train", "val", "test")
    }
    boxes = sum(len(item["labels"]) for item in items)
    print(json.dumps({"frames": len(items), "boxes": boxes, "splits": counts}, ensure_ascii=False))


if __name__ == "__main__":
    main()
