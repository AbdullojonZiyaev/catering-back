import asyncio
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Literal

import psycopg
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from psycopg.rows import dict_row
from pydantic import BaseModel, Field, SecretStr

API_KEY = os.environ["DEVICE_API_KEY"]

# Created on start-up so a fresh database works without manual steps.
SCHEMA = """
CREATE TABLE IF NOT EXISTS readings (
    id          BIGSERIAL PRIMARY KEY,
    device      TEXT             NOT NULL,
    temperature DOUBLE PRECISION NOT NULL,
    humidity    DOUBLE PRECISION NOT NULL,
    source      TEXT             NOT NULL DEFAULT 'sensor'
                CHECK (source IN ('sensor', 'test')),
    received_at TIMESTAMPTZ      NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS readings_device_time ON readings (device, received_at DESC);
CREATE INDEX IF NOT EXISTS readings_time ON readings (received_at DESC);
"""


def connect():
    return psycopg.connect(
        host=os.environ.get("POSTGRES_HOST", "db"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        connect_timeout=5,
        row_factory=dict_row,
    )


@asynccontextmanager
async def lifespan(app):
    # The database may still be starting; try for about 30 s before giving up.
    for attempt in range(15):
        try:
            with connect() as conn:
                conn.execute(SCHEMA)
            break
        except psycopg.OperationalError:
            if attempt == 14:
                raise
            await asyncio.sleep(2)
    yield


app = FastAPI(title="Catering Sensor API", lifespan=lifespan)

# Browsers may call the read endpoints only from these origins (comma-separated).
origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET"], allow_headers=[])


class Reading(BaseModel):
    # The key may come in the body (current firmware) or in the X-Device-Key header.
    key: SecretStr | None = None
    device: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    # Sensor ranges: SHT-type sensors read -40..125 °C
    temperature: float = Field(ge=-60, le=125, allow_inf_nan=False)
    humidity: float = Field(ge=0, le=100, allow_inf_nan=False)
    source: Literal["sensor", "test"] = "sensor"


@app.exception_handler(RequestValidationError)
async def invalid_request(request, exc):
    # Do not return the submitted payload: it contains a secret.
    fields = sorted({str(e["loc"][-1]) for e in exc.errors() if e.get("loc")} - {"key"})
    return JSONResponse(
        status_code=422,
        content={"detail": "Invalid request", "fields": fields},
    )


@app.get("/health")
def health():
    try:
        with connect() as conn:
            conn.execute("SELECT 1")
    except psycopg.Error:
        return JSONResponse(status_code=503, content={"status": "error", "database": "unreachable"})
    return {"status": "ok", "database": "connected"}


@app.post("/api/readings", status_code=201)
def save_reading(reading: Reading, x_device_key: str | None = Header(default=None)):
    given = x_device_key or (reading.key.get_secret_value() if reading.key else "")
    if not secrets.compare_digest(given.encode(), API_KEY.encode()):
        raise HTTPException(status_code=401, detail="Invalid device key")

    with connect() as conn:
        row = conn.execute(
            """
            INSERT INTO readings (device, temperature, humidity, source)
            VALUES (%s, %s, %s, %s)
            RETURNING id, device, temperature, humidity, received_at, source
            """,
            (reading.device, reading.temperature, reading.humidity, reading.source),
        ).fetchone()
    return row


@app.get("/api/readings")
def list_readings(
    device: str | None = Query(default=None, max_length=100, pattern=r"^[A-Za-z0-9_-]+$"),
    since: datetime | None = None,
    limit: int = Query(default=200, ge=1, le=5000),
    include_test: bool = False,
):
    """Newest readings first. Filter by device and/or time."""
    where, args = [], []
    if device:
        where.append("device = %s")
        args.append(device)
    if since:
        where.append("received_at > %s")
        args.append(since)
    if not include_test:
        where.append("source = 'sensor'")
    sql = "SELECT id, device, temperature, humidity, source, received_at FROM readings"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY received_at DESC, id DESC LIMIT %s"
    with connect() as conn:
        return conn.execute(sql, (*args, limit)).fetchall()


@app.get("/api/devices")
def list_devices(include_test: bool = False):
    """Every device that has sent data, with its latest reading."""
    filt = "" if include_test else "WHERE source = 'sensor'"
    with connect() as conn:
        return conn.execute(
            f"""
            SELECT DISTINCT ON (device)
                   device, temperature, humidity, received_at AS last_seen,
                   COUNT(*) OVER (PARTITION BY device) AS readings
            FROM readings {filt}
            ORDER BY device, received_at DESC, id DESC
            """
        ).fetchall()
