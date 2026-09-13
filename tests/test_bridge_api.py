import base64
import shutil
from pathlib import Path

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
