import base64
import shutil
import threading
from pathlib import Path
from time import time_ns

import cv2
from fastapi.testclient import TestClient

from agentic_gaming.contracts import VisionState
from agentic_gaming.main import create_app
from agentic_gaming.vision_host import GamePackVisionHost


def test_bridge_status_and_events_follow_authenticated_frame(monkeypatch):
    artifact_dir = Path("data") / "test-bridge-artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("BRIDGE_ARTIFACTS_DIR", str(artifact_dir))

    try:
        with TestClient(create_app()) as client:
            with client.websocket_connect(
                "/ws/host-bridge",
                headers={"X-Bridge-Token": "dev-only-change-me"},
            ) as websocket:
                websocket.send_json({
                    "type": "hello",
                    "protocol_version": "1.0",
                    "client_id": "test-bridge",
                    "capabilities": ["screen_capture"],
                    "dry_run": True,
                    "profile_id": "fnaf1",
                    "safe_capture": False,
                })
                assert websocket.receive_json()["type"] == "hello_ack"

                websocket.send_json({
                    "type": "frame",
                    "frame_id": "test-frame",
                    "captured_at_ns": 1,
                    "width": 320,
                    "height": 200,
                    "encoding": "png",
                    "data_base64": base64.b64encode(b"png-test").decode(),
                    "source_window_title": "Test Game",
                    "source_process_id": 1234,
                })
                assert websocket.receive_json()["type"] == "frame_ack"

                status = client.get("/api/bridge/status").json()
                assert status["status"] == "CONNECTED"
                assert status["profile_id"] == "fnaf1"
                assert status["window_title"] == "Test Game"
                assert status["process_id"] == 1234
                assert status["frames_received"] == 1
                assert status["last_frame_id"] == "test-frame"

                events = client.get("/api/bridge/events?limit=10").json()
                assert [event["event_type"] for event in events[:3]] == [
                    "bridge.frame.received",
                    "bridge.hello",
                    "bridge.connected",
                ]
    finally:
        shutil.rmtree(artifact_dir, ignore_errors=True)


def test_bridge_sends_vision_annotations_for_a_real_asset(monkeypatch):
    artifact_dir = Path("data") / "test-bridge-vision-artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("BRIDGE_ARTIFACTS_DIR", str(artifact_dir))
    frame_path = Path("data/games/FNAF1/assets/227.png")

    try:
        with TestClient(create_app()) as client:
            with client.websocket_connect(
                "/ws/host-bridge",
                headers={"X-Bridge-Token": "dev-only-change-me"},
            ) as websocket:
                websocket.send_json({
                    "type": "hello",
                    "protocol_version": "beta-4",
                    "client_id": "test-vision-bridge",
                    "capabilities": ["screen_capture", "vision_overlay"],
                    "dry_run": True,
                    "profile_id": "fnaf1",
                    "safe_capture": False,
                })
                assert websocket.receive_json()["type"] == "hello_ack"

                websocket.send_json({
                    "type": "frame",
                    "frame_id": "asset-frame-227",
                    "captured_at_ns": time_ns(),
                    "width": 1600,
                    "height": 720,
                    "encoding": "png",
                    "data_base64": base64.b64encode(frame_path.read_bytes()).decode(),
                    "source_window_title": "FNAF 1",
                    "source_process_id": 1234,
                })

                assert websocket.receive_json()["type"] == "frame_ack"
                annotations = websocket.receive_json()

                assert annotations["type"] == "vision_annotations"
                assert annotations["protocol_version"] == "beta-4"
                assert any(box["kind"] == "character" for box in annotations["boxes"])
                assert not any(box["kind"] == "interaction" for box in annotations["boxes"])
                vision = client.get("/api/bridge/latest-vision").json()
                assert vision["frame_id"] == "asset-frame-227"
                vision_frame = client.get(vision["raw_frame_ref"])
                assert vision_frame.status_code == 200
                assert vision_frame.headers["X-Frame-ID"] == vision["frame_id"]
                assert vision_frame.content == frame_path.read_bytes()
                assert client.get(
                    "/api/bridge/latest-vision-frame?frame_id=stale-frame"
                ).status_code == 409
    finally:
        shutil.rmtree(artifact_dir, ignore_errors=True)


def test_bridge_processes_curated_camera_and_event_reference_assets(monkeypatch):
    artifact_dir = Path("data") / "test-bridge-reference-assets"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("BRIDGE_ARTIFACTS_DIR", str(artifact_dir))
    cases = [
        ("241", "character", "running", "Foxy"),
        ("553", "event", "imminent", "Foxy attack imminent"),
        ("487", "character", "present", "Freddy"),
        ("486", "character", "present", "Freddy"),
        ("555", "character", "present", "Bonnie"),
        ("358", "event", "game_over", "Game over"),
    ]

    try:
        with TestClient(create_app()) as client:
            with client.websocket_connect(
                "/ws/host-bridge",
                headers={"X-Bridge-Token": "dev-only-change-me"},
            ) as websocket:
                websocket.send_json({
                    "type": "hello",
                    "protocol_version": "beta-4",
                    "client_id": "test-reference-assets",
                    "capabilities": ["screen_capture", "vision_overlay"],
                    "dry_run": True,
                    "profile_id": "fnaf1",
                    "safe_capture": False,
                })
                assert websocket.receive_json()["type"] == "hello_ack"

                for asset_id, kind, state, label in cases:
                    frame_path = Path(f"data/games/FNAF1/assets/{asset_id}.png")
                    image_size = cv2.imread(str(frame_path)).shape
                    height, width = image_size[:2]
                    websocket.send_json({
                        "type": "frame",
                        "frame_id": f"reference-{asset_id}",
                        "captured_at_ns": time_ns(),
                        "width": width,
                        "height": height,
                        "encoding": "png",
                        "data_base64": base64.b64encode(frame_path.read_bytes()).decode(),
                        "source_window_title": "FNAF 1 reference corpus",
                        "source_process_id": 1234,
                    })
                    assert websocket.receive_json()["type"] == "frame_ack"
                    annotations = websocket.receive_json()
                    assert annotations["type"] == "vision_annotations"
                    assert annotations["frame_id"] == f"reference-{asset_id}"
                    assert any(
                        box["kind"] == kind
                        and box["state"] == state
                        and box["label"] == label
                        and box["bbox"] is not None
                        for box in annotations["boxes"]
                    ), (
                        f"No matching annotation returned for asset {asset_id}: "
                        f"{annotations['boxes']}"
                    )
    finally:
        shutil.rmtree(artifact_dir, ignore_errors=True)


def test_bridge_vision_last_frame_wins_when_analysis_is_slow(monkeypatch):
    artifact_dir = Path("data") / "test-bridge-vision-last-frame-artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("BRIDGE_ARTIFACTS_DIR", str(artifact_dir))
    first_started = threading.Event()
    release_first = threading.Event()
    analyzed_frames: list[str] = []

    def slow_analyze(
        self,
        *,
        frame_id,
        captured_at_ns,
        width,
        height,
        frame_bytes,
        game_pack,
    ):
        del self, width, height, frame_bytes, game_pack
        analyzed_frames.append(frame_id)
        if frame_id == "frame-1":
            first_started.set()
            assert release_first.wait(timeout=2)
        return VisionState(
            frame_id=frame_id,
            captured_at_ns=captured_at_ns,
            frame_width=320,
            frame_height=200,
            confidence=0.0,
            detector_id="test.slow",
            detector_status="ready",
            processing_ms=1.0,
        )

    monkeypatch.setattr(GamePackVisionHost, "observe", slow_analyze)

    def send_frame(websocket, frame_id):
        websocket.send_json({
            "type": "frame",
            "frame_id": frame_id,
            "captured_at_ns": time_ns(),
            "width": 320,
            "height": 200,
            "encoding": "png",
            "data_base64": base64.b64encode(b"png-test").decode(),
            "source_window_title": "Test Game",
            "source_process_id": 1234,
        })
        assert websocket.receive_json()["type"] == "frame_ack"

    try:
        with TestClient(create_app()) as client:
            with client.websocket_connect(
                "/ws/host-bridge",
                headers={"X-Bridge-Token": "dev-only-change-me"},
            ) as websocket:
                websocket.send_json({
                    "type": "hello",
                    "protocol_version": "beta-4",
                    "client_id": "test-last-frame-bridge",
                    "capabilities": ["screen_capture", "vision_overlay"],
                    "dry_run": True,
                    "profile_id": "fnaf1",
                    "safe_capture": False,
                })
                assert websocket.receive_json()["type"] == "hello_ack"

                send_frame(websocket, "frame-1")
                assert first_started.wait(timeout=2)
                send_frame(websocket, "frame-2")
                send_frame(websocket, "frame-3")

                release_first.set()
                annotations = websocket.receive_json()

                assert annotations["type"] == "vision_annotations"
                assert annotations["frame_id"] == "frame-3"
                assert analyzed_frames == ["frame-1", "frame-3"]

                status = client.get("/api/bridge/status").json()
                assert status["last_vision_frame_id"] == "frame-3"
                assert status["vision_frames_dropped"] == 2
                assert client.get("/api/bridge/latest-vision").json()["frame_id"] == (
                    "frame-3"
                )
    finally:
        shutil.rmtree(artifact_dir, ignore_errors=True)


def test_bridge_accepts_audio_chunk_and_keeps_only_latest_artifact(monkeypatch):
    artifact_dir = Path("data") / "test-bridge-audio-artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("BRIDGE_ARTIFACTS_DIR", str(artifact_dir))

    try:
        with TestClient(create_app()) as client:
            with client.websocket_connect(
                "/ws/host-bridge",
                headers={"X-Bridge-Token": "dev-only-change-me"},
            ) as websocket:
                websocket.send_json({
                    "type": "hello",
                    "protocol_version": "beta-3",
                    "client_id": "test-audio-bridge",
                    "capabilities": ["audio_pcm", "latest_audio_chunk"],
                    "dry_run": True,
                    "profile_id": "fnaf1",
                    "safe_capture": False,
                    "run_id": "test-run",
                    "audio": {
                        "stream_id": "audio-test-stream",
                        "mode": "process_loopback",
                        "device_id": None,
                        "device_name": None,
                        "source_process_id": 4321,
                        "source_process_name": "FiveNightsatFreddys",
                        "sample_rate": 1000,
                        "channels": 1,
                        "sample_format": "pcm_f32le",
                        "chunk_duration_ms": 40,
                    },
                })
                assert websocket.receive_json()["type"] == "hello_ack"

                payload = bytes(range(160))
                started_at_ns = time_ns()

                websocket.send_json({
                    "type": "audio_chunk",
                    "stream_id": "audio-test-stream",
                    "chunk_id": "audio-chunk-1",
                    "sequence": 1,
                    "started_at_ns": started_at_ns,
                    "duration_ns": 40_000_000,
                    "sample_rate": 1000,
                    "channels": 1,
                    "sample_format": "pcm_f32le",
                    "frame_count": 40,
                    "data_base64": base64.b64encode(payload).decode(),
                    "source_process_id": 4321,
                    "source_process_name": "FiveNightsatFreddys",
                })
                assert websocket.receive_json() == {
                    "type": "audio_ack",
                    "stream_id": "audio-test-stream",
                    "chunk_id": "audio-chunk-1",
                    "sequence": 1,
                    "accepted": True,
                }

                status = client.get("/api/bridge/status").json()
                assert status["audio_status"] == "RECEIVING"
                assert status["audio_mode"] == "process_loopback"
                assert status["audio_chunks_received"] == 1
                assert status["audio_bytes_received"] == 160
                assert status["last_audio_sequence"] == 1
                assert status["audio_source_process_id"] == 4321
                assert status["audio_analysis_status"] == "WARMING"
                assert status["audio_buffer_chunks"] == 1
                assert status["audio_last_latency_ms"] is not None
                assert status["audio_latency_p95_ms"] is not None
                assert client.get("/api/bridge/latest-audio").content == payload
                assert client.get("/api/bridge/latest-audio/metadata").json()["sequence"] == 1
                analysis = client.get("/api/bridge/latest-audio-analysis").json()
                assert analysis["measurement"]["sequence"] == 1
                assert analysis["latency"]["deadline_met"] is True

                websocket.send_json({
                    "type": "audio_chunk",
                    "stream_id": "audio-test-stream",
                    "chunk_id": "audio-chunk-2",
                    "sequence": 1,
                    "started_at_ns": 1_700_000_000_040_000_000,
                    "duration_ns": 40_000_000,
                    "sample_rate": 1000,
                    "channels": 1,
                    "sample_format": "pcm_f32le",
                    "frame_count": 40,
                    "data_base64": base64.b64encode(payload).decode(),
                })
                assert websocket.receive_json()["code"] == "AUDIO_SEQUENCE_INVALID"

            with client.websocket_connect(
                "/ws/host-bridge",
                headers={"X-Bridge-Token": "dev-only-change-me"},
            ) as websocket:
                websocket.send_json({
                    "type": "hello",
                    "protocol_version": "beta-3",
                    "client_id": "test-audio-bridge-reconnect",
                    "capabilities": ["audio_pcm", "latest_audio_chunk"],
                    "dry_run": True,
                    "profile_id": "fnaf1",
                    "safe_capture": False,
                    "audio": {
                        "stream_id": "audio-test-stream-reconnected",
                        "mode": "process_loopback",
                        "source_process_id": 4321,
                        "source_process_name": "FiveNightsatFreddys",
                        "sample_rate": 1000,
                        "channels": 1,
                        "sample_format": "pcm_f32le",
                        "chunk_duration_ms": 40,
                    },
                })
                assert websocket.receive_json()["type"] == "hello_ack"

                websocket.send_json({
                    "type": "audio_chunk",
                    "stream_id": "audio-test-stream-reconnected",
                    "chunk_id": "audio-chunk-reconnected-1",
                    "sequence": 1,
                    "started_at_ns": 1_700_000_000_000_000_000,
                    "duration_ns": 40_000_000,
                    "sample_rate": 1000,
                    "channels": 1,
                    "sample_format": "pcm_f32le",
                    "frame_count": 40,
                    "data_base64": base64.b64encode(payload).decode(),
                    "source_process_id": 4321,
                    "source_process_name": "FiveNightsatFreddys",
                })
                assert websocket.receive_json()["type"] == "audio_ack"
    finally:
        shutil.rmtree(artifact_dir, ignore_errors=True)
