# ai_channel

An independent, **stdlib-only** simulator that acts like an ordinary Ghost
League client. It provisions normal accounts through Ghost's provisioning API,
stores their tokens locally, and then calls only public `/v1/me/*` and
`/v1/shop*` endpoints.

Ghost sees normal accounts and normal game rows (`kind='human'`). This package
owns the simulated identity and policy; Ghost never imports it and never learns
which accounts are simulated.

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
the 1074 adopted accounts. Never print or commit the token.

The example `state_db` path (`ai_channel/data/ai_accounts.db`) is relative to
the repository root. If you run from another directory, adjust it or pass an
absolute path.

## Commands

From the repository root (`PYTHONPATH=ai_channel` finds the package without
installing it):

```bash
# Create sim-0001, sim-0002, ... and store their tokens. Prints IDs only.
PYTHONPATH=ai_channel python -m ai_channel provision \
  --config ai_channel/config.json --count 3 --prefix sim-

# Print user ids and display names. Never prints tokens.
PYTHONPATH=ai_channel python -m ai_channel list --config ai_channel/config.json

# One increment per account for the current hour; optionally buy one star.
PYTHONPATH=ai_channel python -m ai_channel tick \
  --config ai_channel/config.json --seconds 900 --buy-stars

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
backfills.

## V1 scope

- The package itself only provisions new simulated accounts. The 2026-11-05
  live migration of legacy Waka `kind='ai'` rows was completed separately
  through the provisioning endpoint's `adopt_existing_player`; those rows are
  now ordinary `kind='human'` accounts.
- One XP increment per account per hour, default 900 seconds.
- Optional one cheapest affordable star purchase per day.
- No bets, tasks, rival selection, or multi-account coordination.
- No direct database writes and no private Ghost endpoints.
- CLI-driven only: there is no resident scheduler or full behavior policy yet.

See [`../docs/AI_ACCOUNTS.md`](../docs/AI_ACCOUNTS.md) for the architecture,
migration results and remaining cleanup.
