import json
from pathlib import Path
from time import time_ns

import cv2
import numpy as np

from agentic_gaming.gamepacks import GamePackRegistry
from agentic_gaming.vision_host import GamePackVisionHost

REFERENCE_TEST_CATALOG = json.loads(
    Path("game-packs/fnaf1/vision/reference-tests.json").read_text(encoding="utf-8")
)
REFERENCE_TESTS = REFERENCE_TEST_CATALOG["cases"]
INGAME_EVAL_CATALOG = json.loads(
    Path("game-packs/fnaf1/vision/ingame-eval.json").read_text(encoding="utf-8")
)


def test_fnaf1_difference_detector_marks_character_without_template_or_yolo():
    registry = GamePackRegistry(Path("game-packs"))
    registry.load()
    pack = registry.get("fnaf1")
    frame_path = Path("data/games/FNAF1/assets/227.png")

    vision = GamePackVisionHost().observe(
        frame_id="asset-frame-227",
        captured_at_ns=time_ns(),
        width=1600,
        height=720,
        frame_bytes=frame_path.read_bytes(),
        game_pack=pack,
    )

    characters = [entity for entity in vision.entities if entity.kind == "character"]

    assert characters
    assert characters[0].properties["identity"] == "chica"
    assert characters[0].properties["candidate_id"] == "office_chica_right_door"
    assert characters[0].bbox is not None
    assert not [entity for entity in vision.entities if entity.kind == "interaction"]
    assert vision.detector_id == "pack.fnaf1.difference_roi"
    assert vision.detector_status == "ready"
    assert vision.processing_ms is not None


def test_fnaf1_difference_detector_rejects_the_negative_character_reference():
    registry = GamePackRegistry(Path("game-packs"))
    registry.load()
    pack = registry.get("fnaf1")
    source = cv2.imread("data/games/FNAF1/assets/127.png", cv2.IMREAD_COLOR)
    assert source is not None
    _, encoded = cv2.imencode(".png", source)

    vision = GamePackVisionHost().observe(
        frame_id="negative-reference-127",
        captured_at_ns=time_ns(),
        width=source.shape[1],
        height=source.shape[0],
        frame_bytes=encoded.tobytes(),
        game_pack=pack,
    )

    characters = [entity for entity in vision.entities if entity.kind == "character"]

    assert len(characters) == 1
    assert characters[0].state == "absent"
    assert characters[0].bbox is None
    assert vision.detector_id == "pack.fnaf1.difference_roi"
    assert vision.detector_status == "ready"


def test_fnaf1_world_signature_registers_horizontal_viewport_before_difference():
    registry = GamePackRegistry(Path("game-packs"))
    registry.load()
    pack = registry.get("fnaf1")
    source = cv2.imread("data/games/FNAF1/assets/227.png", cv2.IMREAD_COLOR)
    assert source is not None
    viewport = source[:, 180:1407]
    _, encoded = cv2.imencode(".png", viewport)

    vision = GamePackVisionHost().observe(
        frame_id="viewport-227",
        captured_at_ns=time_ns(),
        width=viewport.shape[1],
        height=viewport.shape[0],
        frame_bytes=encoded.tobytes(),
        game_pack=pack,
    )

    characters = [entity for entity in vision.entities if entity.kind == "character"]

    assert len(characters) == 1
    assert characters[0].properties["identity"] == "chica"
    assert characters[0].properties["coordinate_space"] == "world"
    assert abs(characters[0].properties["pan_x"] - 180) <= 5
    assert characters[0].properties["pan_confidence"] > 0.7


def test_fnaf1_difference_panel_emits_only_the_active_left_door():
    registry = GamePackRegistry(Path("game-packs"))
    registry.load()
    pack = registry.get("fnaf1")
    panel = cv2.imread("data/games/FNAF1/assets/124.png", cv2.IMREAD_COLOR)
    assert panel is not None
    frame = np.zeros((720, 1600, 3), dtype=np.uint8)
    panel = cv2.resize(panel, (104, 259), interpolation=cv2.INTER_AREA)
    frame[288:547, 24:128] = panel
    _, encoded = cv2.imencode(".png", frame)

    vision = GamePackVisionHost().observe(
        frame_id="asset-control-panel-124",
        captured_at_ns=time_ns(),
        width=frame.shape[1],
        height=frame.shape[0],
        frame_bytes=encoded.tobytes(),
        game_pack=pack,
    )

    interactions = [entity for entity in vision.entities if entity.kind == "interaction"]
    active_interactions = [entity for entity in interactions if entity.state == "present"]
    labels = {entity.properties["label"] for entity in active_interactions}

    assert labels == {"left door"}
    assert all(entity.origin.value == "observed_now" for entity in active_interactions)
    assert all(
        entity.detector_id == "pack.fnaf1.difference_roi"
        for entity in active_interactions
    )
    assert all(
        entity.properties["roi_id"] == "left_control_panel"
        for entity in active_interactions
    )


def test_fnaf1_rejects_world_observations_when_viewport_registration_is_unreliable():
    registry = GamePackRegistry(Path("game-packs"))
    registry.load()
    pack = registry.get("fnaf1")
    frame = np.zeros((720, 1227, 3), dtype=np.uint8)
    _, encoded = cv2.imencode(".png", frame)

    vision = GamePackVisionHost().observe(
        frame_id="unregistered-world-frame",
        captured_at_ns=time_ns(),
        width=frame.shape[1],
        height=frame.shape[0],
        frame_bytes=encoded.tobytes(),
        game_pack=pack,
    )

    world_entities = [
        entity for entity in vision.entities
        if entity.properties.get("coordinate_space") == "world"
    ]
    assert not world_entities
    assert vision.detector_status == "insufficient_evidence"


def test_fnaf1_curated_reference_frames_reach_the_expected_observations():
    registry = GamePackRegistry(Path("game-packs"))
    registry.load()
    pack = registry.get("fnaf1")
    observer = GamePackVisionHost()
    failures = []

    for index, case in enumerate(REFERENCE_TESTS):
        frame_path = Path("data/games/FNAF1/assets") / case["asset"]
        vision = observer.observe(
            frame_id=f"curated-reference-{index}-{frame_path.stem}",
            captured_at_ns=time_ns(),
            width=1600 if frame_path.stem != "358" else 1280,
            height=720,
            frame_bytes=frame_path.read_bytes(),
            game_pack=pack,
        )
        matches = [
            entity
            for entity in vision.entities
            if entity.properties.get("candidate_id") == case["candidate_id"]
            and entity.properties.get("identity") == case["identity"]
            and entity.state == case["state"]
        ]
        if not matches:
            failures.append(f"{case['asset']} -> {case['candidate_id']} ({case['state']})")
            continue
        entity = matches[0]
        if entity.bbox is None or not all(0 <= coordinate <= 1 for coordinate in entity.bbox):
            failures.append(f"{case['asset']} -> missing/invalid normalized bbox")
        if entity.kind != case["kind"]:
            failures.append(f"{case['asset']} -> kind {entity.kind!r}, expected {case['kind']!r}")
        if entity.properties.get("camera_id") != case["camera_id"]:
            failures.append(
                f"{case['asset']} -> camera {entity.properties.get('camera_id')!r}, "
                f"expected {case['camera_id']!r}"
            )
        if f"positive:{case['asset']}" not in entity.evidence:
            failures.append(f"{case['asset']} -> expected source asset missing from evidence")

    for index, case in enumerate(REFERENCE_TEST_CATALOG["negative_cases"]):
        frame_path = Path("data/games/FNAF1/assets") / case["asset"]
        vision = observer.observe(
            frame_id=f"curated-negative-{index}-{frame_path.stem}",
            captured_at_ns=time_ns(),
            width=1600,
            height=720,
            frame_bytes=frame_path.read_bytes(),
            game_pack=pack,
        )
        false_positives = [
            entity
            for entity in vision.entities
            if entity.properties.get("candidate_id") == case["candidate_id"]
            and entity.state != "absent"
        ]
        if false_positives:
            failures.append(
                f"negative {case['asset']} -> unexpected positive for {case['candidate_id']}"
            )

    assert not failures, "Curated reference mismatches:\n" + "\n".join(failures)


def test_fnaf1_ingame_eval_frames_identify_camera_and_expected_animatronics():
    registry = GamePackRegistry(Path("game-packs"))
    registry.load()
    pack = registry.get("fnaf1")
    observer = GamePackVisionHost()

    for index, case in enumerate(INGAME_EVAL_CATALOG["samples"]):
        frame_path = Path(case["image"])
        source = cv2.imread(str(frame_path), cv2.IMREAD_COLOR)
        assert source is not None, f"Could not load in-game evaluation image: {frame_path}"
        _, encoded = cv2.imencode(".png", source)
        vision = observer.observe(
            frame_id=f"ingame-eval-{index}-{frame_path.stem}",
            captured_at_ns=time_ns(),
            width=source.shape[1],
            height=source.shape[0],
            frame_bytes=encoded.tobytes(),
            game_pack=pack,
        )
        camera_entities = [entity for entity in vision.entities if entity.kind == "camera"]
        if case["camera_id"] is None:
            assert not camera_entities, f"Unexpected camera classification for {frame_path}"
        else:
            assert len(camera_entities) == 1
            assert camera_entities[0].properties["camera_id"] == case["camera_id"]
            assert vision.scene == "camera"

        detected_labels = {
            entity.properties.get("label")
            for entity in vision.entities
            if entity.state != "absent" and entity.kind != "camera"
        }
        assert not (set(case.get("forbidden_labels", [])) & detected_labels), (
            f"{frame_path} produced forbidden labels "
            f"{set(case.get('forbidden_labels', [])) & detected_labels}"
        )
        assert set(case["expected_labels"]).issubset(detected_labels), (
            f"{frame_path} missing {set(case['expected_labels']) - detected_labels}; "
            f"detected {detected_labels}"
        )
