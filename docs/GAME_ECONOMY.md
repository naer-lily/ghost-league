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
drawing session -> diamond rewards -> stars and other sinks -> visible collection
```

Competition, bets, and boosts are supporting mechanics around that chain. They are not the chain itself.

A player should be able to answer "why do I want more diamonds?" with a concrete use: a star for the wall, an ember to protect a streak, or a boost before a planned drawing session. "The number went up" alone is not a durable motivation.

## Gamification boundaries

- Gamification is instrumental. It exists to reduce the cost of starting and to make progress visible.
- Mixed mechanics are acceptable. A game economy does not need to be pure before it can be useful; it needs to be observable and adjustable.
- Start with a small loop, put it in front of the player, then tune it from behavior.
- Do not reject an unfinished system because it does not yet match an abstract ideal. Do not keep redesigning it instead of letting it run.

Signals that a mechanic is misaligned:

- The player checks bets more often than the drawing canvas.
- The main way to earn diamonds is unrelated to drawing effort.
- A boost mainly increases casino activity rather than drawing activity.
- The player wants diamonds only because the counter rose.

## Betting and leverage

- Betting and leverage are optional, bounded, and small relative to the core loop.
- No real money, no debt, and no loss-chasing.
- The intended function is a commitment device: stake something on your own planned drawing output, then show up to earn it back.
- A boost should make a planned drawing window more valuable. It should not turn the game into a self-contained money loop.

## Diamond sources and sinks

Current and intended sources should remain legible:

- real drawing output and XP-linked milestones;
- rival and group competition bonuses;
- bounded bet payouts;
- initial wallet balance for new players.

Current and intended sinks:

- stars and seasonal stars;
- embers for streak repair;
- warehouse capacity;
- time-boxed boosts;
- bets.

Competition and bets may add upside, but they should not become the main faucet. If the main faucet is disconnected from drawing, the economy stops expressing the player's effort.

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

- The primary diamond faucet should be tied more directly to real drawing output; the exact conversion and cadence are still open.
- Stars need a real display path, not only an inventory grid.
- The boost should be evaluated against drawing behavior, not only against bet volume.
- The economy should be tuned only after the small loop has real usage data.
