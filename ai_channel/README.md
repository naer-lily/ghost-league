# ai_channel

An independent, **stdlib-only** Channel simulator that acts like an ordinary
Ghost League client. It provisions normal accounts through Ghost's provisioning
API, stores their tokens locally, and then calls only public `/v1/me/*` and
`/v1/shop*` endpoints.

Ghost sees normal accounts and ordinary player rows. It has no player identity
column and never learns which accounts are simulated. This package owns the
Channel's local account state and policy; Ghost never imports it.

## Setup

From the repository root:

```bash
cp ai_channel/config.example.json ai_channel/config.json
chmod 600 ai_channel/config.json
# edit ai_channel/config.json: set provisioning_token (never commit it)
```

`ai_channel/config.json` and `ai_channel/data/` are local secrets. The SQLite
state DB contains account tokens; it is created with mode `0600`. Protect both
files.

Environment overrides:

- `AI_CHANNEL_PROVISIONING_TOKEN` overrides `provisioning_token`.
- `AI_CHANNEL_BASE_URL` overrides `base_url`.

The setup requires Ghost to run with `GHOST_LEAGUE_PROVISIONING_TOKEN` (or
`create_app(provisioning_token=...)`); without that token the route stays
disabled. The live service is already configured and the route is enabled: the
token is in the service environment and `ai_channel/config.json` (both `0600`,
untracked). `ai_channel` can use the route, and its local token DB already holds
the existing ordinary accounts. Never print or commit the token.

`state_db` is resolved relative to the process working directory. The example
path (`ai_channel/data/ai_accounts.db`) is meant for one-shot commands run from
the repository root. The installed systemd unit runs from
`/opt/ghost-league/ai_channel`, so the config it loads should use
`data/ai_accounts.db` or an absolute path such as
`/opt/ghost-league/ai_channel/data/ai_accounts.db`.

## One-shot commands

From the repository root (`PYTHONPATH=ai_channel` finds the package without
installing it):

```bash
# Create sim-0001, sim-0002, ... and store their tokens. Prints IDs only.
PYTHONPATH=ai_channel python -m ai_channel provision \
  --config ai_channel/config.json --count 3 --prefix sim-

# Print user ids and display names. Never prints tokens.
PYTHONPATH=ai_channel python -m ai_channel list \
  --config ai_channel/config.json
PYTHONPATH=ai_channel python -m ai_channel list \
  --config ai_channel/config.json --prefix sim-

# One increment per account for the current hour; optionally buy one star.
PYTHONPATH=ai_channel python -m ai_channel tick \
  --config ai_channel/config.json --seconds 900 --buy-stars
PYTHONPATH=ai_channel python -m ai_channel tick \
  --config ai_channel/config.json --seconds 900 --prefix sim-

PYTHONPATH=ai_channel python -m ai_channel --version
```

Alternatively install the package (`pip install -e ai_channel`) and use
`python -m ai_channel ...` without `PYTHONPATH`.

`tick` uses the stable event id `ai_channel:{user_id}:{YYYYMMDDTHH}`, so
running it twice in the same hour is idempotent on Ghost. With `--buy-stars` it
reads `/v1/me/status` and `/v1/shop`, then buys the cheapest available
`star` / `seasonal_star` the wallet can afford. The purchase request id is
stable per account/item/day, so a repeated tick does not double-buy.

Use `--at 2026-11-05T12:00:00+08:00` to simulate a specific hour in tests or
backfills. `tick --prefix` limits the run to matching `user_id` values; without
`--prefix`, manual `tick` still processes every local account.

## Resident mode

`serve` runs the same `tick` in a loop, then waits for the interval:

```bash
cd /opt/ghost-league/ai_channel
python3 -m ai_channel serve \
  --config config.json --interval 3600 --prefix sim- --buy-stars
```

Arguments:

- `--interval` seconds between ticks, default `3600`, must be positive.
- `--seconds` increment size; defaults to `default_seconds` from the config.
- `--prefix` account filter, default `sim-`.
- `--cycles` number of ticks, default `0` (run forever). Bounded runs are for
  tests and manual dry runs; `--cycles 1` returns immediately without waiting.
- `--at` fixed ISO-8601 simulation time, mainly for tests.
- `--buy-stars` enables the optional cheapest-affordable-star purchase.

The loop runs one `tick`, logs its summary, then waits on a
`threading.Event`. `SIGINT` and `SIGTERM` set that event and the process exits
cleanly after logging a final summary. Tokens are never printed.

If the prefix matches no accounts, `serve` logs a zero-count summary and waits
for the next interval; it makes no HTTP request at all.

## Prefix isolation from Waka accounts

The local SQLite store can contain rows for more than one Channel. In particular
the existing Waka-backed rows use `ch-...` ids, while simulator accounts use
`sim-...`.

- `serve` defaults to `--prefix sim-`, so resident ticks never use Waka account
  tokens against `/v1/me/*`.
- `tick` keeps its manual default of all accounts for deliberate full runs.
  On a mixed DB, pass `--prefix sim-` (or another Channel prefix) to isolate
  the run.
- `list --prefix` only prints matching ids and names.
- Filtering happens in SQLite before token rows are loaded.

Do not point resident mode at `ch-` accounts unless that Channel is explicitly
supposed to tick those accounts.

## systemd unit

The unit source lives at
[`deploy/ai-channel.service`](deploy/ai-channel.service). It runs the package
from `/opt/ghost-league/ai_channel`:

```ini
[Service]
WorkingDirectory=/opt/ghost-league/ai_channel
ExecStart=/usr/bin/python3 -m ai_channel serve --config /opt/ghost-league/ai_channel/config.json --prefix sim-
Restart=on-failure
```

The unit contains no token. The token stays in `config.json` (mode `0600`, Git
ignored) and is read by the process.

`ai-channel.service` was installed and enabled on 2026-11-05 15:07 CST and is
active. It runs `serve --prefix sim-`. The configured local state DB currently
has zero `sim-` accounts, so each cycle logs `accounts=0` and makes no HTTP
request; the service is idle. It filters to `sim-` accounts, so it never loads
or uses Waka `ch-` tokens. There is no timer; systemd starts the long-running
service at boot.

## V1 scope

- The package only provisions new simulated accounts. Ghost has no
  `adopt_existing_player`; the player-identity schema migration preserves the
  existing ordinary players, and this package never writes Ghost's database.
- One XP increment per account per hour, default 900 seconds.
- Optional one cheapest affordable star purchase per day.
- No bets, tasks, rival selection, chests, or multi-account coordination.
- No direct database writes and no private Ghost endpoints.
- One-shot commands plus a resident loop; behavior policy is still deliberately
  small. Full behavior policy (bets, tasks, rival selection, chests) remains
  future work.

See [`../docs/CHANNEL_ACCOUNTS.md`](../docs/CHANNEL_ACCOUNTS.md) for the architecture,
player-identity migration and remaining cleanup.
