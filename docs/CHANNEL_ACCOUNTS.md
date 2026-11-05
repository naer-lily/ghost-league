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

Waka roster sync looks players up by `source_key_hash` only. A row that returns
after a missing week refreshes the same player id and never creates a duplicate
identity beside it.

## Player identity live migration

Schema 14 removes the retired identity columns from the game database. The
migration is idempotent and runs from `GameStore.initialize()`:

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

Apply it with the API and Web stopped:

```bash
cd /opt/ghost-league
PYTHONPATH=. python3 scripts/migrate_player_identity.py --db data/league/league.db
```

The script prints `integrity_check`, `players`, `channel_players`,
`group_members` counts and the backup path. Re-running it on an already
migrated database is a no-op and creates no second backup. Roll back by
stopping the service, restoring the most recent
`league.db.backup-player-identity-*` (plus any needed `-wal` / `-shm` state),
then returning to the schema 13 code. Never overwrite a live database while the
service is running.

## ai_channel package

`ai_channel/` is a separate, stdlib-only simulator. It uses `urllib.request`,
never imports Ghost internals and never writes Ghost's database.

```text
ai_channel CLI
  ├─ provisioning token -> POST /v1/provisioning/accounts
  ├─ local SQLite (0600) -> user ids + ordinary account tokens
  └─ account token      -> /v1/me/increments, /v1/me/status, /v1/shop*
```

State:

- `accounts(user_id, display_name, token, created_at)`
- `runs(id, user_id, event_id, seconds, created_at)`

`provision` prints only user ids and a count. `list` prints ids and display
names. Neither command prints tokens; the local SQLite DB is created with mode
`0600`.

Config is a local secret file (`ai_channel/config.json`, copied from
`config.example.json`). `AI_CHANNEL_PROVISIONING_TOKEN` and
`AI_CHANNEL_BASE_URL` override the file. The base URL must be an absolute
HTTP(S) URL, and timeout/default seconds must be positive.

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

V1 policy:

- One XP increment per account per hour, default 900 seconds.
- `event_id = ai_channel:{user_id}:{YYYYMMDDTHH}`; a repeated tick in the same
  hour is idempotent on Ghost.
- Optional star purchase only when `diamonds` from `/v1/me/status` covers the
  item price. Choose the lowest-price available `star` / `seasonal_star`.
- `request_id = ai_star:{user_id}:{item_id}:{YYYYMMDD}` prevents a repeated
  tick from double-buying.
- No bets, tasks, rival selection or multi-account coordination.
- No Ghost DB access and no private endpoints.
- `serve` runs the tick loop residently; the behavior policy itself is still deliberately
  small.

## Current scope and remaining cleanup

Implemented:

- Separate provisioning token and `/v1/provisioning/accounts`.
- Ordinary accounts that enter the normal player path; no Ghost identity field.
- `ai_channel/` provisioning, local token state, XP ticks and optional star
  purchases through public API calls.
- Idempotent player-identity schema migration with automatic backup.
- Waka as a Channel whose leaderboard players are ordinary contestants; only
  `source_kind` / `source_key_hash` record provenance.

Remaining cleanup:

- The legacy Channel ingest endpoints remain for Waka / external Channels.
- Legacy source/projection code remains for historical compatibility, but it
  must not write a player identity column or branch on one.
- Live provisioning is enabled: the token is configured in the service
  environment and `ai_channel/config.json` (both `0600`, untracked), so
  `ai_channel` can use the route and its token DB already holds the 1074
  ordinary accounts. Keep the token out of logs and Git.
- `ai_channel/` has tokens, one-shot commands and a resident `serve` loop;
  a full behavior policy remains future work.

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
