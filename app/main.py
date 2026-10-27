"""Run three benchmark configurations using MODE=A, B, or C."""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.middleware.mutation import SchemaMutationMiddleware

MODE = os.getenv("MODE", "A").upper()
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
redis_client = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_client
    app.state.redis = None
    if MODE == "C":
        try:
            from redis.asyncio import Redis
        except ImportError as exc:
            raise RuntimeError("Install redis package to run MODE=C") from exc
        redis_client = Redis.from_url(REDIS_URL, decode_responses=True)
        await redis_client.ping()
        app.state.redis = redis_client
    yield
    if redis_client is not None:
        await redis_client.aclose()
        redis_client = None
        app.state.redis = None


app = FastAPI(title=f"Mutation Defense Research Prototype ({MODE})", lifespan=lifespan)


class Checkout(BaseModel):
    item_id: int = Field(gt=0)
    qty: int = Field(gt=0, le=100)


@app.middleware("http")
async def no_op_for_benchmark(request, call_next):
    # Intentionally empty: keeps the application path simple and consistent.
    return await call_next(request)


@app.post("/api/v1/checkout")
async def checkout(data: Checkout):
    # No payment or database side effects in this benchmark endpoint.
    return {"ok": True, "item_id": data.item_id, "qty": data.qty}


if MODE in ("B", "C"):
    app.add_middleware(
        SchemaMutationMiddleware,
        mode=MODE,
        redis_client=redis_client,
    )
