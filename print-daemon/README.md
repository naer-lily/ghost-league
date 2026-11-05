# print-daemon

Cross-platform, stdlib-only Python daemon for the user's PC. It polls
[`print-service`](../print-service/) over HTTP, claims one job, writes the raw
ESC/POS bytes to the printer over TCP (normally port 9100), and reports the
result. It has no local database, no ticket layout, and no public URL logic.

Architecture and deployment notes are in [`docs/PRINT_QUEUE.md`](../docs/PRINT_QUEUE.md).

## Configure

Copy `config.example.json` to `config.json` and replace the placeholders:

```json
{
  "server_url": "http://127.0.0.1:8096",
  "daemon_token": "replace-me",
  "printer_id": "home-80mm",
  "printer_host": "192.0.2.10",
  "printer_port": 9100,
  "poll_seconds": 2.0,
  "lease_seconds": 60,
  "heartbeat_seconds": 30,
  "http_timeout_seconds": 15,
  "printer_timeout_seconds": 10
}
```

`PRINT_DAEMON_TOKEN` and `PRINT_SERVICE_URL` override the file values, so the
token can stay in the environment or a protected service configuration instead
of the JSON file. The token is never logged and is not included in `repr(config)`.

Validation rejects missing strings, non-positive numbers, and printer ports
outside 1-65535. `server_url` must be an absolute `http` or `https` URL.
`config.json` is a local secret file: do not commit it.

## Run

```bash
cd print-daemon
PYTHONPATH=. python3 -m print_daemon --config config.json
PYTHONPATH=. python3 -m print_daemon --config config.json --once
PYTHONPATH=. python3 -m print_daemon --config config.json --print-test
python3 -m print_daemon --version
```

- Default mode: heartbeat, claim, print, report, repeat. No job means sleeping
  `poll_seconds`; HTTP/network errors use exponential backoff capped at 30
  seconds. `SIGINT`/`SIGTERM` stop the loop cleanly.
- `--once`: claim and process at most one job. Exit 0 for success or no job, 1
  for any failure. Useful for schedulers and smoke tests.
- `--print-test`: send an ASCII-only ESC/POS page (`ESC @`, text, `GS V 0` cut)
  directly to the printer, bypassing the service.
- `--log-level`: `DEBUG`, `INFO`, `WARNING`, or `ERROR`.

The daemon verifies `payload_sha256` before printing. A checksum mismatch is
reported as `failed` and nothing is sent to the printer. If reporting the final
result fails, the daemon logs it and leaves the lease alone; the service expires
the lease and retries according to its policy. There is no local queue.

## Windows

Use Task Scheduler or NSSM, with full paths and the working directory set to
this package so `python -m print_daemon` resolves correctly.

Task Scheduler (run at logon, hidden console window may require a wrapper):

```bat
schtasks /Create /TN "PrintDaemon" /SC ONLOGON /RL LIMITED ^
  /TR "C:\path\to\python.exe -m print_daemon --config C:\path\to\config.json"
```

NSSM:

```bat
nssm install PrintDaemon C:\path\to\python.exe -m print_daemon --config C:\path\to\config.json
nssm set PrintDaemon AppDirectory C:\path\to\ghost-league\print-daemon
nssm set PrintDaemon AppStdout C:\path\to\logs\print-daemon.out.log
nssm set PrintDaemon AppStderr C:\path\to\logs\print-daemon.err.log
nssm start PrintDaemon
```

Keep the token out of the command line where possible: set
`PRINT_DAEMON_TOKEN` in the service environment (NSSM) or a protected machine
scope variable. Restrict access to `config.json` and log files.

## Tests

```bash
cd print-daemon
PYTHONPATH=. python3 -m pytest -q
```

Tests use a local `socketserver` TCP endpoint and fake API/printer objects; no
real network or printer is required.
