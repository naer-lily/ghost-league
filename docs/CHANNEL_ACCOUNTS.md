# Channel account simulation (v1)

This document describes the account-backed Channel simulator and the Ghost
player model it relies on. Simulated clients act through Ghost's public API
using ordinary accounts, exactly like any other client.

## Why account-backed Channel clients

Ghost has no player identity class. Its game path does not need a human / ai
branch to produce XP, check-ins, stars, ranks or settlements. The cleanest way
to test that property is to let the simulator own a normal account and a normal
token, then use the same public endpoints as everyone else.

- Ghost stores only ordinary players and ordinary game state.
- The simulator owns identity, token storage and behavior policy.
- Ghost does not import the simulator, does not know which accounts are
  simulated, and writes no AI marker into `players` or `channel_players`.
- The account's first authenticated `/v1/me/*` call follows
  `ensure_human_player`, which writes an ordinary player row.
- Waka is a Channel. Its leaderboard rows become ordinary contestants with
  `source_kind = SOURCE_WAKA` (`wakatime_public_leaderboard`) and an optional
  `source_key_hash`; those fields are provenance, not identity. There is no
  `SOURCE_AI`, no `players.kind` / `players.controller`, and no
  `channel_players.kind`.
- Waka's production XP transport is account-backed and was cut over live on
  2026-11-05 ~15:41 CST: `waka_channel` supplies the cache and hourly projection,
  and `ai_channel tick --source waka`—triggered hourly at `:01` by
  `ai-channel-waka.timer` as a oneshot `ai-channel-waka.service`—uses the
  existing 1074 ordinary `ch-` account tokens to call `POST /v1/me/increments`.
  `ai-channel-fetch.timer` refreshes the cache weekly on Monday at 00:02. Ghost
  has no Waka scheduler job and imports no Channel/provider client.
- `group_members.is_human` remains only for the existing UI contract. Every
  ordinary member is written with value `1`; it is not a new identity class.

Ghost's Channel roster boundary has no identity flag: every roster player is
created or refreshed as an ordinary player, and an old `kind` field is rejected
as an unknown field. Channel-local state may still distinguish clients for its
own purposes, but none of that reaches Ghost.

## Provisioning API

Ghost accepts an optional separate provisioning credential:

- `create_app(provisioning_token=...)`
- or `GHOST_LEAGUE_PROVISIONING_TOKEN`

It never falls back to the owner, bootstrap or Channel token. The route
compares with `hmac.compare_digest`.

A missing provisioning token leaves the route disabled. The live service is
configured: the route is enabled and authenticated. The token lives only in the
service environment and `ai_channel/config.json` (both `0600`, untracked); it is
never printed or committed. Missing or wrong credentials return `401`.

```http
POST /v1/provisioning/accounts
Authorization: Bearer <provisioning-token>
Content-Type: application/json

{
  "user_id": "sim-0001",
  "display_name": "Sim One",
  "activity_label": "练习"
}
```

Rules:

- `user_id` must match Ghost's `SAFE_USER_ID` pattern (1-80 characters, leading
  letter or digit, then letters/digits/dot/underscore/dash) and must not be the
  owner.
- Duplicate ids return `409`; malformed or unknown fields return `422`.
- `display_name` is non-empty and at most 80 characters.
- The response is `201 {"account": {...}, "token": "..."}`.
- The plaintext token is returned exactly once; Ghost stores only its hash.
- Only an account is created. No `players` row, wallet or identity marker is
  written until the account makes its first authenticated `/v1/me/*` call.
- There is no `adopt_existing_player` field or endpoint. Accounts are always
  created fresh; existing players are never converted by provisioning.

The provisioning token is only for account creation. It cannot call
`/v1/me/*`, and an ordinary account token cannot call the provisioning route.

The legacy Waka roster sync looks players up by `source_key_hash` only. A row that
returns after a missing week refreshes the same player id and never creates a
duplicate identity beside it. Ghost no longer schedules that sync; Waka XP uses
the account path described below.

## Player identity live migration

Schema 14 removes the retired identity columns from the game database. The
migration was applied live on 2026-11-05 14:53 CST. The pre-migration backup is
`/data/backups/ghost-league/pre-player-kind-20261105T145317`, and the automatic
backup beside the database is
`data/league/league.db.backup-player-identity-20261105T145319553868`. It
preserved 1076 players, 1074 channel mappings and 1954 group members at
migration time, `PRAGMA integrity_check` returned `ok`, and the API/Web
restarted healthy. A full Waka roster sync after migration succeeded with 972
rows, 0 created and 972 existing; the Waka leaderboard was intact.

The migration itself is idempotent and runs from `GameStore.initialize()` on an
old database:

1. Detect any remaining `players.kind` / `players.controller` /
   `channel_players.kind` column.
2. Back up the database with the SQLite backup API to
   `league.db.backup-player-identity-<timestamp>` beside the live file.
3. Rebuild `players` and `channel_players` in one transaction, copying only
   shared columns.
4. Preserve player ids, `source_kind` / `source_key_hash`, channel profile
   snapshots and mappings, XP, weekly scores, group memberships and wallets.
   No player row is deleted.
5. Set `group_members.is_human = 1` for all existing memberships.

The live database is already migrated, so no rerun is needed. For a fresh
instance or a drill, apply it with the API and Web stopped:

```bash
cd /opt/ghost-league
PYTHONPATH=. python3 scripts/migrate_player_identity.py --db data/league/league.db
```

The script prints `integrity_check`, `players`, `channel_players`,
`group_members` counts and the backup path. Re-running it on an already
migrated database is a no-op and creates no second backup. Roll back by
stopping the service, restoring the pre-migration backup directory above or the
most recent `league.db.backup-player-identity-*` (plus any needed `-wal` /
`-shm` state), then returning to the schema 13 code. Never overwrite a live
database while the service is running.

## ai_channel package

`ai_channel/` is a separate account-backed Channel client. Its generic mode is
stdlib-only (`urllib.request`) and creates accounts through provisioning. Its
Waka mode adds the `waka_channel` source/projection library, which borrows only
Ghost's pure schedule math; neither mode imports Ghost's game/store/channels
code or writes Ghost's database.

```text
ai_channel CLI
  ├─ generic mode
  │    ├─ provisioning token -> POST /v1/provisioning/accounts
  │    ├─ local SQLite (0600) -> user ids + ordinary account tokens
  │    └─ account token      -> /v1/me/increments, /v1/me/status, /v1/shop*
  └─ Waka mode (--source waka)
       ├─ data/cache/cn-978.json + waka_channel.projection
       ├─ player_ref -> ch- + sha256(namespace + "waka\\0" + player_ref)
       ├─ local SQLite (0600) -> existing ordinary account token
       └─ account token      -> POST /v1/me/increments only
```

State:

- `accounts(user_id, display_name, token, created_at)`
- `runs(id, user_id, event_id, seconds, created_at)`

Waka mode does not add a table: it reuses the existing weekly cursor in
`waka_channel.state` (default `data/cache/waka-channel-state.json`). A missing
token is reported and skipped, never provisioned. The generic `sim-` mode is
unchanged.

`provision` prints only user ids and a count. `list` prints ids and display
names. Neither command prints tokens; the local SQLite DB is created with mode
`0600`.

Config is a local secret file (`ai_channel/config.json`, copied from
`config.example.json`). `AI_CHANNEL_PROVISIONING_TOKEN` and
`AI_CHANNEL_BASE_URL` override the file. The base URL must be an absolute
HTTP(S) URL, and timeout/default seconds must be positive. Waka mode also
accepts `--cache` and `--state`; run it with the repository root on
`PYTHONPATH` (for example `PYTHONPATH=/opt/ghost-league:/opt/ghost-league/ai_channel`).

### Lifecycle

From the repository root (the example `state_db` path is relative to it):

```bash
cp ai_channel/config.example.json ai_channel/config.json
chmod 600 ai_channel/config.json
# edit ai_channel/config.json and set the provisioning token

PYTHONPATH=ai_channel python -m ai_channel provision \
  --config ai_channel/config.json --count 3 --prefix sim-
PYTHONPATH=ai_channel python -m ai_channel list \
  --config ai_channel/config.json
PYTHONPATH=ai_channel python -m ai_channel tick \
  --config ai_channel/config.json --seconds 900 --buy-stars
PYTHONPATH=ai_channel python -m ai_channel --version
```

Installing the package (`pip install -e ai_channel`) lets you drop the
`PYTHONPATH` prefix. Use an absolute `state_db` path if you run from elsewhere.

Generic v1 policy:

- One XP increment per account per hour, default 900 seconds.
- `event_id = ai_channel:{user_id}:{YYYYMMDDTHH}`; a repeated tick in the same
  hour is idempotent on Ghost.
- Optional star purchase only when `diamonds` from `/v1/me/status` covers the
  item price. Choose the lowest-price available `star` / `seasonal_star`.
- `request_id = ai_star:{user_id}:{item_id}:{YYYYMMDD}` prevents a repeated
  tick from double-buying.
- No bets, tasks, rival selection, chests or multi-account coordination.
- No Ghost DB access and no private endpoints.
- `serve` runs the tick loop residently; the behavior policy itself is still deliberately
  small.

### Waka mode

Waka mode keeps the existing cache, normalization and hourly projection, and
only changes the transport. Each projected increment is sent with its existing
`event_id`, `seconds` and `occurred_at` to the ordinary account that already
exists for that `player_ref`:

```bash
cd /opt/ghost-league
export PYTHONPATH=/opt/ghost-league:/opt/ghost-league/ai_channel

# Optional cache refresh; only data/cache is written.
python3 scripts/source_fetch.py --out data/cache/cn-978.json --country CN

# One tick: completed hours only, existing Waka cursor.
python3 -m ai_channel tick --config ai_channel/config.json --source waka \
  --cache data/cache/cn-978.json \
  --state data/cache/waka-channel-state.json

# Resident form with the same source.
python3 -m ai_channel serve --config ai_channel/config.json --source waka \
  --cache data/cache/cn-978.json \
  --state data/cache/waka-channel-state.json
```

- `player_ref` maps to `ch-` + sha256(`ghost-channel-player-v1\0waka\0` +
  `player_ref`), the same id Ghost already uses for the Channel mapping.
- The token is read from `ai_accounts.db`; a missing token is reported and
  skipped, and no account or player is created.
- Every positive event is one `POST /v1/me/increments`; there is no Channel
  ingest call.
- The cursor advances only for players whose batch succeeded. A repeated tick
  sends no duplicate events, and Ghost also deduplicates by `event_id`.
- The legacy `waka_channel.cli tick` and `ai_channel --source waka` share the
  cursor; do not run both at the same time.
- `--source waka` ignores the generic `--prefix`, `--seconds` and `--buy-stars`
  options. The default `--source accounts` mode and its `sim-` prefix behavior
  are unchanged.

### Deployment status

The Waka cutover was applied live on 2026-11-05 ~15:41 CST. The pre-cutover
backup is `/data/backups/ghost-league/pre-waka-cutover-20261105T154101`
(`league.db`, `ai_accounts.db`, Waka state and the then-current
`ai-channel.service`).

Production transport is a systemd timer, not a resident process:

- `ai-channel-waka.timer` runs hourly at `:01` and activates the oneshot
  `ai-channel-waka.service`, which executes `ai_channel tick --source waka`
  with cache `/opt/ghost-league/data/cache/cn-978.json` and state
  `/opt/ghost-league/data/cache/waka-channel-state.json`.
- `ai-channel-fetch.timer` refreshes `data/cache/cn-978.json` weekly on Monday
  at 00:02 through the oneshot `ai-channel-fetch.service`; it writes only the
  cache.
- `ai-channel-waka.service` is a oneshot unit activated by the timer, not a
  resident process.
- `ai-channel.service` remains the resident generic `serve --prefix sim-` loop.
  Its local state has zero `sim-` accounts, so it stays idle (`accounts=0`, no
  HTTP request); it is not the Waka tick and never loads or uses `ch-` tokens.

Ghost's in-process scheduler registers only generic game jobs and no longer has
`waka-tick`, `waka-roster` or `source-fetch`; historical `job_runs` rows remain
for audit. Waka's existing `channel_events` rows also remain. New Waka XP writes
`activity_events` through `/v1/me/increments`, and the daily XP resolver still
takes the larger of the two, so frontend XP and historical channel events are
preserved.

## Current scope and remaining cleanup

Implemented:

- Separate provisioning token and `/v1/provisioning/accounts`.
- Ordinary accounts that enter the normal player path; no Ghost identity field.
- `ai_channel/` provisioning, local token state, XP ticks and optional star
  purchases through public API calls.
- `ai_channel --source waka`: existing cache + `waka_channel.projection` sent
  per account through `POST /v1/me/increments`, with the existing Waka cursor,
  missing-token reporting and no Channel ingest.
- Waka cutover applied live on 2026-11-05 ~15:41 CST: hourly
  `ai-channel-waka.timer` oneshot for XP transport, weekly
  `ai-channel-fetch.timer` for the cache, and `ai-channel.service` left as the
  idle generic `sim-` loop.
- Idempotent player-identity schema migration with automatic backup, applied
  live on 2026-11-05 14:53 CST.
- Waka as a Channel whose leaderboard players are ordinary contestants; only
  `source_kind` / `source_key_hash` record provenance.
- Ghost's in-process scheduler no longer registers `waka-tick`, `waka-roster`
  or `source-fetch`, and imports no Channel/provider client. Historical
  `job_runs` rows are retained.

Remaining cleanup:

- The legacy Channel ingest endpoints remain for other/external Channels and
  historical data; Waka XP no longer uses them.
- Legacy source/projection code remains for historical compatibility, but it
  must not write a player identity column or branch on one.
- Live provisioning is enabled: the token is configured in the service
  environment and `ai_channel/config.json` (both `0600`, untracked), so
  `ai_channel` can use the route. The repository-root local token DB retains the
  1074 Waka `ch-` ordinary accounts. Keep the token out of logs and Git.
- `ai_channel/` has tokens, one-shot commands and a resident `serve` loop.
  Production Waka transport is now the `ai-channel-waka.timer` oneshot plus the
  weekly `ai-channel-fetch.timer`; `ai-channel.service` is only the idle generic
  `sim-` loop. The cutover was applied live on 2026-11-05 ~15:41 CST; do not
  describe `ai-channel.service` as carrying Waka.
- Waka's existing `channel_events` rows remain untouched. New Waka XP writes
  `activity_events`; the daily XP resolver still takes the larger of the two,
  so current frontend data is preserved and the frontend is unchanged.
- A full behavior policy (bets, tasks, rival selection, chests) remains future
  work and is not implemented.

The long-term design remains in the `ghost-league` skill reference
`references/agent-symmetry.md`.

## Security

- The provisioning token is highly privileged: it can create accounts. Protect
  it like the owner token, keep it in an environment file with restrictive
  permissions, and rotate it if exposed.
- `ai_channel`'s SQLite DB contains plaintext account tokens because the
  simulator must act later. Restrict the file (`0600`), keep `ai_channel/data/`
  out of Git, and treat the whole machine as a secret boundary.
- `ai_channel/config.json` is also a secret and is Git-ignored.
- Neither tokens nor bearer headers should be logged. CLI output contains only
  ids, names, event ids and outcomes.
