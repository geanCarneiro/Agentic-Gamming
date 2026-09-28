"""Build a FNAF1 detector dataset with annotated hard-example crops."""

from __future__ import annotations

import argparse
import json
import shutil
import zipfile
from pathlib import Path

from PIL import Image, ImageEnhance

VARIANTS = (
    ("bright", 1.30, 1.00),
    ("dark", 0.75, 1.00),
    ("contrast", 1.00, 1.30),
    ("bright_contrast", 1.15, 1.20),
    ("dark_contrast", 0.85, 1.20),
    ("soft_contrast", 1.05, 0.85),
)


def read_member(archive: zipfile.ZipFile, name: str) -> str:
    return archive.read(name).decode("utf-8")


def parse_labels(raw: str) -> list[str]:
    labels = []
    for line in raw.splitlines():
        if line.strip():
            values = line.split()
            if len(values) != 5:
                raise ValueError(f"Invalid YOLO label line: {line!r}")
            labels.append(" ".join(values))
    return labels


def copy_base_dataset(base: Path, output: Path) -> None:
    for split in ("train", "val", "test"):
        for kind in ("images", "labels"):
            source_dir = base / kind / split
            target_dir = output / kind / split
            target_dir.mkdir(parents=True, exist_ok=True)
            for source in source_dir.glob("*.png" if kind == "images" else "*.txt"):
                shutil.copy2(source, target_dir / source.name)


def apply_variant(image: Image.Image, brightness: float, contrast: float) -> Image.Image:
    result = ImageEnhance.Brightness(image).enhance(brightness)
    return ImageEnhance.Contrast(result).enhance(contrast)


def write_label(path: Path, labels: list[str]) -> None:
    path.write_text("\n".join(labels) + ("\n" if labels else ""), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--zip", dest="archive_path", type=Path, required=True)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--variants", type=int, default=len(VARIANTS))
    args = parser.parse_args()

    for path in (args.base, args.archive_path, args.assets):
        if not path.exists():
            raise SystemExit(f"Required path does not exist: {path}")
    if args.variants < 0 or args.variants > len(VARIANTS):
        raise SystemExit(f"--variants must be between 0 and {len(VARIANTS)}")
    if args.output.exists() and any(args.output.iterdir()):
        raise SystemExit(f"Output directory is not empty: {args.output}")

    args.output.mkdir(parents=True, exist_ok=True)
    copy_base_dataset(args.base, args.output)

    crops: list[dict] = []
    with zipfile.ZipFile(args.archive_path) as archive:
        members = set(archive.namelist())
        train_file = "train.txt"
        if train_file not in members:
            raise SystemExit("Hard-example CVAT export does not contain train.txt")
        for entry in read_member(archive, train_file).splitlines():
            entry = entry.strip()
            if not entry:
                continue
            asset_name = Path(entry.replace("\\", "/")).name
            asset_path = args.assets / asset_name
            if not asset_path.exists():
                raise SystemExit(f"Missing crop asset: {asset_path}")
            label_member = f"labels/train/{Path(asset_name).stem}.txt"
            if label_member not in members:
                raise SystemExit(f"Missing annotation for crop: {asset_name}")
            crops.append(
                {
                    "asset": asset_name,
                    "labels": parse_labels(read_member(archive, label_member)),
                    "label_member": label_member,
                }
            )

    train_images = args.output / "images" / "train"
    train_labels = args.output / "labels" / "train"
    manifest: list[dict] = []
    for crop in crops:
        source = args.assets / crop["asset"]
        stem = Path(crop["asset"]).stem
        original_name = f"hard_{stem}.png"
        target = train_images / original_name
        shutil.copy2(source, target)
        write_label(train_labels / f"hard_{stem}.txt", crop["labels"])
        manifest.append(
            {
                "source": crop["asset"],
                "output": original_name,
                "variant": "original",
                "labels": crop["labels"],
                "source_label_member": crop["label_member"],
            }
        )

        with Image.open(source) as opened:
            image = opened.convert("RGB")
            for index, (variant, brightness, contrast) in enumerate(
                VARIANTS[: args.variants], start=1
            ):
                output_name = f"hard_{stem}__aug{index:02d}_{variant}.png"
                output_path = train_images / output_name
                apply_variant(image, brightness, contrast).save(output_path, format="PNG")
                write_label(train_labels / f"{Path(output_name).stem}.txt", crop["labels"])
                manifest.append(
                    {
                        "source": crop["asset"],
                        "output": output_name,
                        "variant": variant,
                        "labels": crop["labels"],
                        "source_label_member": crop["label_member"],
                    }
                )

    dataset_yaml = "\n".join(
        [
            f"path: {args.output.resolve().as_posix()}",
            "train: images/train",
            "val: images/val",
            "test: images/test",
            "nc: 5",
            "names:",
            "  0: bonnie",
            "  1: chica",
            "  2: freddy",
            "  3: foxy",
            "  4: bonnie_shadow",
            "",
        ]
    )
    (args.output / "dataset.yaml").write_text(dataset_yaml, encoding="utf-8")
    with (args.output / "hard_examples_manifest.jsonl").open(
        "w", encoding="utf-8", newline="\n"
    ) as handle:
        for item in manifest:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")

    counts = {
        "base_train": len(list((args.output / "images" / "train").glob("*.png")))
        - len(manifest),
        "hard_examples": len(manifest),
        "val": len(list((args.output / "images" / "val").glob("*.png"))),
        "test": len(list((args.output / "images" / "test").glob("*.png"))),
    }
    print(json.dumps({"crops": len(crops), "variants_per_crop": args.variants, "counts": counts}))


if __name__ == "__main__":
    main()
