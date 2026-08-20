---
id: ADR-0008
title: The state view shows everything until it cannot
status: accepted
date: 2026-08-19
authors: Sean Cozart <seancozart@outlook.com>
refs: docs/adr/0005-state-is-a-union-merged-log-projected-into-capped-views.md
---

# ADR-0008: The state view shows everything until it cannot

## Context

ADR-0005 gave every state event a `weight` and capped the rendered view at twenty
entries per section, ranked heaviest first, on the argument that "a cap that drops the
least important is a summary; a cap that drops the oldest is data loss with extra steps."

That argument is sound. Its premise turned out not to hold.

Building `state migrate` is what exposed it. A hand-authored `STATE.md` carries no
importance signal anywhere, so every migrated event had to default to weight 3, which
meant a migrated repo's cap would drop entries arbitrarily. Writing that down as a
limitation forced the question of where a *non*-migrated weight comes from, and the
answer is: a human types it, at the moment of `state add`, with no feedback if they get
it wrong and no trigger telling them to revisit it.

The numbers made it worse rather than better. This repo, the most heavily exercised
cozyplan project in existence, has fifteen projected entries against a cap of twenty.
The cap has never truncated anything. So the ranking machinery has never ranked, fed by
a field that had no natural moment where anyone set it, guarding against a length no
project has yet reached.

Weight was also load-bearing in exactly one place that mattered: it was the field
`migrate` had to apologise for. Removing it made the migration report shorter, which is
the tell that it was carrying complexity rather than value.

## Decision

We remove `weight`, `--cap`, and importance ranking. `state render` writes every
projected entry; `state show` prints every entry and drops `--all`.

**Ordering becomes commit position alone** — `_ord`, which every writer already shares
and which ADR-0005 established as the total order. Existing events keep their `weight`
field on disk; the projection ignores it. No migration is required and no log is
rewritten.

**A cap comes back when a real `STATE.md` is too long to read, and not before.** At that
point the project will have the thing it lacks today: evidence about which entries
readers actually skip. Ranking designed against that evidence will beat ranking designed
against a guess.

The general rule this instance follows: **a feature earns its place when you can name
what breaks if you delete it.** Delete the render guard and a user loses their
`STATE.md`. Delete `weight` and nothing breaks until a project has hundreds of events,
which none does.

## Consequences

Easier: one fewer concept in the state model, one fewer flag on `state add`, one fewer
thing `migrate` cannot carry, and one fewer field whose staleness is invisible. The
`state` command lost three flags in a release where it also gained a subparser split.

Harder: a project that does reach hundreds of events will render a long `STATE.md`
before anyone notices, because nothing now bounds it. That is a visible, self-announcing
failure — the file gets long and someone complains — rather than the silent one we had,
where a cap quietly dropped entries by a rank nobody maintained. We prefer the loud
failure, and it is the failure that will tell us how to build the cap properly.

## Alternatives Considered

- Keep `weight` and set it automatically from the event kind — rejected: it dresses a
  constant up as a judgment. If the rank is derivable, it is not a separate field.
- Keep the cap and rank by recency — rejected: ADR-0005 is right that dropping the
  oldest is data loss, and with no cap firing there is nothing to fix.
- Keep both and document that weights need maintenance — rejected: this project already
  learned that a documented failure mode ships as a failure. `hooks.json` described its
  own silent-disable behaviour in its own description, and it happened anyway.

## Status History

- 2026-08-19 — proposed by Sean Cozart
- 2026-08-19 — accepted by Sean Cozart
