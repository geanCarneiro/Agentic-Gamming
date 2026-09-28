"""Build a reversible inventory and visual review set from FNAF1 assets.

This script deliberately does not create semantic labels. It groups assets by
shape and produces contact sheets so the multimodal/manual review can add
labels without altering the original files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


def shape_group(width: int, height: int) -> str:
    if width >= 1000 and height >= 600:
        return "full_frame_candidate"
    if width >= 150 and height >= 600:
        return "vertical_scene_strip"
    if width >= 600 and height <= 150:
        return "horizontal_ui_strip"
    if 80 <= width <= 110 and 220 <= height <= 280:
        return "control_panel_reference"
    if 150 <= width <= 450 and 150 <= height <= 450:
        return "square_or_map_reference"
    if width <= 120 and height <= 150:
        return "small_ui_or_sprite"
    return "other_reference"


def surface_classification(asset_id: int, group: str) -> tuple[str, str, list[str]]:
    """Return a deliberately shallow, reviewable semantic classification."""
    notes: list[str] = []
    if group == "control_panel_reference":
        return "interaction_reference", "high", ["candidate for tight door/light boxes"]

    if asset_id in {12, 13, 14, 15, 16, 17, 18, 20}:
        return "visual_noise", "high", ["static/noise candidate; useful negative"]
    if asset_id in {145, 149, 155, 157, 160, 161, 163, 164}:
        return "camera_map_reference", "high", ["map/marker reference; not a scene object"]
    if asset_id in {47, 122, 124, 125, 130, 131, 134, 135}:
        return "interaction_reference", "high", ["door/light panel reference"]
    if asset_id in {42, 50, 54, 70, 71, 72, 73, 74, 75, 76, 77, 78, 79}:
        return "camera_label_or_ui", "high", ["text/UI fragment"]
    if 430 <= asset_id <= 479 or 520 <= asset_id <= 538 or 567 <= asset_id <= 605:
        return "menu_or_text_ui", "high", [
            "menu/status/text asset; exclude from character training"
        ]

    character_ranges = {
        "chica_candidate": (
            {65, 69, 211, 214, 215, *range(223, 233), 234, 279, 281, 446, 451, 529},
            "character close-up or scene",
        ),
        "bonnie_candidate": (
            {286, *range(288, 300), 528},
            "character close-up or scene",
        ),
        "foxy_candidate": (
            {*range(327, 338), *range(396, 414), 536},
            "character close-up or scene",
        ),
        "freddy_candidate": (
            {*range(307, 326), 354, 355, 431, 435, 440, 441, 442,
             484, 485, *range(489, 519), 525, 527},
            "character close-up or scene",
        ),
    }
    for label, (ids, note) in character_ranges.items():
        if asset_id in ids:
            return label, "medium", [note, "tight character box still needs review"]

    office_ids = {0, 39, 49, 58, 126, 127, 188, 190, 220, 222, 237, 238, 480, 485, 514, 540}
    if asset_id in office_ids:
        notes.append("inspect left door/window for bonnie_shadow")
        return "office_scene", "medium", notes

    if group == "full_frame_candidate":
        return "camera_or_scene", "low", ["full frame requires visual object review"]
    if group in {"vertical_scene_strip", "horizontal_ui_strip"}:
        return "scene_fragment_or_ui", "low", ["fragment; do not train as a full scene"]
    return "ui_or_reference_fragment", "low", [
        "retain for provenance; usually not a detector sample"
    ]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def expand_selector(selector: str) -> list[int]:
    asset_ids: set[int] = set()
    for token in selector.split(","):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            start, end = (int(value) for value in token.split("-", maxsplit=1))
            asset_ids.update(range(start, end + 1))
        else:
            asset_ids.add(int(token))
    return sorted(asset_ids)


def load_user_labels(path: Path) -> dict[int, dict[str, Any]]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    labels: dict[int, dict[str, Any]] = {}
    for entry in payload.get("entries", []):
        for asset_id in expand_selector(str(entry["selector"])):
            labels[asset_id] = {
                "surface_label": entry["surface_label"],
                "training_role": entry["training_role"],
                "notes": entry.get("notes", ""),
            }
    return labels


def make_contact_sheets(files: list[Path], output: Path, per_sheet: int) -> None:
    output.mkdir(parents=True, exist_ok=True)
    columns = 5
    cell_width, cell_height = 240, 155
    rows = (per_sheet + columns - 1) // columns
    font = ImageFont.load_default()

    for sheet_index in range(0, len(files), per_sheet):
        batch = files[sheet_index : sheet_index + per_sheet]
        canvas = Image.new("RGB", (columns * cell_width, rows * cell_height), "#202124")
        draw = ImageDraw.Draw(canvas)
        for offset, path in enumerate(batch):
            try:
                with Image.open(path) as source:
                    image = source.convert("RGB")
                    image.thumbnail((cell_width - 12, cell_height - 34))
                    x = (offset % columns) * cell_width
                    y = (offset // columns) * cell_height
                    image_x = x + (cell_width - image.width) // 2
                    image_y = y + 4
                    canvas.paste(image, (image_x, image_y))
                    label = f"{path.stem}  {source.width}x{source.height}"
                    draw.text((x + 6, y + cell_height - 25), label, fill="white", font=font)
            except Exception as exc:  # pragma: no cover - defensive for damaged assets
                x = (offset % columns) * cell_width
                y = (offset // columns) * cell_height
                draw.text((x + 6, y + 6), f"{path.name}: {exc}", fill="#ff8080", font=font)

        first_id = batch[0].stem
        last_id = batch[-1].stem
        canvas.save(output / f"assets-{first_id}-{last_id}.jpg", quality=88)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("data/games/FNAF1/assets"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/games/FNAF1/training-work"),
    )
    parser.add_argument(
        "--user-labels",
        type=Path,
        default=Path("data/games/FNAF1/training-work/user_surface_labels.json"),
    )
    parser.add_argument("--per-sheet", type=int, default=50)
    args = parser.parse_args()

    user_labels = load_user_labels(args.user_labels)
    files = sorted(
        args.source.glob("*.png"),
        key=lambda path: int(path.stem) if path.stem.isdigit() else path.stem,
    )
    args.output.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, object]] = []

    for path in files:
        with Image.open(path) as image:
            width, height = image.size
        group = shape_group(width, height)
        asset_id = int(path.stem) if path.stem.isdigit() else -1
        surface_label, confidence, notes = surface_classification(asset_id, group)
        user_label = user_labels.get(asset_id)
        if user_label is not None:
            surface_label = str(user_label["surface_label"])
            confidence = "user_confirmed"
            notes = [str(user_label["notes"])]
        records.append(
            {
                "asset": path.name,
                "source": str(path).replace("\\", "/"),
                "width": width,
                "height": height,
                "shape_group": group,
                "surface_label": surface_label,
                "training_role": user_label["training_role"] if user_label else None,
                "sha256": sha256(path),
                "semantic_label": None,
                "bbox": None,
                "confidence": confidence,
                "review_status": (
                    "user_surface_confirmed_bbox_pending"
                    if user_label
                    else "surface_triage_pending_review"
                ),
                "notes": notes,
            }
        )

    inventory_path = args.output / "asset_inventory.jsonl"
    with inventory_path.open("w", encoding="utf-8", newline="\n") as target:
        for record in records:
            target.write(json.dumps(record, ensure_ascii=False) + "\n")

    review_queue = [
        {
            "asset": record["asset"],
            "shape_group": record["shape_group"],
            "reason": (
                "candidate for visual scene annotation"
                if record["shape_group"] == "full_frame_candidate"
                else "candidate for reference/UI annotation"
            ),
            "priority": "high" if record["shape_group"] == "full_frame_candidate" else "normal",
            "requested_action": "identify objects and add tight bounding boxes",
        }
        for record in records
    ]
    with (args.output / "review_queue.jsonl").open(
        "w", encoding="utf-8", newline="\n"
    ) as target:
        for record in review_queue:
            target.write(json.dumps(record, ensure_ascii=False) + "\n")

    make_contact_sheets(files, args.output / "contact-sheets", args.per_sheet)

    counts: dict[str, int] = {}
    for record in records:
        group = str(record["shape_group"])
        counts[group] = counts.get(group, 0) + 1
    print(json.dumps({"assets": len(records), "groups": counts}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
