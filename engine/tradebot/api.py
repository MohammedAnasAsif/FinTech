"""HTTP API the Android/Windows app talks to. Every call except /health needs the
pairing token shown when the engine starts (stored in data/api_token.txt)."""
from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from .engine import Engine


def load_or_create_token(data_dir: Path) -> str:
    p = data_dir / "api_token.txt"
    if p.exists():
        return p.read_text(encoding="utf-8").strip()
    tok = secrets.token_urlsafe(24)
    p.write_text(tok, encoding="utf-8")
    return tok


class StartBody(BaseModel):
    capital: float = Field(gt=0, le=10_000_000)


def build_app(engine: Engine, token: str) -> FastAPI:
    app = FastAPI(title="TradeBot engine", version="0.1.0")

    def auth(authorization: str = Header(default="")) -> None:
        if not secrets.compare_digest(authorization, f"Bearer {token}"):
            raise HTTPException(status_code=401, detail="bad or missing token")

    def result(r: dict) -> dict:
        if not r.get("ok"):
            raise HTTPException(status_code=409, detail=r.get("error", "refused"))
        return r

    @app.get("/health")
    def health():
        return {"ok": True, "name": "tradebot", "version": app.version}

    @app.get("/status", dependencies=[Depends(auth)])
    def status():
        return engine.status()

    @app.post("/start", dependencies=[Depends(auth)])
    def start(body: StartBody):
        return result(engine.start_day(body.capital))

    @app.post("/pause", dependencies=[Depends(auth)])
    def pause():
        return result(engine.pause())

    @app.post("/resume", dependencies=[Depends(auth)])
    def resume():
        return result(engine.resume())

    @app.post("/stop", dependencies=[Depends(auth)])
    def stop():
        return result(engine.stop_day())

    @app.post("/kill", dependencies=[Depends(auth)])
    def kill():
        return result(engine.kill())

    @app.post("/research", dependencies=[Depends(auth)])
    def research_now():
        return result(engine.run_research_now())

    @app.get("/watchlist", dependencies=[Depends(auth)])
    def watchlist():
        return engine.watchlist()

    @app.get("/trades", dependencies=[Depends(auth)])
    def trades(day: str | None = None, limit: int = 200):
        return engine.store.trades(day=day, limit=min(limit, 1000))

    @app.get("/reviews", dependencies=[Depends(auth)])
    def reviews(limit: int = 30):
        return engine.store.reviews(limit=min(limit, 365))

    @app.get("/events", dependencies=[Depends(auth)])
    def events(since: int = 0, limit: int = 200):
        return engine.store.events(since=since, limit=min(limit, 1000))

    @app.get("/days", dependencies=[Depends(auth)])
    def days():
        return engine.store.days()

    return app
