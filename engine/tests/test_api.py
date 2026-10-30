from fastapi.testclient import TestClient

from test_engine import make_engine
from tradebot.api import build_app


def test_api_auth_and_controls(store, settings):
    eng, _ = make_engine(store, settings)
    c = TestClient(build_app(eng, "secret"))
    assert c.get("/health").json()["ok"]
    assert c.get("/status").status_code == 401
    assert c.get("/status", headers={"Authorization": "Bearer nope"}).status_code == 401
    h = {"Authorization": "Bearer secret"}
    s = c.get("/status", headers=h).json()
    assert s["mode"] == "paper" and s["state"] == "IDLE"
    assert c.post("/start", json={"capital": -5}, headers=h).status_code == 422
    assert c.post("/start", json={"capital": 2000}, headers=h).json()["ok"]
    assert c.post("/start", json={"capital": 2000}, headers=h).status_code == 409
    assert c.post("/kill", headers=h).json()["ok"]
    assert c.get("/status", headers=h).json()["state"] == "KILLED"
    assert isinstance(c.get("/events", headers=h).json(), list)
    assert "picks" in c.get("/watchlist", headers=h).json()
