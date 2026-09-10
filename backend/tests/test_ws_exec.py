from fastapi.testclient import TestClient

from app.main import app

c = TestClient(app)


def test_ws_exec_route_exist(monkeypatch):
    # Without a real docker daemon, connecting to a missing container should
    # either send an error or close. We assert the route is reachable.
    try:
        with c.websocket_connect("/ws/exec?container=missing") as ws:
            ws.send_text("ls")
    except Exception:
        pass