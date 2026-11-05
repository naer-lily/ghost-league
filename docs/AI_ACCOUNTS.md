# Account-backed AI channel (v1)

This document describes the first vertical slice of the symmetric-league
design: simulated players act through Ghost's public API using ordinary
accounts, exactly like a human client.

## Why account-backed AI

Ghost is a Duolingo-like league. Its game path should not need an "AI" branch
to produce XP, check-ins, stars, ranks or settlements. The cleanest way to test
that property is to let the simulator own a normal account and a normal token,
then use the same public endpoints as everyone else.

- Ghost stores only a normal account and normal game state.
- The simulator owns identity, token storage and behavior policy.
- Ghost does not import the simulator, does not know which accounts are
  simulated, and writes no AI marker into `players` or `channel_players`.
- The account's first authenticated `/v1/me/*` call follows the existing human
  path (`ensure_human_player`), so the game row is `kind='human'`.

This is intentionally different from the legacy Waka Channel ingest, which
still creates anonymous `kind='ai'` players through `channel_players`.

## Provisioning API

Ghost accepts an optional separate provisioning credential:

- `create_app(provisioning_token=...)`
- or `GHOST_LEAGUE_PROVISIONING_TOKEN`

It never falls back to the owner, bootstrap or Channel token. The route
compares with `hmac.compare_digest`.

If no provisioning token is configured, the route returns
`503 service_token_not_configured`. Missing or wrong credentials with a
configured token return `401`.

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
  owner. Live legacy AI ids are `ch-` plus a 64-hex source key, 67 characters,
  so they fit the provisioning limit.
- Duplicate ids return `409`; malformed or unknown fields return `422`.
- `display_name` is non-empty and at most 80 characters.
- The response is `201 {"account": {...}, "token": "..."}`.
- The plaintext token is returned exactly once; Ghost stores only its hash.
- Only an account is created. No `players` row, wallet or AI marker is written
  until the account makes its first authenticated `/v1/me/*` call.

The provisioning token is only for account creation. It cannot call
`/v1/me/*`, and an ordinary account token cannot call the provisioning route.

### Adopting one legacy AI player

`adopt_existing_player` promotes one existing Waka `players.id` that is still
`kind='ai'` into an ordinary account without changing its player id:

```http
POST /v1/provisioning/accounts
Authorization: Bearer <provisioning-token>
Content-Type: application/json

{
  "user_id": "ai-0123456789ab",
  "display_name": "Adopted player",
  "activity_label": "练习",
  "adopt_existing_player": true
}
```

Adoption rules:

- `adopt_existing_player` defaults to `false`; the default path creates a new
  account exactly as v1 does.
- `user_id` must be an existing `players.id` with `kind='ai'`. A missing player
  returns `404`; an already-human player returns `409` with
  `player already human`; the owner is still rejected with `422`.
- An account is created only if that id has none. A duplicate adoption or any
  other existing account returns `409`.
- The player row is promoted in one league transaction to `kind='human'`,
  `controller='human'`, `source_kind='local_increment'` and `is_active=1`.
- `source_key_hash`, `joined_week`, `last_seen_week`, `created_at`, XP/history
  and group membership are preserved. The player row is updated in place, never
  deleted or recreated, and `channel_players` rows are not touched.
- A normal diamond wallet is created in the same transaction.
- The returned token is an ordinary account token. The first `/v1/me/*` call
  follows the normal human path.

After adoption, Waka identity lookup is kind-independent: both
`get_player_by_source_key_hash()` and the weekly `upsert_ai_player()` match on
`source_key_hash` alone. A later Waka roster sync therefore refreshes the
adopted human's display name and `last_seen_week` and returns `created=False`
instead of inserting a duplicate AI row.

This is a **migration primitive for one player at a time**, not the full bulk
migration. No live database, production deployment or existing Waka row was
changed here; callers must choose ids and run adoption deliberately.

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

## Current scope and remaining migration

Implemented in v1:

- Separate provisioning token and `/v1/provisioning/accounts`.
- Ordinary accounts that enter the normal human game path.
- `ai_channel/` provisioning, local token state, XP ticks and optional star
  purchases through public API calls.

**Single-player adoption primitive implemented.** Full bulk migration of the
legacy AI path is still pending.

- An existing Waka `kind='ai'` player can be adopted into an ordinary account
  one at a time through `adopt_existing_player`, preserving its player id,
  history, group membership and channel mapping.
- Waka lookup and weekly roster sync are safe after adoption: they match the
  same `source_key_hash` regardless of `kind` and do not recreate an AI row.
- Existing unadopted Waka `kind='ai'` rows and their `channel_players` rows are
  otherwise unchanged.
- The legacy Channel ingest endpoints remain for Waka / external Channels and
  are still not the target path for new simulated AI.
- There is no automatic backfill, no bulk account migration and no removal of
  the remaining internal `kind='ai'` branches. The owner must select and adopt
  players explicitly.
- No live database or production deployment was changed by this slice.

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
