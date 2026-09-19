import base64
import shutil
from pathlib import Path
from time import time_ns

from fastapi.testclient import TestClient

from agentic_gaming.main import create_app


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
