# Thermal printing: queue service + PC daemon

This document covers the two independent packages added for thermal printing:

- `print-service/`: server-side FastAPI + SQLite queue. It stores raw ESC/POS
  payloads, owns leases/retries/dedupe/reprints, and records printer heartbeats.
- `print-daemon/`: stdlib-only Python client on the user's PC. It polls the
  service, claims one job, prints raw bytes over TCP, and reports the result.

Ticket templates, QR generation, public URLs, and Ghost League game data are
out of scope. The producer renders bytes before calling the service.

## Architecture

```text
 Producer(s)                         print-service                    PC
 ───────────                         ─────────────                    ──
 ticket renderer  ── HTTPS ──▶  FastAPI routes + auth
 / bot / script                 SQLite queue (WAL)  ◀── HTTPS ──  print-daemon
                                     │                              │
                                     │ no printer I/O                │ raw TCP 9100
                                     │                              ▼
                                     └── job state ◀── result ──  thermal printer
```

- The printer is reachable from the PC, not necessarily from the server.
- The daemon makes only **outbound** HTTP requests to the service and outbound
  TCP connections to the printer. The service never opens a connection to the
  printer.
- The service is the only source of truth for job state. The daemon has no
  local queue and no business database.
- The payload is opaque bytes to both packages. The service computes and stores
  SHA-256 so the daemon can detect transport/encoding corruption before
  printing.

## Trust boundaries and auth

Two independent bearer tokens split the API surface:

| Token | Environment variable | Allowed routes |
| --- | --- | --- |
| Producer | `PRINT_PRODUCER_TOKEN` | create/get/reprint jobs |
| Daemon | `PRINT_DAEMON_TOKEN` | claim/result/heartbeat |

Rules:

- `Authorization: Bearer <token>` only. Query-string tokens are never accepted.
- Tokens are compared in constant time with `hmac.compare_digest`.
- Missing/wrong token: `401` (`missing_token`, `invalid_authorization`, or
  `invalid_token`).
- If a token is not configured on the server, authenticated routes fail closed
  with `503 service_token_not_configured`; `GET /healthz` remains public.
- Producer and daemon tokens are not interchangeable. A producer token cannot
  claim or report jobs, and a daemon token cannot create or read producer jobs.
- Secrets are read from environment variables or `create_app(...)` arguments.
  Do not put real tokens in JSON committed to Git, command lines visible to
  other users, logs, or examples. The daemon hides its token from `repr()` and
  never logs request headers.
- Terminate TLS in front of the service when producers or PCs are not on the
  same trusted host. Do not expose the service or printer port to the WAN.

The producer supplies `printer_id`; it is a routing label, not a credential.
Anyone with the producer token can enqueue to any printer id. Treat the
producer token as privileged and rotate it if leaked.

## Data model

One SQLite file (default `print-service/data/print.db`) in WAL mode with a busy
timeout. All timestamps are ISO-8601 UTC with a `Z` suffix.

`print_jobs`:

| Column | Meaning |
| --- | --- |
| `id` | UUID, returned to producers and daemons |
| `printer_id`, `kind`, `source_ref` | routing and producer metadata |
| `dedupe_key` | optional producer idempotency key, scoped by printer |
| `payload`, `payload_sha256` | raw ESC/POS bytes and their digest |
| `status` | `pending`, `claimed`, `done`, `failed`, `needs_attention` |
| `attempts`, `max_attempts` | claim count and retry limit (1-10) |
| `lease_id`, `lease_expires_at` | current daemon lease |
| `created_at`, `updated_at` | lifecycle timestamps |
| `claimed_at`, `printed_at` | last claim and successful print |
| `last_error` | last reported or lease-expiry error |
| `reprint_of` | original job id for a reprint copy |

A partial unique index enforces `(printer_id, dedupe_key)` where `dedupe_key IS
NOT NULL`. Dedupe is checked inside the same `BEGIN IMMEDIATE` transaction as
the insert.

`print_printers`:

| Column | Meaning |
| --- | --- |
| `printer_id` | primary key |
| `state` | `online`, `offline`, or `unknown` |
| `detail` | last daemon error/detail, if any |
| `last_seen_at`, `updated_at` | last heartbeat times |

## Status machine and leases

```text
pending ── claim ─────────────────────────────▶ claimed
claimed ── result done ───────────────────────▶ done
claimed ── result failed, attempts < max ─────▶ pending
claimed ── result failed, attempts >= max ────▶ failed
claimed ── result unknown ────────────────────▶ needs_attention
claimed ── lease expiry, attempts < max ──────▶ pending  (reaped on next claim)
claimed ── lease expiry, attempts >= max ─────▶ failed   (reaped on next claim)
```

- `attempts` increments when a job is claimed, not when it is created.
- `claim` first reaps expired leases for that printer inside the same write
  transaction, then selects the oldest `pending` job. A claim increments
  `attempts`, sets `claimed_at`, generates a new `lease_id`, and sets
  `lease_expires_at = now + lease_seconds` (default 60, allowed 10-300).
- Reaping an expired lease moves the job to `pending` while
  `attempts < max_attempts`, otherwise to `failed`. A failed reaper sets
  `last_error = lease_expired`.
- `done` sets `printed_at`, clears the lease, and clears `last_error`.
- `failed` stores `error` in `last_error`; it requeues to `pending` until
  `attempts >= max_attempts`, then becomes `failed`.
- `unknown` means the daemon cannot prove whether paper was emitted (for
  example, a timeout after sending bytes). The job becomes `needs_attention`
  and is never auto-retried, avoiding duplicate prints. An operator must
  reprint explicitly.
- A result with the wrong job id, wrong lease id, or a job that is no longer
  `claimed` returns `409 lease_conflict`. A late result after the lease was
  reaped is rejected for the same reason.
- `done`, `failed`, and `needs_attention` are terminal for that job. The only
  way to print again is a producer `reprint`, which creates a new job.

### Dedupe and reprint

- Same `(printer_id, dedupe_key)` returns the existing job unchanged with
  `"duplicate": true`, including if that job has already finished or failed.
  Producers that want a fresh attempt after a failure should use reprint or a
  new dedupe key.
- `reprint` copies printer id, kind, source ref, payload, payload digest, and
  max attempts into a new `pending` job. It gets a new UUID, starts at zero
  attempts, sets `reprint_of`, and deliberately has **no** dedupe key so it
  cannot collide with the original.

## API summary

All bodies are JSON and models forbid unknown fields (`extra="forbid"`).
Malformed bodies return `422`; error responses use stable `detail` strings.

| Method | Path | Auth | Success | Notes |
| --- | --- | --- | --- | --- |
| GET | `/healthz` | none | `200 {status, time}` | liveness only |
| POST | `/v1/print/jobs` | producer | `200 {job, duplicate}` | enqueue |
| GET | `/v1/print/jobs/{job_id}` | producer | `200 {job}` | metadata only, never payload |
| POST | `/v1/print/jobs/{job_id}/reprint` | producer | `200 {job}` | new pending copy |
| POST | `/v1/print/claim` | daemon | `200 {job}` or `204` | no job is an empty 204 |
| POST | `/v1/print/jobs/{job_id}/result` | daemon | `200 {job}` | `done`/`failed`/`unknown` |
| POST | `/v1/print/heartbeat` | daemon | `200 {status, time}` | upsert |

Create job body:

```json
{
  "printer_id": "home-80mm",
  "kind": "ticket",
  "payload_b64": "<standard base64 ESC/POS bytes>",
  "source_ref": "order-123",
  "dedupe_key": "order-123",
  "max_attempts": 3
}
```

- `payload_b64` is standard base64 with strict validation. Decoded payload must
  be at least 1 byte and at most 2 MiB.
- Producer-only fields are optional; `max_attempts` defaults to 3.
- Validation errors: `422 payload_b64_invalid`, `422 payload_empty`,
  `422 payload_too_large`.
- Unknown jobs: `404 job_not_found`.

Claim job body and response:

```json
{"printer_id": "home-80mm", "lease_seconds": 60}
```

```json
{
  "job": {
    "id": "…",
    "printer_id": "home-80mm",
    "kind": "ticket",
    "source_ref": "order-123",
    "payload_b64": "…",
    "payload_sha256": "…",
    "attempts": 1,
    "max_attempts": 3,
    "lease_id": "…",
    "lease_expires_at": "2026-01-01T12:01:00.000000Z"
  }
}
```

Result body:

```json
{"lease_id": "…", "status": "done"}
```

`status` is exactly `done`, `failed`, or `unknown`; `error` is optional and
stored in `last_error`.

Heartbeat body:

```json
{"printer_id": "home-80mm", "state": "online", "detail": "tcp probe ok"}
```

`state` is exactly `online`, `offline`, or `unknown`. Each heartbeat updates
`last_seen_at`, whether the printer itself was reachable or not.

## Daemon behavior

- Claims one job at a time and sends bytes with
  `socket.create_connection`, `sendall`, `shutdown(SHUT_WR)`, then close.
- Decodes and verifies `payload_sha256` before opening the printer connection.
  A mismatch reports `failed` with `payload_sha256_mismatch` and prints nothing.
- Reports `done` only after the bytes were accepted by the printer socket. If
  that report fails, the daemon logs it and leaves the lease; the service
  handles expiry/retry.
- Printer connection/send failures report `failed` with the error.
- Heartbeats probe the printer over TCP and report `online` or `offline` with a
  detail string. Heartbeat failures are logged and do not stop the daemon.
- The claim loop sleeps `poll_seconds` when there is no job and uses exponential
  backoff capped at 30 seconds for HTTP/network errors.
- `SIGINT`/`SIGTERM` set a stop event for a graceful exit. Only stdlib modules
  are used, so the same code runs on Windows, Linux, and macOS.
- `--once` exits 0 for "printed" or "no job" and 1 for any failure.
- `--print-test` sends an ASCII-only page starting with `ESC @` and ending with
  the `GS V 0` full cut directly to the printer, bypassing the service.

## Deployment notes

### Server

Run uvicorn bound to loopback behind the existing reverse proxy/TLS, with both
tokens in a root-owned `0600` environment file:

```ini
# /etc/print-service.env  (chmod 0600)
PRINT_PRODUCER_TOKEN=<producer-token>
PRINT_DAEMON_TOKEN=<daemon-token>
PRINT_SERVICE_DB=/srv/print-service/print.db
```

```ini
# /etc/systemd/system/print-service.service
[Unit]
Description=Ghost League print queue
After=network.target

[Service]
User=print-service
WorkingDirectory=/opt/ghost-league/print-service
EnvironmentFile=/etc/print-service.env
ExecStart=/opt/ghost-league/print-service/.venv/bin/uvicorn \
  print_service.app:create_app --factory --host 127.0.0.1 --port 8096
Restart=on-failure
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now print-service
curl -fsS http://127.0.0.1:8096/healthz
```

Back up the SQLite database together with its `-wal`/`-shm` files, or use
`sqlite3 print.db ".backup ..."` while the service is stopped. The directory is
gitignored; only `data/.gitkeep` is tracked. Health checks need no token, but
producer and daemon clients still need the appropriate bearer token.

### PC daemon

- Run `python -m print_daemon --config <path>` from a protected working
  directory. On Windows use Task Scheduler (at logon/startup) or NSSM; set the
  working directory to `print-daemon/` and use absolute paths. See
  `print-daemon/README.md` for commands.
- Provide `PRINT_DAEMON_TOKEN` via the service environment rather than the
  command line where possible.
- Assign the printer a static DHCP reservation (or a documented fixed address)
  so `printer_host` does not drift. Allow outbound TCP to port 9100 only on the
  local network.
- Some printers need a raw-print server; this daemon expects a plain TCP socket
  that accepts raw bytes. Host-based print queues/spoolers are not used.

### Network exposure

- Bind the service to loopback and expose it only through the existing TLS
  reverse proxy. Do not port-forward it to the WAN.
- Do not expose the printer's TCP 9100 port outside the LAN. The PC initiates
  every connection in both directions.
- Keep firewall rules narrow: the PC may reach the service URL and the printer
  IP; the server does not need to reach the printer at all.

## Failure handling cheat sheet

| Situation | Result |
| --- | --- |
| No job pending | claim returns `204`; daemon sleeps and retries |
| Duplicate producer submission | existing job, `duplicate: true`, no new row |
| Daemon dies after claim | lease expires; next claim requeues or fails it |
| Printer unreachable | daemon reports `failed`; server retries up to max |
| Printer result ambiguous | daemon reports `unknown`; job waits in `needs_attention` |
| Wrong/stale lease result | `409 lease_conflict`; job state is unchanged |
| Missing payload digest match | daemon reports `failed`, prints nothing |
| Server/token misconfigured | authenticated route returns `503`, never anonymous access |

## Explicit non-goals

- No ticket templates, layout language, QR generation, or image rendering.
- No public URL or customer-facing ticket lookup.
- No Ghost League database coupling: the service never reads or writes game
  state, and the daemon never calls Ghost League APIs.
- No local daemon queue, spooler, or offline replay.
- No printing from the server, no inbound connection to the PC.
- No deployment, systemd install, or token provisioning is performed by this
  repository task.

## Tests

```bash
cd /opt/ghost-league
ruff check print-service print-daemon
python3 -m compileall -q print-service print-daemon

cd print-service && PYTHONPATH=. python3 -m pytest -q
cd ../print-daemon && PYTHONPATH=. python3 -m pytest -q
```

The service tests use `TestClient`, a temporary SQLite file, and an injected
clock for lease expiry. The daemon tests use a local `socketserver` and fake API
clients, so neither suite needs a real network or printer.
