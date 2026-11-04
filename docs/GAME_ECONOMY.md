# Game Economy & Motivation

Status: product design note, 2026-11-03.

## One sentence

XP is the truthful record of real drawing time. Diamonds are the spendable layer. Stars are the visual payoff that leaves the screen and reaches the wall.

## Why the game exists

The game exists to make starting a drawing session easier and to make accumulated drawing time visible. It is not a generic league product, and it is not a second progression system that competes with drawing.

## Currency roles

### XP

- XP is derived from real activity time: `XP = floor(seconds / 6)`.
- XP is the only source of truth for tiers, weekly ranking, and promotion or demotion.
- No item, purchase, boost, bet, or cosmetic may change XP or the tier calculation.
- Keeping XP unboostable is a hard product boundary, not a temporary balance choice.

### Diamonds

- Diamonds are the foreground currency: the number a player watches, spends, saves, and risks.
- Diamonds are a spendable layer on top of XP, never a substitute for it.
- Diamonds may buy stars, seasonal stars, embers, warehouse capacity, and time-boxed boosts.
- Diamonds must never buy XP, tier progress, or a better position in the XP ranking.

### Stars

- Stars are the long-term reason to care about diamonds.
- A star should have a name, a rarity, and its own visual identity.
- Stars should be able to leave the inventory and become part of a wallpaper or room display, so collection has a real-world outlet.
- The collection is a record of effort and taste, not just a completion counter.

## Motivation model

The intended chain is:

```text
drawing session -> real seconds -> XP -> tier and weekly standing
drawing session -> XP -> lifetime XP milestones -> diamonds
drawing session -> XP and rank -> rival / group / bet settlement -> diamonds
diamonds -> stars and other sinks -> visible collection
```

Competition, bets, and boosts are supporting mechanics around that chain. They are not a separate source of diamonds. A bet is a claim on an XP or rank outcome, not a diamond-only slot.

A player should be able to answer "why do I want more diamonds?" with a concrete use: a star for the wall, an ember to protect a streak, or a boost before a planned drawing session. "The number went up" alone is not a durable motivation.

## Gamification boundaries

- Gamification is instrumental. It exists to reduce the cost of starting and to make progress visible.
- Mixed mechanics are acceptable. A game economy does not need to be pure before it can be useful; it needs to be observable and adjustable.
- Start with a small loop, put it in front of the player, then tune it from behavior.
- Do not reject an unfinished system because it does not yet match an abstract ideal. Do not keep redesigning it instead of letting it run.

Signals that a mechanic is misaligned:

- The player checks bets more often than the drawing canvas.
- A boost mainly increases casino activity rather than drawing activity.
- A payout can be won with no drawing output at all.
- The player wants diamonds only because the counter rose.

## Betting and leverage

- Betting and leverage are optional, bounded, and small relative to the core loop.
- No real money, no debt, and no loss-chasing.
- The intended function is a commitment device: stake something on your own planned drawing output, then show up to earn it back.
- Settlement is not a house game. Every rival bet is judged on the XP gap, every group bet on the group's XP ranking, and the opponent has no separate diamond income. The free stake is a participation subsidy, not a second faucet.
- A boost should make a planned drawing window more valuable. It should not turn the game into a self-contained money loop.

## Daily bet pricing and limits

Daily bets are the small, frequent loop. They use a fixed odds axis instead of a
free target range, so the player picks a price first and the server tells them
what XP gap that price requires:

```text
odds:      2.0, 3.0, 4.0, 5.0
p       = 1 / odds
z       = NormalDist().inv_cdf(1 - p)
margin  = max(1, ceil(muD + z * sigmaD))
expected_xp = round_to_step(mu_rival + margin, 10)
```

`muD` and `sigmaD` come from each player's own recent daily XP, not from a
shared band average. The same power band is only a prior: a player with at
least 3 completed check-in days in the last 28 days has their own mean and
sample variance shrunk toward that prior with 2 pseudo-days. A shorter history
falls back to the band prior unchanged, so the screen still has four prices on
day one. Both players are computed independently and may have different means
and spreads.

Daily paid stake is capped at 100 diamonds. Weekly and group bets keep the
existing 500-diamond cap. The cap is enforced in the bet transaction, not only
in the client, and the free 20 stake still stacks on top of the paid part. A
daily bet at the cap has 120 total principal (20 free + 100 paid); a weekly or
group bet at the cap has 520. Rejecting a daily stake above 100 uses the same
`invalid_stake` code as the other stake checks.

The odds shown on the daily screen are the stored odds. The client submits only
`target_margin`; the server finds that margin among the day's four options and
copies its `odds` onto the bet. No settlement-time price is recomputed.

## Diamond sources and sinks

Diamonds enter through the settlement of XP and rank outcomes, not through a separate casino:

- lifetime XP milestones, one diamond per complete 10 XP, boosted while a boost is active;
- rival and group settlement payouts, which are derived from real XP and rank and are never boosted;
- initial wallet balance for new players;
- free stake on each bet, as a bounded subsidy.

Current and intended sinks:

- stars and seasonal stars;
- embers for streak repair;
- warehouse capacity;
- time-boxed boosts;
- bets.

A diamond payout should always be traceable to an XP or rank result. If a payout can be won without any drawing output, that is a settlement bug or an open rule, not a second economy.

## Current shop tuning

The first tuning pass lowers the boost entry price and caps repeat buying so a
boost supports a planned drawing session instead of becoming a standing
multiplier:

| item | price | duration | purchase limit |
| --- | --- | --- | --- |
| `diamond_boost_25` | 20 diamonds | 25 minutes | 2 per Asia/Shanghai calendar day |
| `diamond_boost_60` | 40 diamonds | 60 minutes | 2 per Asia/Shanghai calendar day |
| `ember` | 800 diamonds | immediate | 1 purchase per 7 days |

Daily boost limits are per SKU, configurable through
`diamond_boost_25_daily_limit` and `diamond_boost_60_daily_limit`, and checked
inside the purchase transaction. A limit is a guardrail, not a replacement for
player choice: the shop shows `bought_today` and `remaining_today`, but the
server still rejects the next purchase with `daily_limit_reached`.

The ember cooldown is 7 days (`shop_items.ember.cooldown_seconds = 604800`).
Seeds, startup migration, and the idempotent
`scripts/apply_shop_economy_update.py` keep new and existing databases aligned
without overwriting later operator edits.

## Balance tuning

Parameters that affect the economy should be configurable, including prices, durations, multipliers, reward tiers, and availability. Balance changes should be data changes where possible, not code changes.

For each tuning pass, record:

- the loop being tuned;
- the intended player behavior;
- the parameter table with current value, proposed value, safe range, and purpose;
- expected-value checks for random or risk-based rewards;
- the telemetry that will show whether the change worked.

Useful telemetry:

- drawing minutes and XP per day;
- diamond inflow by source;
- diamond outflow by sink;
- star acquisition rate;
- boost purchase rate and active-window coverage;
- whether players open betting surfaces more often than drawing surfaces;
- distribution of diamond balances, to catch runaway accumulation.

## Open items

- Stars need a real display path, not only an inventory grid.
- The boost should be evaluated against drawing behavior, not only against bet volume.
- The economy should be tuned only after the small loop has real usage data.
