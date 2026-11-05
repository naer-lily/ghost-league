# print-service

Server-side thermal-printer queue: FastAPI + SQLite with leases, retries, dedupe,
and reprints. Producers submit an already-rendered ESC/POS payload; this service
never renders tickets and never talks to a printer.

The PC-side counterpart is [`print-daemon/`](../print-daemon/). Architecture and
deployment notes are in [`docs/PRINT_QUEUE.md`](../docs/PRINT_QUEUE.md).

## Install and run

Requires Python 3.11+.

```bash
cd print-service
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'

export PRINT_PRODUCER_TOKEN='<producer-token>'
export PRINT_DAEMON_TOKEN='<daemon-token>'
export PRINT_SERVICE_DB='data/print.db'

uvicorn print_service.app:create_app --factory --host 127.0.0.1 --port 8096
```

`create_app(*, db_path=None, producer_token=None, daemon_token=None, now_fn=None)`
is also importable directly. Explicit arguments win over environment variables:

| Setting | Environment variable | Default |
| --- | --- | --- |
| SQLite file | `PRINT_SERVICE_DB` | `print-service/data/print.db` |
| Producer token | `PRINT_PRODUCER_TOKEN` | none, authenticated routes fail closed |
| Daemon token | `PRINT_DAEMON_TOKEN` | none, authenticated routes fail closed |

`GET /healthz` is public. If a token is not configured, routes that need it
return `503 service_token_not_configured`; they never fall back to anonymous
access. Tokens are accepted only in `Authorization: Bearer <token>`, never in a
query string.

## API

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| GET | `/healthz` | none | health and server time |
| POST | `/v1/print/jobs` | producer | enqueue raw bytes (`payload_b64`) |
| GET | `/v1/print/jobs/{id}` | producer | job metadata, no payload |
| POST | `/v1/print/jobs/{id}/reprint` | producer | copy payload into a new job |
| POST | `/v1/print/claim` | daemon | claim the oldest pending job |
| POST | `/v1/print/jobs/{id}/result` | daemon | report `done`/`failed`/`unknown` |
| POST | `/v1/print/heartbeat` | daemon | upsert printer reachability |

Example enqueue:

```bash
PAYLOAD_B64="$(printf '\\033@hello\\n\\035V\\000' | base64 -w0)"
curl -sS http://127.0.0.1:8096/v1/print/jobs \
  -H "Authorization: Bearer $PRINT_PRODUCER_TOKEN" \
  -H 'Content-Type: application/json' \
  -d "{\"printer_id\":\"home-80mm\",\"kind\":\"test\",\"payload_b64\":\"$PAYLOAD_B64\",\"dedupe_key\":\"ticket-42\"}"
```

The decoded payload must be 1 byte to 2 MiB. Malformed base64, empty payloads,
oversized payloads, unknown fields, and out-of-range values return 422 with a
stable error string. Jobs without a `dedupe_key` are always new; a duplicate
`(printer_id, dedupe_key)` returns the existing job with `"duplicate": true`.

## Tests

```bash
cd print-service
PYTHONPATH=. python3 -m pytest -q
```

Tests use a temporary SQLite file and an injected clock for lease expiry; no
network or real printer is required.
