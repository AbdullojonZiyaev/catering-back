import os
import secrets
from typing import Literal

import psycopg
from psycopg.rows import dict_row
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, SecretStr

app = FastAPI(title="Catering Sensor API")
API_KEY = os.environ["DEVICE_API_KEY"]


def connect():
    return psycopg.connect(
        host="db",
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        connect_timeout=5,
        row_factory=dict_row,
    )


class Reading(BaseModel):
    key: SecretStr
    device: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    temperature: float = Field(allow_inf_nan=False)
    humidity: float = Field(ge=0, le=100, allow_inf_nan=False)
    source: Literal["sensor", "test"] = "sensor"


@app.exception_handler(RequestValidationError)
async def invalid_request(request, exc):
    # Do not return the submitted payload: it contains a secret.
    return JSONResponse(
        status_code=422,
        content={"detail": "Invalid payload: check device, temperature and humidity"},
    )


@app.get("/health")
def health():
    with connect() as conn:
        conn.execute("SELECT 1")
    return {"status": "ok", "database": "connected"}


@app.post("/api/readings", status_code=201)
def save_reading(reading: Reading):
    if not secrets.compare_digest(
        reading.key.get_secret_value().encode(), API_KEY.encode()
    ):
        raise HTTPException(status_code=401, detail="Invalid device key")

    with connect() as conn:
        row = conn.execute(
            """
            INSERT INTO readings (device, temperature, humidity, source)
            VALUES (%s, %s, %s, %s)
            RETURNING id, device, temperature, humidity, received_at, source
            """,
            (
                reading.device,
                reading.temperature,
                reading.humidity,
                reading.source,
            ),
        ).fetchone()
    return row
