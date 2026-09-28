from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from time import time_ns
from uuid import uuid4

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont

from agentic_gaming.main import create_app

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "game-packs/fnaf1/vision/ingame-eval.json"
OUTPUT = ROOT / "data/diagnostics/fnaf1-ingame-core-eval"


def _font(size: int = 18) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype("arial.ttf", size)
    except OSError:
        return ImageFont.load_default()


def _draw_overlay(image_path: Path, annotation: dict, output_path: Path) -> Image.Image:
    image = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(image)
    scale_x, scale_y = image.width, image.height
    header = (
        f"scene={annotation.get('scene') or 'unknown'}  "
        f"status={annotation['detector_status']}  "
        f"{annotation['processing_ms']:.1f} ms"
    )
    camera_ids = sorted(
        {box.get("camera_id") for box in annotation.get("boxes", []) if box.get("camera_id")}
    )
    if camera_ids:
        header += "  active=" + ",".join(camera_ids)
    draw.rectangle((0, 0, image.width, 32), fill=(0, 0, 0))
    draw.text((8, 7), header, fill=(255, 255, 255), font=_font())

    for box in annotation.get("boxes", []):
        bbox = box.get("bbox")
        if not bbox:
            continue
        x, y, width, height = bbox
        left, top = round(x * scale_x), round(y * scale_y)
        right, bottom = round((x + width) * scale_x), round((y + height) * scale_y)
        color = (0, 220, 255) if box.get("kind") == "camera" else (255, 220, 40)
        draw.rectangle((left, top, right, bottom), outline=color, width=3)
        label = box.get("label", box.get("kind", "entity"))
        if box.get("state"):
            label += f" · {box['state']}"
        if box.get("camera_id"):
            label = box["camera_id"]
        draw.text(
            (left + 3, max(34, top - 21)),
            label,
            fill=color,
            stroke_width=2,
            stroke_fill=(0, 0, 0),
            font=_font(16),
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)
    return image


def main() -> int:
    samples = json.loads(MANIFEST.read_text(encoding="utf-8"))["samples"]
    results: list[dict] = []
    annotated_images: list[Image.Image] = []
    OUTPUT.mkdir(parents=True, exist_ok=True)

    artifact_dir = OUTPUT / "bridge-artifacts" / uuid4().hex
    artifact_dir.mkdir(parents=True, exist_ok=True)
    os.environ["BRIDGE_ARTIFACTS_DIR"] = str(artifact_dir)
    with TestClient(create_app()) as client:
        with client.websocket_connect(
            "/ws/host-bridge",
            headers={"X-Bridge-Token": os.getenv("HOST_BRIDGE_TOKEN", "dev-only-change-me")},
        ) as websocket:
            websocket.send_json(
                {
                    "type": "hello",
                    "protocol_version": "beta-4",
                    "client_id": "fnaf1-ingame-eval",
                    "capabilities": ["screen_capture", "vision_overlay"],
                    "dry_run": True,
                    "profile_id": "fnaf1",
                    "safe_capture": False,
                }
            )
            hello = websocket.receive_json()
            if hello.get("type") != "hello_ack":
                raise RuntimeError(f"Core handshake failed: {hello}")

            for index, sample in enumerate(samples, start=1):
                image_path = ROOT / sample["image"]
                image_bytes = image_path.read_bytes()
                with Image.open(image_path) as image:
                    width, height = image.size
                frame_id = f"ingame-eval-{index:02d}"
                websocket.send_json(
                    {
                        "type": "frame",
                        "frame_id": frame_id,
                        "captured_at_ns": time_ns(),
                        "width": width,
                        "height": height,
                        "encoding": "png",
                        "data_base64": base64.b64encode(image_bytes).decode("ascii"),
                        "source_window_title": "FNAF 1 in-game evaluation",
                        "source_process_id": 0,
                    }
                )
                ack = websocket.receive_json()
                if ack.get("type") != "frame_ack":
                    raise RuntimeError(f"Core rejected {frame_id}: {ack}")
                annotation = websocket.receive_json()
                if annotation.get("type") != "vision_annotations":
                    raise RuntimeError(
                        f"Core did not return annotations for {frame_id}: {annotation}"
                    )

                labels = [
                    box.get("label", "")
                    for box in annotation.get("boxes", [])
                    if box.get("state") != "absent"
                ]
                expected_camera = sample.get("camera_id")
                detected_camera = next(
                    (
                        box.get("camera_id")
                        for box in annotation.get("boxes", [])
                        if box.get("kind") == "camera"
                    ),
                    None,
                )
                expected_labels = sample.get("expected_labels", [])
                forbidden_labels = sample.get("forbidden_labels", [])
                results.append(
                    {
                        "frame_id": frame_id,
                        "image": sample["image"],
                        "expected_camera_id": expected_camera,
                        "detected_camera_id": detected_camera,
                        "camera_match": expected_camera == detected_camera,
                        "expected_labels": expected_labels,
                        "detected_labels": labels,
                        "missing_expected_labels": [
                            label for label in expected_labels if label not in labels
                        ],
                        "unexpected_labels": [
                            label for label in forbidden_labels if label in labels
                        ],
                        "processing_ms": annotation.get("processing_ms"),
                        "scene": annotation.get("scene"),
                        "detector_status": annotation.get("detector_status"),
                        "boxes": annotation.get("boxes", []),
                    }
                )
                overlay_path = OUTPUT / "overlays" / f"{index:02d}_{Path(sample['image']).stem}.png"
                annotated_images.append(_draw_overlay(image_path, annotation, overlay_path))
                print(
                    f"{frame_id}: camera={detected_camera or 'office'} "
                    f"labels={labels} processing={annotation.get('processing_ms')} ms"
                )

    results_path = OUTPUT / "results.json"
    results_path.write_text(
        json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    thumb_width = 640
    thumbnails = []
    for image in annotated_images:
        thumbnail = image.copy()
        thumbnail.thumbnail((thumb_width, 390))
        thumbnails.append(thumbnail)
    cell_width, cell_height = thumb_width, 420
    sheet = Image.new(
        "RGB", (cell_width * 2, cell_height * ((len(thumbnails) + 1) // 2)), (30, 30, 30)
    )
    sheet_draw = ImageDraw.Draw(sheet)
    for index, thumbnail in enumerate(thumbnails):
        x = (index % 2) * cell_width
        y = (index // 2) * cell_height
        sheet.paste(thumbnail, (x, y + 25))
        sheet_draw.text(
            (x + 8, y + 4),
            f"Image {index + 1}: {samples[index]['image']}",
            fill="white",
            font=_font(14),
        )
    sheet.save(OUTPUT / "contact-sheet.png")

    camera_errors = sum(not row["camera_match"] for row in results if row["expected_camera_id"])
    missing_labels = sum(len(row["missing_expected_labels"]) for row in results)
    unexpected_labels = sum(len(row["unexpected_labels"]) for row in results)
    print(f"Results: {results_path}")
    print(f"Overlays: {OUTPUT / 'overlays'}")
    print(f"Contact sheet: {OUTPUT / 'contact-sheet.png'}")
    print(
        f"Camera mismatches: {camera_errors}; expected labels missing: {missing_labels}; "
        f"forbidden labels detected: {unexpected_labels}"
    )
    return int(camera_errors > 0 or missing_labels > 0 or unexpected_labels > 0)


if __name__ == "__main__":
    raise SystemExit(main())
