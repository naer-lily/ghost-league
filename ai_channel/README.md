# ai_channel

An independent, account-backed Channel client for Ghost League. It acts like an
ordinary client: it owns local account tokens and calls only Ghost's public
`/v1/me/*` and `/v1/shop*` endpoints. Ghost sees normal accounts and ordinary
player rows; it has no player identity column and never learns which accounts are
simulated.

There are two tick sources:

- **`accounts` (default)** — the existing generic simulator. It provisions
  normal accounts through Ghost's provisioning API, stores their tokens locally,
  and sends one increment per account per hour.
- **`waka`** — the Waka projection transport. It reads the existing
  `waka_channel` cache/projection library and sends each projected hour with the
  already stored ordinary account token, keeping the existing Waka `event_id`,
  `seconds` and `occurred_at`.

Waka remains a source/projection library used by this Channel:

```text
Waka cache / projection  ->  ai_channel (Channel)
ai_channel uses the existing ordinary account tokens
  -> POST /v1/me/increments (same public API as any player)
Ghost: fixed rules, no provider imports, no Waka scheduler jobs
```

`waka_channel` borrows Ghost's pure schedule math but this package never imports
Ghost's game/store/channels code and never writes Ghost's database.

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

Waka mode also imports the sibling `waka_channel` package, so run it with the
repository root importable:

```bash
export PYTHONPATH=/opt/ghost-league:/opt/ghost-league/ai_channel
```

## Waka source mode

```bash
cd /opt/ghost-league

# Optional: refresh the public leaderboard cache. Only data/cache is written.
python3 scripts/source_fetch.py --out data/cache/cn-978.json --country CN

# Send completed Waka hours through the ordinary account tokens.
python3 -m ai_channel tick --config ai_channel/config.json --source waka \
  --cache data/cache/cn-978.json \
  --state data/cache/waka-channel-state.json

# Resident form.
python3 -m ai_channel serve --config ai_channel/config.json --source waka \
  --cache data/cache/cn-978.json \
  --state data/cache/waka-channel-state.json
```

Production does not run this manually or as a resident `serve`. The Waka cutover
was applied live on 2026-11-05 ~15:41 CST (pre-cutover backup:
`/data/backups/ghost-league/pre-waka-cutover-20261105T154101`).
`ai-channel-waka.timer` runs the tick hourly at `:01` as the oneshot
`ai-channel-waka.service`, and `ai-channel-fetch.timer` refreshes the cache
weekly on Monday at 00:02. The resident `ai-channel.service` is a separate idle
generic `sim-` loop and does not carry Waka.

How it works:

- The cache is read only; `waka_channel.projection` produces the same hourly
  `event_id` / seconds / `occurred_at` as the existing Waka Channel.
- Each `player_ref` maps to the stable Ghost user id `ch-` + sha256(
  `ghost-channel-player-v1\0waka\0` + `player_ref`). That is the same id Ghost
  already uses for the Channel mapping.
- The ordinary account token is read from `ai_accounts.db`. A missing token is
  reported and skipped; no account or player is created.
- Each positive event is one `POST /v1/me/increments`. There is no Channel
  ingest call and no Ghost database write.
- The cursor is the existing Waka weekly hour cursor. A repeated tick sends no
  duplicate events; Ghost also deduplicates by `event_id`.
- The legacy `waka_channel.cli tick` and `ai_channel --source waka` share that
  cursor file; do not run both at the same time.
- `--source waka` ignores `--prefix`, `--seconds` and `--buy-stars`. The generic
  `--source accounts` mode and its `sim-` prefix behavior are unchanged.

Historical `channel_events` rows remain in Ghost. New Waka XP writes
`activity_events` through the public API, and Ghost's daily XP resolver still
takes the larger of the two, so current frontend data is preserved.

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

Generic `tick` uses the stable event id `ai_channel:{user_id}:{YYYYMMDDTHH}`, so
running it twice in the same hour is idempotent on Ghost. With `--buy-stars` it
reads `/v1/me/status` and `/v1/shop`, then buys the cheapest available
`star` / `seasonal_star` the wallet can afford. The purchase request id is
stable per account/item/day, so a repeated tick does not double-buy.

Use `--at 2026-11-05T12:00:00+08:00` to simulate a specific hour in tests or
backfills. Generic `tick --prefix` limits the run to matching `user_id` values;
without `--prefix`, manual generic `tick` still processes every local account.

## Resident mode

`serve` runs the same `tick` in a loop, then waits for the interval:

```bash
cd /opt/ghost-league/ai_channel
python3 -m ai_channel serve \
  --config config.json --interval 3600 --prefix sim- --buy-stars
```

Arguments:

- `--source` `accounts` (default) or `waka`.
- `--interval` seconds between ticks, default `3600`, must be positive.
- `--seconds` increment size; defaults to `default_seconds` from the config.
  Ignored by `--source waka`.
- `--prefix` account filter for generic mode, default `sim-`.
- `--cache` / `--state` Waka cache and cursor paths, default
  `data/cache/cn-978.json` and `data/cache/waka-channel-state.json`.
- `--week-start` optional ISO Monday for a Waka catch-up.
- `--cycles` number of ticks, default `0` (run forever). Bounded runs are for
  tests and manual dry runs; `--cycles 1` returns immediately without waiting.
- `--at` fixed ISO-8601 simulation time, mainly for tests.
- `--buy-stars` enables the optional cheapest-affordable-star purchase. Ignored
  by `--source waka`.

The loop runs one `tick`, logs its summary, then waits on a
`threading.Event`. `SIGINT` and `SIGTERM` set that event and the process exits
cleanly after logging a final summary. Tokens are never printed.

If the generic prefix matches no accounts, `serve` logs a zero-count summary and
waits for the next interval; it makes no HTTP request at all.

## Prefix isolation from Waka accounts

The local SQLite store can contain rows for more than one Channel. In particular
the existing Waka-backed rows use `ch-...` ids, while simulator accounts use
`sim-...`.

- Generic `serve` defaults to `--prefix sim-`, so resident generic ticks never
  use Waka account tokens.
- Generic `tick` keeps its manual default of all accounts for deliberate full
  runs. On a mixed DB, pass `--prefix sim-` (or another Channel prefix) to
  isolate the run.
- Waka mode is the deliberate exception: `--source waka` looks up the exact
  `ch-` account for each projected `player_ref` and never touches `sim-`
  accounts.
- `list --prefix` only prints matching ids and names.
- Filtering happens in SQLite before token rows are loaded.

## systemd unit

The repository template at
[`deploy/ai-channel.service`](deploy/ai-channel.service) is the generic resident
loop. It runs the package from `/opt/ghost-league/ai_channel`:

```ini
[Service]
WorkingDirectory=/opt/ghost-league/ai_channel
ExecStart=/usr/bin/python3 -m ai_channel serve --config /opt/ghost-league/ai_channel/config.json --prefix sim-
Restart=on-failure
```

The unit contains no token. The token stays in `config.json` (mode `0600`, Git
ignored) and is read by the process.

The live host runs the generic service plus two timer-driven oneshot units after
the Waka cutover, which was applied on 2026-11-05 ~15:41 CST (pre-cutover backup:
`/data/backups/ghost-league/pre-waka-cutover-20261105T154101`):

- `ai-channel.service` — the resident generic `Type=simple` loop above. It is
  active but idle: the local state has zero `sim-` accounts, so it logs
  `accounts=0` and makes no HTTP request. It is not the Waka tick and never loads
  Waka `ch-` tokens.
- `ai-channel-waka.service` — a `Type=oneshot` unit activated by
  `ai-channel-waka.timer` hourly at `:01` (`Persistent=true`). It runs
  `ai_channel tick --source waka` with cache
  `/opt/ghost-league/data/cache/cn-978.json` and state
  `/opt/ghost-league/data/cache/waka-channel-state.json`, with `PYTHONPATH`
  including `/opt/ghost-league`, and exits after the tick. It is not a resident
  process.
- `ai-channel-fetch.service` — a `Type=oneshot` unit activated by
  `ai-channel-fetch.timer` weekly on Monday at 00:02 (`Persistent=true`). It runs
  `scripts/source_fetch.py` and writes only `data/cache/cn-978.json`.

Ghost's scheduler no longer registers `waka-tick`, `waka-roster` or
`source-fetch` and imports no Channel/provider client; historical `job_runs`
rows remain. Existing Waka `channel_events` rows remain too, and new XP writes
`activity_events`, so the daily XP resolver preserves frontend values.

## V1 scope

- Generic mode only provisions new simulated accounts. Ghost has no
  `adopt_existing_player`; the player-identity schema migration preserves the
  existing ordinary players, and this package never writes Ghost's database.
- Waka mode only reuses the existing ordinary `ch-` accounts; it never
  provisions missing players.
- Generic: one XP increment per account per hour, default 900 seconds.
- Waka: one increment per projected positive Waka hour, same event ids and
  seconds as the existing projection.
- Optional one cheapest affordable star purchase per day (generic mode only).
- No bets, tasks, rival selection, chests, or multi-account coordination.
- No direct database writes and no private Ghost endpoints.
- One-shot commands plus a resident loop; behavior policy is still deliberately
  small. Full behavior policy (bets, tasks, rival selection, chests) remains
  future work.

See [`../docs/CHANNEL_ACCOUNTS.md`](../docs/CHANNEL_ACCOUNTS.md) for the architecture,
the Waka transport, player-identity migration and remaining cleanup.
