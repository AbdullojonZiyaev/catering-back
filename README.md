# Catering Sensor API

FastAPI + PostgreSQL service that stores readings from the sensor units and serves them to the dashboard
(`../dashboard`, page **Sensor readings**).

## Run

```bash
cp .env.example .env      # then set your own passwords and key
docker compose up --build
```

The API listens on `http://127.0.0.1:8000` (interactive docs at `/docs`). The `readings` table is created
automatically on start-up.

## Endpoints

| Method | Path | What it does |
|---|---|---|
| GET | `/health` | `200` when the database answers, `503` when it doesn't |
| POST | `/api/readings` | Store one reading. Device key in the body (`"key"`) or the `X-Device-Key` header |
| GET | `/api/readings` | Newest readings first. Query: `device`, `since` (ISO time), `limit` (1–5000, default 200), `include_test` |
| GET | `/api/devices` | Each device with its latest reading, last-seen time and reading count |

```bash
curl -X POST http://127.0.0.1:8000/api/readings \
  -H 'Content-Type: application/json' -H "X-Device-Key: $DEVICE_API_KEY" \
  -d '{"device": "C05", "temperature": 3.4, "humidity": 61.2}'
```

`temperature` must be between −60 and 125 °C, `humidity` between 0 and 100 %, `source` is `sensor`
(default) or `test`. Test readings are hidden from the GET endpoints unless `include_test=true`.

## Notes

- `.env` holds secrets and is ignored by git. Only `.env.example` is committed.
- The read endpoints have no login yet; the API is only reachable from the same machine (`127.0.0.1`).
  Add authentication before exposing it on a network.
- The API also joins the Docker network `catering` (created by this compose project). The dashboard's nginx
  joins it too and forwards its `/backend/*` GET requests to `http://api:8000`, so start this project first.
- `CORS_ORIGINS` lists the browser origins allowed to call the API directly (default: the dashboard dev
  server). Not needed when the dashboard's dev server forwards `/backend` to the API.
- The stored format is one temperature and humidity per device, timed when the server receives it. The
  dashboard's **Sensor readings → Best case** view shows the full message format it was designed for.
