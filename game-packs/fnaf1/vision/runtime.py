from __future__ import annotations

import hashlib
import html
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Literal

import cv2
import numpy as np
from pydantic import ConfigDict, Field, field_validator

from agentic_gaming.contracts import InformationOrigin, StrictModel, VisionEntity, VisionState
from agentic_gaming.vision_host import VisionFrame


class Roi(StrictModel):
    id: str
    bbox: tuple[float, float, float, float]
    coordinate_space: Literal["screen", "world"] = "screen"
    purpose: str = "search"
    side: str | None = None

    @field_validator("bbox")
    @classmethod
    def validate_bbox(cls, value: tuple[float, float, float, float]):
        x, y, width, height = value
        if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > 1 or y + height > 1:
            raise ValueError("FNAF vision ROI must fit inside the normalized frame")
        return value


class ViewportRegistration(StrictModel):
    enabled: bool = True
    reference_asset: str
    reference_size: tuple[int, int] = (1600, 720)
    anchor_roi: tuple[float, float, float, float]
    search_range: tuple[float, float] = (0.0, 1.0)
    coarse_step: float = Field(default=0.02, gt=0, le=1)
    refine_step: float = Field(default=0.004, gt=0, le=1)
    min_confidence: float = Field(default=0.65, ge=0, le=1)
    max_anchor_error: float = Field(default=14.0, gt=0, le=255)
    min_anchor_std: float = Field(default=3.0, ge=0, le=255)
    max_pan_jump_px: int = Field(default=120, ge=1)

    @field_validator("anchor_roi")
    @classmethod
    def validate_anchor_roi(cls, value: tuple[float, float, float, float]):
        x, y, width, height = value
        if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > 1 or y + height > 1:
            raise ValueError("viewport anchor ROI must fit inside the normalized frame")
        return value


class DifferenceEntity(StrictModel):
    id: str
    label: str
    kind: str = "object"
    identity: str | None = None
    state: str = "present"
    bbox: tuple[float, float, float, float] | None = None
    bbox_scope: str = "roi"
    bbox_mode: str = "detected"

    @field_validator("bbox")
    @classmethod
    def validate_bbox(cls, value: tuple[float, float, float, float] | None):
        if value is None:
            return value
        x, y, width, height = value
        if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > 1 or y + height > 1:
            raise ValueError("difference entity bbox must fit inside its scope")
        return value


class DifferenceCandidate(StrictModel):
    id: str
    positive_asset: str
    positive_assets: list[str] = Field(default_factory=list)
    positive_asset_bboxes: dict[str, tuple[float, float, float, float]] = Field(
        default_factory=dict
    )
    negative_asset: str
    negative_assets: list[str] = Field(default_factory=list)
    roi_id: str
    coordinate_space: Literal["screen", "world"] = "screen"
    reference_scope: Literal["frame", "roi"] = "frame"
    entities: list[DifferenceEntity] = Field(default_factory=list)
    scene: str | None = None
    camera_id: str | None = None
    threshold: float = Field(default=0.62, ge=0, le=1)
    min_score_margin: float = Field(default=0.05, ge=0, le=1)
    pixel_threshold: int = Field(default=18, ge=1, le=255)
    blur_kernel: int = Field(default=5, ge=1, le=31)
    open_kernel: int = Field(default=3, ge=1, le=31)
    close_kernel: int = Field(default=5, ge=1, le=31)
    dilate_kernel: int = Field(default=3, ge=1, le=31)
    min_component_area: int = Field(default=24, ge=1)
    background_threshold: float = Field(default=12.0, gt=0, le=255)
    exclusion_regions: list[tuple[float, float, float, float]] = Field(default_factory=list)
    enabled: bool = True

    @field_validator("positive_asset_bboxes")
    @classmethod
    def validate_positive_asset_bboxes(
        cls,
        value: dict[str, tuple[float, float, float, float]],
    ):
        for asset, bbox in value.items():
            x, y, width, height = bbox
            if (
                not asset
                or x < 0
                or y < 0
                or width <= 0
                or height <= 0
                or x + width > 1
                or y + height > 1
            ):
                raise ValueError("positive asset bboxes must be normalized and fit the frame")
        return value

    @field_validator("exclusion_regions")
    @classmethod
    def validate_exclusion_regions(
        cls,
        value: list[tuple[float, float, float, float]],
    ):
        for x, y, width, height in value:
            if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > 1 or y + height > 1:
                raise ValueError("difference exclusion regions must fit inside their ROI")
        return value


class DifferenceDetection(StrictModel):
    id: str = "pack.fnaf1.difference_roi"
    candidates: list[DifferenceCandidate] = Field(min_length=1)
    enabled: bool = True


class CameraTitleTemplate(StrictModel):
    camera_id: str
    asset: str


class CameraTitleDetection(StrictModel):
    enabled: bool = True
    roi: tuple[float, float, float, float]
    threshold: int = Field(default=200, ge=0, le=255)
    minimum_score: float = Field(default=0.6, ge=0, le=1)
    minimum_margin: float = Field(default=0.12, ge=0, le=1)
    templates: list[CameraTitleTemplate] = Field(default_factory=list)


class Pipeline(StrictModel):
    model_config = ConfigDict(extra="ignore")

    asset_root: str
    rois: list[Roi] = Field(default_factory=list)
    viewport_registration: ViewportRegistration | None = None
    difference_detection: DifferenceDetection
    camera_title_detection: CameraTitleDetection | None = None
    reference_assets: list[dict[str, str]] = Field(default_factory=list)
    bbox_colors: dict[str, str] = Field(default_factory=dict)

    @field_validator("bbox_colors")
    @classmethod
    def validate_bbox_colors(cls, value: dict[str, str]) -> dict[str, str]:
        for identity, color in value.items():
            if not identity or len(color) != 7 or color[0] != "#" or any(
                character not in "0123456789abcdefABCDEF" for character in color[1:]
            ):
                raise ValueError("bbox colors must use #RRGGBB hexadecimal values")
        return value


Pipeline.model_rebuild()


def _slug(value: str) -> str:
    slug = "".join(character.lower() if character.isalnum() else "-" for character in value)
    slug = "-".join(part for part in slug.split("-") if part)
    return slug or "item"


def _compiled_bbox_key(candidate_id: str, positive: str, negative: str, entity_id: str) -> str:
    return "|".join((candidate_id, positive, negative, entity_id))


def _compile_index(rows: list[dict[str, str]], errors: list[str], compile_id: str) -> str:
    cards = []
    for row in rows:
        folder = html.escape(row["folder"], quote=True)
        cards.append(
            "<article><h2>{camera} · {identity}</h2>"
            "<p>Candidato: {candidate}<br>Positivo: {positive}<br>Negativo: {negative}<br>"
            "BBox: {bbox}<br>Cor: <code>{color}</code></p>"
            "<a href=\"{folder}/positive-with-bbox.png\">"
            "<img src=\"{folder}/positive-with-bbox.png\" alt=\"positivo com bbox\"></a>"
            "<p><a href=\"{folder}/positive.png\">positivo</a> · "
            "<a href=\"{folder}/negative.png\">negativo</a> · "
            "<a href=\"{folder}/difference.png\">diff</a> · "
            "<a href=\"{folder}/metadata.json\">metadados</a></p></article>".format(
                camera=html.escape(row["camera"]),
                identity=html.escape(row["identity"]),
                candidate=html.escape(row["candidate"]),
                positive=html.escape(row["positive"]),
                negative=html.escape(row["negative"]),
                bbox=html.escape(row["bbox"]),
                color=html.escape(row["color"]),
                folder=folder,
            )
        )
    error_html = "" if not errors else (
        "<section class=\"errors\"><h2>Itens que precisam de revisão</h2><ul>"
        + "".join(f"<li>{html.escape(error)}</li>" for error in errors)
        + "</ul></section>"
    )
    return (
        "<!doctype html><html lang=\"pt-BR\"><meta charset=\"utf-8\"><title>"
        f"Game Pack compilado — {html.escape(compile_id)}</title>"
        "<style>body{font:15px system-ui;margin:24px;background:#17191d;color:#eee}"
        "main{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:16px}"
        "article,.errors{background:#242830;padding:16px;border-radius:8px}"
        "img{width:100%;height:auto;background:#08090b}a{color:#8dc8ff}"
        ".errors{border:1px solid #f88}</style><h1>Compilação de visão</h1>"
        f"<p>Execução: {html.escape(compile_id)} · variações compiladas: {len(rows)}</p>"
        f"{error_html}<main>{''.join(cards)}</main></html>"
    )


class DifferenceVision:
    """FNAF 1 vision runtime owned by the Game Pack.

    The Core only supplies an opaque VisionFrame. This module owns OpenCV,
    positive/negative signatures, screen/world ROIs and horizontal viewport
    registration.
    """

    def __init__(self, *, game_pack_root: Path, manifest: dict) -> None:
        del manifest
        self.pack_root = Path(game_pack_root)
        self.pipeline = self._load_pipeline()
        self.asset_root = Path(self.pipeline.asset_root)
        if not self.asset_root.is_absolute():
            self.asset_root = (self.pack_root / self.asset_root).resolve()
        self._assets: dict[str, np.ndarray | None] = {}
        self._gray_assets: dict[str, np.ndarray | None] = {}
        self._camera_title_masks: dict[str, np.ndarray | None] = {}
        self._reference_signatures: dict[
            tuple[object, ...],
            tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray],
        ] = {}
        compile_root = Path(os.getenv("GAME_PACK_COMPILE_DIR", "data/diagnostics/gamepack-compile"))
        self.compiled_bbox_manifest = (
            compile_root / self.pack_root.name / "active-bboxes.json"
        ).resolve()
        self._compiled_bboxes: dict[str, list[float]] = {}
        self._compiled_bbox_mtime_ns: int | None = None
        self._load_compiled_bboxes()
        self._last_pan_x: int | None = None
        self._last_frame_shape: tuple[int, int] | None = None

    def observe(self, frame: VisionFrame) -> VisionState:
        started = perf_counter()
        stage_timings: dict[str, float] = {}
        stage_started = perf_counter()
        image = cv2.imdecode(np.frombuffer(frame.frame_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("FNAF Game Pack could not decode the frame")
        height, width = image.shape[:2]
        stage_timings["decode"] = (perf_counter() - stage_started) * 1000
        stage_started = perf_counter()
        camera_entity, active_camera_id, camera_score = self._detect_active_camera(
            image, width, height
        )
        self._load_compiled_bboxes()
        stage_timings["camera_identification"] = (perf_counter() - stage_started) * 1000
        if self._last_frame_shape is not None and self._last_frame_shape != (width, height):
            self._last_pan_x = None
        self._last_frame_shape = (width, height)
        stage_started = perf_counter()
        pan_x, pan_confidence = self._register_horizontal_viewport(image, width, height)
        stage_timings["viewport_registration"] = (perf_counter() - stage_started) * 1000
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        roi_map = {roi.id: roi for roi in self.pipeline.rois}
        entities: list[VisionEntity] = [camera_entity] if camera_entity is not None else []
        roi_timings: dict[str, float] = {}
        world_observation_unavailable = False
        for candidate in self.pipeline.difference_detection.candidates:
            if not candidate.enabled:
                continue
            if active_camera_id is not None and candidate.scene != "camera":
                continue
            if (
                active_camera_id is not None
                and candidate.scene == "camera"
                and candidate.camera_id != active_camera_id
            ):
                continue
            roi = roi_map.get(candidate.roi_id)
            if roi is None:
                continue
            if candidate.coordinate_space != roi.coordinate_space:
                world_observation_unavailable |= candidate.coordinate_space == "world"
                continue
            world_reference_size = (
                self.pipeline.viewport_registration.reference_size
                if candidate.coordinate_space == "world" and self.pipeline.viewport_registration
                else None
            )
            if candidate.coordinate_space == "world" and (
                pan_x is None or world_reference_size is None
            ):
                world_observation_unavailable = True
                continue
            transformed_roi = self._roi_for_frame(
                roi,
                width,
                height,
                pan_x or 0,
                world_reference_size,
            )
            if transformed_roi is None:
                continue
            stage_started = perf_counter()
            candidate_entities = self._detect_candidate(
                gray,
                candidate,
                transformed_roi,
                width,
                height,
                pan_x or 0,
                pan_confidence,
            )
            if active_camera_id is None and candidate.scene == "camera":
                candidate_entities = [
                    entity for entity in candidate_entities if entity.state != "absent"
                ]
            entities.extend(candidate_entities)
            roi_timings[candidate.id] = (perf_counter() - stage_started) * 1000

        scene_candidates = [
            entity.properties.get("scene")
            for entity in entities
            if isinstance(entity.properties.get("scene"), str)
        ]
        scene = "camera" if active_camera_id is not None else (
            scene_candidates[0] if scene_candidates else None
        )
        if world_observation_unavailable or not entities:
            detector_status = "insufficient_evidence"
        else:
            detector_status = "ready"
        stage_timings.update({f"candidate.{key}": value for key, value in roi_timings.items()})
        stage_timings["observation_construction"] = (perf_counter() - started) * 1000
        return VisionState(
            frame_id=frame.frame_id,
            captured_at_ns=frame.captured_at_ns,
            frame_width=width,
            frame_height=height,
            scene=scene,
            confidence=max((entity.confidence for entity in entities), default=0.0),
            entities=entities,
            detector_id=self.pipeline.difference_detection.id,
            detector_status=detector_status,
            processing_ms=(perf_counter() - started) * 1000,
            stage_timings_ms=stage_timings,
            diagnostics={
                "active_camera": {
                    "camera_id": active_camera_id,
                    "confidence": round(camera_score, 4),
                    "method": "title_template" if active_camera_id is not None else None,
                },
                "viewport_registration": {
                    "pan_x": pan_x,
                    "confidence": round(pan_confidence, 4),
                    "status": "ready" if pan_x is not None else "unreliable",
                },
            },
        )

    def compile(self, *, output_dir: Path) -> dict:
        """Compile reference differences and emit inspectable artifacts and runtime bboxes."""
        output_dir = Path(output_dir).resolve()
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        pipeline_path = self.pack_root / "vision" / "pipeline.json"
        pipeline_sha = hashlib.sha256(pipeline_path.read_bytes()).hexdigest()
        compile_id = f"{timestamp}-{pipeline_sha[:10]}"
        pack_output = output_dir / self.pack_root.name / compile_id
        pack_output.mkdir(parents=True, exist_ok=False)
        roi_map = {roi.id: roi for roi in self.pipeline.rois}
        compiled_boxes: dict[str, list[float]] = {}
        rows: list[dict[str, str]] = []
        errors: list[str] = []

        for candidate in self.pipeline.difference_detection.candidates:
            roi = roi_map.get(candidate.roi_id)
            if not candidate.enabled or roi is None:
                continue
            for positive_name in candidate.positive_assets or [candidate.positive_asset]:
                positive = self._asset(positive_name)
                if positive is None:
                    errors.append(f"Asset positivo ausente: {positive_name}")
                    continue
                for negative_name in candidate.negative_assets or [candidate.negative_asset]:
                    negative = self._asset(negative_name)
                    if negative is None:
                        errors.append(f"Asset negativo ausente: {negative_name}")
                        continue
                    for entity in candidate.entities:
                        result = self._compile_reference_pair(
                            positive, negative, candidate, entity, roi
                        )
                        if result is None:
                            errors.append(
                                f"Par não processado: {candidate.id}/{positive_name}/"
                                f"{negative_name}/{entity.id}"
                            )
                            continue
                        diff_mask, bbox, positive_roi_bounds = result
                        identity = entity.identity or entity.id
                        color = self._bbox_color(identity)
                        camera = candidate.camera_id or candidate.scene or "sem-camera"
                        folder = (
                            pack_output / _slug(camera) / _slug(identity)
                            / _slug(positive_name)
                            / _slug(negative_name)
                        )
                        folder.mkdir(parents=True, exist_ok=True)
                        self._write_compile_artifacts(
                            folder,
                            positive,
                            negative,
                            diff_mask,
                            bbox,
                            positive_roi_bounds,
                            color,
                            positive_name,
                            negative_name,
                            candidate_id=candidate.id,
                            parameters={
                                "pixel_threshold": candidate.pixel_threshold,
                                "blur_kernel": candidate.blur_kernel,
                                "open_kernel": candidate.open_kernel,
                                "close_kernel": candidate.close_kernel,
                                "dilate_kernel": candidate.dilate_kernel,
                                "min_component_area": candidate.min_component_area,
                                "reference_scope": candidate.reference_scope,
                                "coordinate_space": candidate.coordinate_space,
                                "roi_id": candidate.roi_id,
                                "roi_bbox": roi.bbox,
                            },
                            positive_sha256=hashlib.sha256(
                                (self.asset_root / positive_name).read_bytes()
                            ).hexdigest(),
                            negative_sha256=hashlib.sha256(
                                (self.asset_root / negative_name).read_bytes()
                            ).hexdigest(),
                        )
                        bbox_key = _compiled_bbox_key(
                            candidate.id, positive_name, negative_name, entity.id
                        )
                        if bbox is not None:
                            compiled_boxes[bbox_key] = [round(value, 8) for value in bbox]
                        relative = folder.relative_to(pack_output).as_posix()
                        rows.append({
                            "camera": camera,
                            "identity": identity,
                            "candidate": candidate.id,
                            "positive": positive_name,
                            "negative": negative_name,
                            "bbox": (
                                ", ".join(f"{value:.4f}" for value in bbox)
                                if bbox is not None else "sem componentes acima do mínimo"
                            ),
                            "color": color,
                            "folder": relative,
                        })

        manifest = {
            "compile_id": compile_id,
            "game_pack_id": self.pack_root.name,
            "pipeline_sha256": pipeline_sha,
            "compiled_at_utc": datetime.now(UTC).isoformat(),
            "bbox_coordinate_space": "normalized full positive asset frame",
            "bbox_colors": self.pipeline.bbox_colors,
            "bboxes": compiled_boxes,
            "errors": errors,
        }
        (pack_output / "active-bboxes.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        index_path = pack_output / "index.html"
        index_path.write_text(_compile_index(rows, errors, compile_id), encoding="utf-8")
        self.compiled_bbox_manifest.parent.mkdir(parents=True, exist_ok=True)
        temporary_manifest = self.compiled_bbox_manifest.with_suffix(".json.tmp")
        temporary_manifest.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        os.replace(temporary_manifest, self.compiled_bbox_manifest)
        self._load_compiled_bboxes()
        return {
            "compile_id": compile_id,
            "game_pack_id": self.pack_root.name,
            "output_dir": str(pack_output),
            "index": str(index_path),
            "active_bbox_manifest": str(self.compiled_bbox_manifest),
            "compiled_variations": len(rows),
            "compiled_bboxes": len(compiled_boxes),
            "errors": errors,
        }

    def _compile_reference_pair(
        self,
        positive: np.ndarray,
        negative: np.ndarray,
        candidate: DifferenceCandidate,
        entity: DifferenceEntity,
        roi: Roi,
    ) -> tuple[
        np.ndarray,
        tuple[float, float, float, float] | None,
        tuple[int, int, int, int],
    ] | None:
        positive_height, positive_width = positive.shape[:2]
        if candidate.reference_scope == "frame":
            positive_source, roi_bounds = self._crop_normalized(
                cv2.cvtColor(positive, cv2.COLOR_BGR2GRAY),
                roi.bbox,
                positive_width,
                positive_height,
            )
            negative_gray = cv2.cvtColor(negative, cv2.COLOR_BGR2GRAY)
            negative_source, _ = self._crop_normalized(
                negative_gray, roi.bbox, negative_gray.shape[1], negative_gray.shape[0]
            )
        else:
            positive_source = cv2.cvtColor(positive, cv2.COLOR_BGR2GRAY)
            negative_source = cv2.cvtColor(negative, cv2.COLOR_BGR2GRAY)
            roi_bounds = (0, 0, positive_width, positive_height)
        if positive_source.size == 0 or negative_source.size == 0:
            return None
        height, width = positive_source.shape[:2]
        negative_resized = cv2.resize(
            negative_source, (width, height), interpolation=cv2.INTER_AREA
        )
        kernel = candidate.blur_kernel + (candidate.blur_kernel % 2 == 0)
        positive_blurred = cv2.GaussianBlur(positive_source, (kernel, kernel), 0)
        negative_blurred = cv2.GaussianBlur(negative_resized, (kernel, kernel), 0)
        mask = (
            cv2.absdiff(positive_blurred, negative_blurred) >= candidate.pixel_threshold
        ).astype(np.uint8) * 255
        mask[self._exclusion_mask(mask.shape, candidate) == 0] = 0
        mask = self._morphology(mask, candidate)
        reference_size = (
            self.pipeline.viewport_registration.reference_size
            if candidate.coordinate_space == "world" and self.pipeline.viewport_registration
            else None
        )
        mask = self._restrict_mask(
            mask, entity, roi_bounds, positive_width, positive_height, 0, reference_size
        )
        count, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
        valid = [
            component for component in range(1, count)
            if int(stats[component, cv2.CC_STAT_AREA]) >= candidate.min_component_area
        ]
        if not valid:
            return mask, None, roi_bounds
        left = min(int(stats[item, cv2.CC_STAT_LEFT]) for item in valid)
        top = min(int(stats[item, cv2.CC_STAT_TOP]) for item in valid)
        right = max(
            int(stats[item, cv2.CC_STAT_LEFT] + stats[item, cv2.CC_STAT_WIDTH])
            for item in valid
        )
        bottom = max(
            int(stats[item, cv2.CC_STAT_TOP] + stats[item, cv2.CC_STAT_HEIGHT])
            for item in valid
        )
        roi_left, roi_top, roi_width, roi_height = roi_bounds
        bbox = (
            (roi_left + left * roi_width / width) / positive_width,
            (roi_top + top * roi_height / height) / positive_height,
            (right - left) * roi_width / width / positive_width,
            (bottom - top) * roi_height / height / positive_height,
        )
        return mask, bbox, roi_bounds

    @staticmethod
    def _write_compile_artifacts(
        folder: Path,
        positive: np.ndarray,
        negative: np.ndarray,
        mask: np.ndarray,
        bbox: tuple[float, float, float, float] | None,
        roi_bounds: tuple[int, int, int, int],
        color: str,
        positive_name: str,
        negative_name: str,
        *,
        candidate_id: str,
        parameters: dict,
        positive_sha256: str,
        negative_sha256: str,
    ) -> None:
        cv2.imwrite(str(folder / "positive.png"), positive)
        cv2.imwrite(str(folder / "negative.png"), negative)
        cv2.imwrite(str(folder / "difference-mask.png"), mask)
        height, width = mask.shape[:2]
        diff_rgba = np.zeros((height, width, 4), dtype=np.uint8)
        diff_rgba[:, :, :3] = (0, 255, 255)
        diff_rgba[:, :, 3] = mask
        cv2.imwrite(str(folder / "difference.png"), cv2.cvtColor(diff_rgba, cv2.COLOR_RGBA2BGRA))
        annotated = positive.copy()
        image_height, image_width = annotated.shape[:2]
        if bbox is not None:
            x = round(bbox[0] * image_width)
            y = round(bbox[1] * image_height)
            box_width = round(bbox[2] * image_width)
            box_height = round(bbox[3] * image_height)
            red, green, blue = (int(color[index:index + 2], 16) for index in (5, 3, 1))
            cv2.rectangle(
                annotated, (x, y), (x + box_width, y + box_height), (blue, green, red), 3
            )
        else:
            x = y = box_width = box_height = 0
        cv2.imwrite(str(folder / "positive-with-bbox.png"), annotated)
        metadata = {
            "candidate_id": candidate_id,
            "positive_asset": positive_name,
            "negative_asset": negative_name,
            "positive_sha256": positive_sha256,
            "negative_sha256": negative_sha256,
            "parameters": parameters,
            "bbox_normalized": [round(value, 8) for value in bbox] if bbox is not None else None,
            "bbox_pixels": [x, y, box_width, box_height] if bbox is not None else None,
            "bbox_color": color,
            "difference_mask_size": [width, height],
            "positive_size": [image_width, image_height],
            "roi_bounds_pixels": list(roi_bounds),
            "artifacts": [
                "positive.png", "negative.png", "difference.png",
                "difference-mask.png", "positive-with-bbox.png",
            ],
        }
        (folder / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    def _bbox_color(self, identity: str) -> str:
        colors = self.pipeline.bbox_colors
        if identity in colors:
            return colors[identity]
        return colors.get(identity.split("_", 1)[0], "#00FF00")

    def _load_compiled_bboxes(self) -> None:
        try:
            stat = self.compiled_bbox_manifest.stat()
        except FileNotFoundError:
            self._compiled_bboxes = {}
            self._compiled_bbox_mtime_ns = None
            return
        if stat.st_mtime_ns == self._compiled_bbox_mtime_ns:
            return
        try:
            payload = json.loads(self.compiled_bbox_manifest.read_text(encoding="utf-8"))
            raw_bboxes = payload.get("bboxes", {})
            self._compiled_bboxes = {
                key: [float(value) for value in bbox]
                for key, bbox in raw_bboxes.items()
                if isinstance(key, str)
                and isinstance(bbox, list)
                and len(bbox) == 4
                and all(isinstance(value, (int, float)) for value in bbox)
                and all(0 <= float(value) <= 1 for value in bbox)
                and float(bbox[2]) > 0
                and float(bbox[3]) > 0
                and float(bbox[0]) + float(bbox[2]) <= 1.000001
                and float(bbox[1]) + float(bbox[3]) <= 1.000001
            }
            self._compiled_bbox_mtime_ns = stat.st_mtime_ns
        except (OSError, json.JSONDecodeError, AttributeError):
            self._compiled_bboxes = {}
            self._compiled_bbox_mtime_ns = None

    @staticmethod
    def _roi_for_frame(
        roi: Roi,
        width: int,
        height: int,
        pan_x: int,
        reference_size: tuple[int, int] | None,
    ) -> Roi | None:
        x, y, roi_width, roi_height = roi.bbox
        if roi.coordinate_space == "screen":
            return roi
        if reference_size is None:
            return None
        reference_width, reference_height = reference_size
        scale = height / reference_height
        left = round((x * reference_width - pan_x) * scale)
        top = round(y * reference_height * scale)
        right = round(((x + roi_width) * reference_width - pan_x) * scale)
        bottom = round((y + roi_height) * reference_height * scale)
        left = max(0, min(width, left))
        top = max(0, min(height, top))
        right = max(left, min(width, right))
        bottom = max(top, min(height, bottom))
        if right <= left or bottom <= top:
            return None
        return roi.model_copy(update={
            "bbox": (left / width, top / height, (right - left) / width, (bottom - top) / height),
            "coordinate_space": "screen",
        })

    def _load_pipeline(self) -> Pipeline:
        pipeline_file = self.pack_root / "vision" / "pipeline.json"
        payload = json.loads(pipeline_file.read_text(encoding="utf-8"))
        return Pipeline.model_validate(payload)

    def _asset(self, name: str) -> np.ndarray | None:
        if name not in self._assets:
            self._assets[name] = cv2.imread(str(self.asset_root / name), cv2.IMREAD_COLOR)
        return self._assets[name]

    def _gray_asset(self, name: str) -> np.ndarray | None:
        if name not in self._gray_assets:
            image = self._asset(name)
            self._gray_assets[name] = (
                cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image is not None else None
            )
        return self._gray_assets[name]

    def _camera_title_mask(self, name: str, size: tuple[int, int]) -> np.ndarray | None:
        key = f"{name}:{size[0]}x{size[1]}"
        if key not in self._camera_title_masks:
            image = self._gray_asset(name)
            if image is None:
                self._camera_title_masks[key] = None
            else:
                resized = cv2.resize(image, size, interpolation=cv2.INTER_AREA)
                self._camera_title_masks[key] = resized > 0
        return self._camera_title_masks[key]

    def _detect_active_camera(
        self,
        image: np.ndarray,
        width: int,
        height: int,
    ) -> tuple[VisionEntity | None, str | None, float]:
        detector = self.pipeline.camera_title_detection
        if detector is None or not detector.enabled or not detector.templates:
            return None, None, 0.0

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        live_crop, _ = self._crop_normalized(gray, detector.roi, width, height)
        if live_crop.size == 0:
            return None, None, 0.0
        target_size = (300, 100)
        resized = cv2.resize(live_crop, target_size, interpolation=cv2.INTER_AREA)
        _, live_mask = cv2.threshold(resized, detector.threshold, 255, cv2.THRESH_BINARY)
        live_mask = cv2.morphologyEx(
            live_mask,
            cv2.MORPH_OPEN,
            cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2)),
        ) > 0

        ranked: list[tuple[float, str]] = []
        for template in detector.templates:
            template_mask = self._camera_title_mask(template.asset, target_size)
            if template_mask is None:
                continue
            intersection = int(np.count_nonzero(live_mask & template_mask))
            union = int(np.count_nonzero(live_mask | template_mask))
            ranked.append((intersection / max(union, 1), template.camera_id))
        if not ranked:
            return None, None, 0.0
        ranked.sort(reverse=True)
        best_score, camera_id = ranked[0]
        second_score = ranked[1][0] if len(ranked) > 1 else 0.0
        if (
            best_score < detector.minimum_score
            or best_score - second_score < detector.minimum_margin
        ):
            return None, None, best_score

        return (
            VisionEntity(
                id=f"camera.active.{camera_id.lower()}",
                kind="camera",
                state="active",
                confidence=best_score,
                bbox=detector.roi,
                detector_id="pack.fnaf1.camera_title",
                evidence=[f"camera_title_template:{camera_id}"],
                properties={
                    "camera_id": camera_id,
                    "scene": "camera",
                    "identification_method": "title_template",
                    "template_score": round(best_score, 4),
                },
                origin=InformationOrigin.OBSERVED_NOW,
            ),
            camera_id,
            best_score,
        )

    def _register_horizontal_viewport(
        self,
        image_bgr: np.ndarray,
        width: int,
        height: int,
    ) -> tuple[int | None, float]:
        registration = self.pipeline.viewport_registration
        if registration is None or not registration.enabled:
            return 0, 1.0

        reference = self._asset(registration.reference_asset)
        if reference is None:
            self._last_pan_x = None
            return None, 0.0
        reference_width, reference_height = registration.reference_size
        reference_gray = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)
        if (
            reference_gray.shape[1] != reference_width
            or reference_gray.shape[0] != reference_height
        ):
            reference_gray = cv2.resize(reference_gray, (reference_width, reference_height))
        if width >= reference_width or height <= 0:
            self._last_pan_x = 0
            return 0, 1.0

        scale = height / reference_height
        viewport_width = max(1, min(reference_width, round(width / scale)))
        max_pan = max(0, reference_width - viewport_width)
        if max_pan == 0:
            self._last_pan_x = 0
            return 0, 1.0

        anchor_x, anchor_y, anchor_width, anchor_height = registration.anchor_roi
        live_left = round(anchor_x * width)
        live_top = round(anchor_y * height)
        live_right = min(width, round((anchor_x + anchor_width) * width))
        live_bottom = min(height, round((anchor_y + anchor_height) * height))
        live_anchor = cv2.cvtColor(
            image_bgr[live_top:live_bottom, live_left:live_right],
            cv2.COLOR_BGR2GRAY,
        )
        if live_anchor.size == 0:
            self._last_pan_x = None
            return None, 0.0
        if float(np.std(live_anchor)) < registration.min_anchor_std:
            self._last_pan_x = None
            return None, 0.0

        source_anchor_width = max(1, round(live_anchor.shape[1] / scale))
        source_anchor_height = max(1, round(live_anchor.shape[0] / scale))
        source_anchor_y = max(
            0,
            min(reference_height - source_anchor_height, round(live_top / scale)),
        )
        min_pan = max(0, round(registration.search_range[0] * max_pan))
        max_pan = min(max_pan, round(registration.search_range[1] * max_pan))
        if max_pan < min_pan:
            min_pan, max_pan = max_pan, min_pan

        def score(pan_x: int) -> float:
            source_x = min(
                max(0, pan_x + round(live_left / scale)),
                reference_width - source_anchor_width,
            )
            reference_anchor = reference_gray[
                source_anchor_y : source_anchor_y + source_anchor_height,
                source_x : source_x + source_anchor_width,
            ]
            reference_anchor = cv2.resize(
                reference_anchor,
                (live_anchor.shape[1], live_anchor.shape[0]),
                interpolation=cv2.INTER_AREA,
            )
            return float(np.mean(cv2.absdiff(live_anchor, reference_anchor)))

        coarse_step = max(1, round(registration.coarse_step * reference_width))
        previous_pan_x = self._last_pan_x
        if previous_pan_x is not None:
            local_min = max(min_pan, previous_pan_x - 2 * coarse_step)
            local_max = min(max_pan, previous_pan_x + 2 * coarse_step)
            local_positions = range(local_min, local_max + 1, coarse_step)
            local_pan = min(local_positions, key=score)
            if score(local_pan) <= registration.max_anchor_error:
                best_pan = local_pan
            else:
                coarse_positions = range(min_pan, max_pan + 1, coarse_step)
                best_pan = min(coarse_positions, key=score)
        else:
            coarse_positions = range(min_pan, max_pan + 1, coarse_step)
            best_pan = min(coarse_positions, key=score)
        refine_step = max(1, round(registration.refine_step * reference_width))
        refine_min = max(min_pan, best_pan - coarse_step)
        refine_max = min(max_pan, best_pan + coarse_step)
        best_pan = min(range(refine_min, refine_max + 1, refine_step), key=score)
        error = score(best_pan)
        confidence = max(0.0, min(1.0, 1.0 - error / 40.0))
        if error > registration.max_anchor_error or confidence < registration.min_confidence:
            self._last_pan_x = None
            return None, confidence
        if (
            previous_pan_x is not None
            and abs(best_pan - previous_pan_x) > registration.max_pan_jump_px
        ):
            self._last_pan_x = None
            return None, confidence
        self._last_pan_x = best_pan
        return best_pan, confidence

    def _detect_candidate(
        self,
        live_gray: np.ndarray,
        candidate: DifferenceCandidate,
        roi: Roi,
        width: int,
        height: int,
        pan_x: int,
        pan_confidence: float,
    ) -> list[VisionEntity]:
        positive_assets = candidate.positive_assets or [candidate.positive_asset]
        best_entities: list[VisionEntity] = []
        best_rank = (-1, -1.0, -1.0)
        for positive_asset in positive_assets:
            negative_assets = candidate.negative_assets or [candidate.negative_asset]
            variants: list[list[VisionEntity]] = []
            for negative_asset in negative_assets:
                entities_for_pair = []
                for entity in candidate.entities:
                    compiled_bbox = self._compiled_bboxes.get(_compiled_bbox_key(
                        candidate.id, positive_asset, negative_asset, entity.id
                    ))
                    bbox_hint = compiled_bbox or candidate.positive_asset_bboxes.get(positive_asset)
                    if bbox_hint is None:
                        entities_for_pair.append(entity)
                    else:
                        entities_for_pair.append(entity.model_copy(update={
                            "bbox": tuple(bbox_hint),
                            "bbox_scope": (
                                "reference"
                                if (
                                    compiled_bbox is not None
                                    and candidate.coordinate_space == "world"
                                )
                                else "frame"
                            ),
                            "bbox_mode": "hint",
                        }))
                single = candidate.model_copy(update={
                    "positive_asset": positive_asset,
                    "positive_assets": [],
                    "positive_asset_bboxes": {},
                    "negative_asset": negative_asset,
                    "negative_assets": [],
                    "entities": entities_for_pair,
                })
                variants.append(self._detect_candidate_single(
                    live_gray, single, roi, width, height, pan_x, pan_confidence
                ))
            if len(variants) > 1:
                # A positive signature must beat every configured negative example.
                # Conflicting references remain inconclusive instead of voting positive.
                if any(not entities for entities in variants):
                    continue
                states = [{entity.state for entity in entities} for entities in variants]
                if any(len(state) != 1 for state in states) or len(
                    {next(iter(state)) for state in states}
                ) != 1:
                    continue
                if next(iter(states[0])) != "present":
                    entities = variants[0]
                else:
                    entities = [min(
                        (variant[index] for variant in variants),
                        key=lambda entity: entity.confidence,
                    )
                        for index in range(min(len(variant) for variant in variants))]
            else:
                entities = variants[0]
            if not entities:
                continue
            margin = max(
                abs(
                    float(entity.properties.get("positive_score", 0.0))
                    - float(entity.properties.get("negative_score", 0.0))
                )
                for entity in entities
            )
            rank = (
                int(any(entity.state != "absent" for entity in entities)),
                max(entity.confidence for entity in entities),
                margin,
            )
            if rank > best_rank:
                best_rank = rank
                best_entities = entities
        return best_entities

    def _detect_candidate_single(
        self,
        live_gray: np.ndarray,
        candidate: DifferenceCandidate,
        roi: Roi,
        width: int,
        height: int,
        pan_x: int,
        pan_confidence: float,
    ) -> list[VisionEntity]:
        positive = self._asset(candidate.positive_asset)
        negative = self._asset(candidate.negative_asset)
        if positive is None or negative is None:
            return []

        live_crop, roi_bounds = self._crop_normalized(live_gray, roi.bbox, width, height)
        if live_crop.size == 0:
            return []
        roi_left, roi_top, roi_width, roi_height = roi_bounds
        reference_size = (
            self.pipeline.viewport_registration.reference_size
            if candidate.coordinate_space == "world" and self.pipeline.viewport_registration
            else None
        )

        kernel = candidate.blur_kernel + (candidate.blur_kernel % 2 == 0)
        signature_key = (
            candidate.id,
            candidate.positive_asset,
            candidate.negative_asset,
            roi_bounds,
            width,
            height,
            pan_x,
            candidate.pixel_threshold,
            kernel,
        )
        prepared = self._reference_signatures.get(signature_key)
        if prepared is None:
            if candidate.coordinate_space == "world":
                positive_gray = self._viewport_gray(positive, pan_x, width, height)
                negative_gray = self._viewport_gray(negative, pan_x, width, height)
                reference_size = self.pipeline.viewport_registration.reference_size
                positive_gray = cv2.resize(
                    positive_gray,
                    (width, height),
                    interpolation=cv2.INTER_AREA,
                )
                negative_gray = cv2.resize(
                    negative_gray,
                    (width, height),
                    interpolation=cv2.INTER_AREA,
                )
                positive_gray = positive_gray[
                    roi_top : roi_top + roi_height,
                    roi_left : roi_left + roi_width,
                ]
                negative_gray = negative_gray[
                    roi_top : roi_top + roi_height,
                    roi_left : roi_left + roi_width,
                ]
            else:
                positive_gray_full = cv2.cvtColor(positive, cv2.COLOR_BGR2GRAY)
                negative_gray_full = cv2.cvtColor(negative, cv2.COLOR_BGR2GRAY)
                if candidate.reference_scope == "frame":
                    positive_gray, _ = self._crop_normalized(
                        positive_gray_full,
                        roi.bbox,
                        positive_gray_full.shape[1],
                        positive_gray_full.shape[0],
                    )
                    negative_gray, _ = self._crop_normalized(
                        negative_gray_full,
                        roi.bbox,
                        negative_gray_full.shape[1],
                        negative_gray_full.shape[0],
                    )
                else:
                    positive_gray = positive_gray_full
                    negative_gray = negative_gray_full
                reference_size = None
                positive_gray = cv2.resize(
                    positive_gray,
                    (roi_width, roi_height),
                    interpolation=cv2.INTER_AREA,
                )
                negative_gray = cv2.resize(
                    negative_gray,
                    (roi_width, roi_height),
                    interpolation=cv2.INTER_AREA,
                )
            positive_blurred = cv2.GaussianBlur(positive_gray, (kernel, kernel), 0)
            negative_blurred = cv2.GaussianBlur(negative_gray, (kernel, kernel), 0)
            exclusion_mask = self._exclusion_mask(positive_blurred.shape, candidate)
            expected_mask = (
                cv2.absdiff(positive_blurred, negative_blurred) >= candidate.pixel_threshold
            ) & exclusion_mask
            prepared = (positive_blurred, negative_blurred, exclusion_mask, expected_mask)
            if len(self._reference_signatures) >= 64:
                self._reference_signatures.clear()
            self._reference_signatures[signature_key] = prepared
        positive_blurred, negative_blurred, exclusion_mask, expected_mask = prepared

        live_crop = cv2.resize(live_crop, (roi_width, roi_height), interpolation=cv2.INTER_AREA)
        live_blurred = cv2.GaussianBlur(live_crop, (kernel, kernel), 0)
        positive_score, positive_mask, positive_metrics = self._signature_score(
            live_blurred,
            positive_blurred,
            negative_blurred,
            candidate,
            exclusion_mask,
            expected_mask,
        )
        negative_score, negative_mask, negative_metrics = self._signature_score(
            live_blurred,
            negative_blurred,
            positive_blurred,
            candidate,
            exclusion_mask,
            expected_mask,
        )
        if (
            max(positive_score, negative_score) < candidate.threshold
            or abs(positive_score - negative_score) < candidate.min_score_margin
        ):
            return []

        is_present = positive_score >= negative_score
        score = positive_score if is_present else negative_score
        mask = positive_mask if is_present else negative_mask
        metrics = positive_metrics if is_present else negative_metrics
        if not is_present:
            return [
                VisionEntity(
                    id=f"difference.{candidate.id}.{entity.id}",
                    kind=entity.kind,
                    state="absent",
                    confidence=score,
                    bbox=None,
                    detector_id=self.pipeline.difference_detection.id,
                    evidence=[
                        f"negative:{candidate.negative_asset}",
                        f"positive:{candidate.positive_asset}",
                        f"roi:{candidate.roi_id}",
                        f"difference_score:{score:.3f}",
                    ],
                    properties={
                        "label": entity.label,
                        "identity": entity.identity,
                        "bbox_color": self._bbox_color(entity.identity or entity.id),
                        "candidate_id": candidate.id,
                        "roi_id": candidate.roi_id,
                        "coordinate_space": candidate.coordinate_space,
                        "scene": candidate.scene,
                        "camera_id": candidate.camera_id,
                        "interactive": entity.kind == "interaction",
                        "pan_x": pan_x,
                        "pan_confidence": round(pan_confidence, 4),
                        "positive_score": round(positive_score, 4),
                        "negative_score": round(negative_score, 4),
                    },
                    origin=InformationOrigin.OBSERVED_NOW,
                )
                for entity in candidate.entities
            ]

        mask = self._morphology(mask, candidate)
        components, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
        valid_components = [
            component
            for component in range(1, components)
            if int(stats[component, cv2.CC_STAT_AREA]) >= candidate.min_component_area
        ]
        if not valid_components:
            return []

        entities: list[VisionEntity] = []
        for entity in candidate.entities:
            entity_mask = self._restrict_mask(
                mask,
                entity,
                roi_bounds,
                width,
                height,
                pan_x,
                reference_size,
            )
            entity_components, _, entity_stats, _ = cv2.connectedComponentsWithStats(entity_mask, 8)
            selected = [
                component
                for component in range(1, entity_components)
                if int(entity_stats[component, cv2.CC_STAT_AREA]) >= candidate.min_component_area
            ]
            if not selected:
                continue

            if entity.bbox is not None and entity.bbox_mode == "hint":
                bbox = self._hint_bbox(
                    entity,
                    roi_bounds,
                    width,
                    height,
                    pan_x,
                    reference_size,
                )
                if bbox is None:
                    continue
            else:
                left = min(int(entity_stats[c, cv2.CC_STAT_LEFT]) for c in selected)
                top = min(int(entity_stats[c, cv2.CC_STAT_TOP]) for c in selected)
                right = max(
                    int(entity_stats[c, cv2.CC_STAT_LEFT])
                    + int(entity_stats[c, cv2.CC_STAT_WIDTH])
                    for c in selected
                )
                bottom = max(
                    int(entity_stats[c, cv2.CC_STAT_TOP])
                    + int(entity_stats[c, cv2.CC_STAT_HEIGHT])
                    for c in selected
                )
                bbox = (
                    (roi_left + left) / width,
                    (roi_top + top) / height,
                    (right - left) / width,
                    (bottom - top) / height,
                )

            properties = {
                "label": entity.label,
                "bbox_color": self._bbox_color(entity.identity or entity.id),
                "candidate_id": candidate.id,
                "positive_asset": candidate.positive_asset,
                "negative_asset": candidate.negative_asset,
                "roi_id": candidate.roi_id,
                "coordinate_space": candidate.coordinate_space,
                "pan_x": pan_x,
                "pan_confidence": round(pan_confidence, 4),
                "difference_score": round(score, 4),
                "difference_precision": round(metrics["precision"], 4),
                "background_error": round(metrics["background_error"], 4),
                "expected_pixels": metrics["expected_pixels"],
                "observed_pixels": metrics["overlap_count"],
                "positive_score": round(positive_score, 4),
                "negative_score": round(negative_score, 4),
                "scene": candidate.scene,
                "camera_id": candidate.camera_id,
                "interactive": entity.kind == "interaction",
            }
            if entity.identity is not None:
                properties["identity"] = entity.identity
            entities.append(
                VisionEntity(
                    id=f"difference.{candidate.id}.{entity.id}",
                    kind=entity.kind,
                    state=entity.state,
                    confidence=score,
                    bbox=bbox,
                    detector_id=self.pipeline.difference_detection.id,
                    evidence=[
                        f"positive:{candidate.positive_asset}",
                        f"negative:{candidate.negative_asset}",
                        f"roi:{candidate.roi_id}",
                        f"pan_x:{pan_x}",
                        f"difference_score:{score:.3f}",
                    ],
                    properties=properties,
                    origin=InformationOrigin.OBSERVED_NOW,
                )
            )
        return entities

    @staticmethod
    def _exclusion_mask(
        shape: tuple[int, int],
        candidate: DifferenceCandidate,
    ) -> np.ndarray:
        allowed = np.ones(shape, dtype=bool)
        height, width = shape
        for x, y, region_width, region_height in candidate.exclusion_regions:
            left = max(0, min(width, round(x * width)))
            top = max(0, min(height, round(y * height)))
            right = max(left, min(width, round((x + region_width) * width)))
            bottom = max(top, min(height, round((y + region_height) * height)))
            allowed[top:bottom, left:right] = False
        return allowed

    @staticmethod
    def _signature_score(
        live: np.ndarray,
        target: np.ndarray,
        alternative: np.ndarray,
        candidate: DifferenceCandidate,
        allowed: np.ndarray,
        expected_mask: np.ndarray | None = None,
    ) -> tuple[float, np.ndarray, dict[str, float | int]]:
        observed_difference = cv2.absdiff(live, alternative)
        if expected_mask is None:
            expected_difference = cv2.absdiff(target, alternative)
            expected_mask = (expected_difference >= candidate.pixel_threshold) & allowed
        observed_mask = (observed_difference >= candidate.pixel_threshold) & allowed
        expected_count = int(np.count_nonzero(expected_mask))
        if expected_count == 0:
            return 0.0, np.zeros(live.shape, dtype=np.uint8), {
                "precision": 0.0,
                "background_error": 255.0,
                "expected_pixels": 0,
                "overlap_count": 0,
            }

        overlap = expected_mask & observed_mask
        overlap_count = int(np.count_nonzero(overlap))
        observed_count = int(np.count_nonzero(observed_mask))
        recall = overlap_count / expected_count
        precision = overlap_count / max(observed_count, 1)
        target_error = float(np.mean(cv2.absdiff(live, target)))
        alternative_error = float(np.mean(cv2.absdiff(live, alternative)))
        contrast = (alternative_error - target_error) / max(
            alternative_error + target_error,
            1.0,
        )
        background_values = observed_difference[allowed & ~expected_mask]
        background_error = float(np.mean(background_values)) if background_values.size else 0.0
        background_support = max(
            0.0,
            min(1.0, 1.0 - background_error / candidate.background_threshold),
        )
        score = max(
            0.0,
            min(
                1.0,
                0.45 * recall
                + 0.25 * precision
                + 0.15 * ((contrast + 1.0) / 2.0)
                + 0.15 * background_support,
            ),
        )
        return score, np.where(overlap, 255, 0).astype(np.uint8), {
            "precision": precision,
            "background_error": background_error,
            "expected_pixels": expected_count,
            "overlap_count": overlap_count,
        }

    def _viewport_gray(
        self,
        source: np.ndarray,
        pan_x: int,
        width: int,
        height: int,
    ) -> np.ndarray:
        registration = self.pipeline.viewport_registration
        if registration is None:
            return cv2.cvtColor(source, cv2.COLOR_BGR2GRAY)
        reference_width, reference_height = registration.reference_size
        source_gray = cv2.cvtColor(source, cv2.COLOR_BGR2GRAY)
        source_gray = cv2.resize(
            source_gray,
            (reference_width, reference_height),
            interpolation=cv2.INTER_AREA,
        )
        scale = height / reference_height
        viewport_width = max(1, min(reference_width, round(width / scale)))
        left = max(0, min(reference_width - viewport_width, pan_x))
        viewport = source_gray[:, left : left + viewport_width]
        return cv2.resize(viewport, (width, height), interpolation=cv2.INTER_AREA)

    @staticmethod
    def _crop_normalized(
        image: np.ndarray,
        bbox: tuple[float, float, float, float],
        width: int,
        height: int,
    ) -> tuple[np.ndarray, tuple[int, int, int, int]]:
        left = max(0, min(width, round(bbox[0] * width)))
        top = max(0, min(height, round(bbox[1] * height)))
        right = max(left, min(width, round((bbox[0] + bbox[2]) * width)))
        bottom = max(top, min(height, round((bbox[1] + bbox[3]) * height)))
        return image[top:bottom, left:right], (left, top, right - left, bottom - top)

    @staticmethod
    def _morphology(mask: np.ndarray, candidate: DifferenceCandidate) -> np.ndarray:
        result = mask
        if candidate.open_kernel > 1:
            result = cv2.morphologyEx(
                result,
                cv2.MORPH_OPEN,
                np.ones((candidate.open_kernel, candidate.open_kernel), np.uint8),
            )
        if candidate.close_kernel > 1:
            result = cv2.morphologyEx(
                result,
                cv2.MORPH_CLOSE,
                np.ones((candidate.close_kernel, candidate.close_kernel), np.uint8),
            )
        if candidate.dilate_kernel > 1:
            result = cv2.dilate(
                result,
                np.ones((candidate.dilate_kernel, candidate.dilate_kernel), np.uint8),
            )
        return result

    @staticmethod
    def _scope_bbox(
        entity: DifferenceEntity,
        roi_bounds: tuple[int, int, int, int],
        width: int,
        height: int,
        pan_x: int,
        reference_size: tuple[int, int] | None,
    ) -> tuple[int, int, int, int] | None:
        if entity.bbox is None:
            return None
        x, y, box_width, box_height = entity.bbox
        roi_left, roi_top, roi_width, roi_height = roi_bounds
        if entity.bbox_scope == "reference":
            if reference_size is None:
                return None
            reference_width, reference_height = reference_size
            scale = height / reference_height
            return (
                round((x * reference_width - pan_x) * scale) - roi_left,
                round(y * reference_height * scale) - roi_top,
                round(box_width * reference_width * scale),
                round(box_height * reference_height * scale),
            )
        if entity.bbox_scope == "frame":
            return (
                round(x * width) - roi_left,
                round(y * height) - roi_top,
                round(box_width * width),
                round(box_height * height),
            )
        return (
            round(x * roi_width),
            round(y * roi_height),
            round(box_width * roi_width),
            round(box_height * roi_height),
        )

    @classmethod
    def _restrict_mask(
        cls,
        mask: np.ndarray,
        entity: DifferenceEntity,
        roi_bounds: tuple[int, int, int, int],
        width: int,
        height: int,
        pan_x: int,
        reference_size: tuple[int, int] | None,
    ) -> np.ndarray:
        scope = cls._scope_bbox(entity, roi_bounds, width, height, pan_x, reference_size)
        if scope is None:
            return mask
        left, top, box_width, box_height = scope
        right = left + box_width
        bottom = top + box_height
        restricted = np.zeros_like(mask)
        left = max(0, min(mask.shape[1], left))
        top = max(0, min(mask.shape[0], top))
        right = max(left, min(mask.shape[1], right))
        bottom = max(top, min(mask.shape[0], bottom))
        restricted[top:bottom, left:right] = mask[top:bottom, left:right]
        return restricted

    @classmethod
    def _hint_bbox(
        cls,
        entity: DifferenceEntity,
        roi_bounds: tuple[int, int, int, int],
        width: int,
        height: int,
        pan_x: int,
        reference_size: tuple[int, int] | None,
    ) -> tuple[float, float, float, float] | None:
        scope = cls._scope_bbox(entity, roi_bounds, width, height, pan_x, reference_size)
        if scope is None:
            raise ValueError("difference bbox hint requires a valid entity bbox")
        left, top, box_width, box_height = scope
        roi_left, roi_top, _, _ = roi_bounds
        pixel_left = max(0, min(width, roi_left + left))
        pixel_top = max(0, min(height, roi_top + top))
        pixel_right = max(pixel_left, min(width, roi_left + left + box_width))
        pixel_bottom = max(pixel_top, min(height, roi_top + top + box_height))
        if pixel_right <= pixel_left or pixel_bottom <= pixel_top:
            return None
        return (
            pixel_left / width,
            pixel_top / height,
            (pixel_right - pixel_left) / width,
            (pixel_bottom - pixel_top) / height,
        )
