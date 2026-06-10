"""Serveur HTTP local pour l'ESP32 : GET /dashboard renvoie le JSON consolidé.

Les sources sont rafraîchies par une tâche de fond ; la requête de l'ESP32 ne
déclenche aucun appel réseau et répond immédiatement (réveil le plus court possible).

Lancement : uvicorn --factory pi_aggregator.app:create_app --host 0.0.0.0 --port 8080
"""

import asyncio
import logging
from contextlib import asynccontextmanager, suppress

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from .aggregator import Aggregator
from .config import Config, load_config

log = logging.getLogger(__name__)

REFRESH_TICK_SECONDS = 60


async def _refresh_loop(aggregator: Aggregator) -> None:
    while True:
        await aggregator.refresh_stale()
        await asyncio.sleep(REFRESH_TICK_SECONDS)


def create_app(cfg: Config | None = None) -> FastAPI:
    cfg = cfg or load_config()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with httpx.AsyncClient(timeout=10) as client:
            aggregator = Aggregator(cfg, client)
            app.state.aggregator = aggregator
            task = asyncio.create_task(_refresh_loop(aggregator))
            try:
                yield
            finally:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    app = FastAPI(title="pi-aggregator", lifespan=lifespan)

    @app.get("/dashboard")
    def dashboard() -> JSONResponse:
        return JSONResponse(app.state.aggregator.build())

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok", "sources": app.state.aggregator.health()}

    return app


if __name__ == "__main__":
    import uvicorn

    config = load_config()
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(create_app(config), host=config.host, port=config.port)
