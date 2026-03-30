# Development Notes

This document collects the practical rules for working inside the rebuild.

## Working defaults

- Start from `rebuild/`.
- Keep changes inside the ownership boundary for the current issue.
- Treat coordination docs as part of the product, not as side notes.
- Update `rebuild/docs/STATUS.md` when coordination state changes.

## Execution order

Follow the mandatory stage order from Stage 0 through Stage 12.
Do not skip ahead when an upstream contract is missing.

## Safety reminders

- Do not touch legacy runtime files from a rebuild slice unless the issue explicitly owns that boundary.
- Safety-critical work needs extra review and should stay tightly scoped.
- If a dependency is incomplete, mark the dependent work blocked instead of guessing.

## Issue and PR discipline

- Keep one issue aligned to one coherent slice whenever possible.
- Keep pull requests reviewable and boundary-aware.
- Restate the scope and the acceptance criteria in the issue or PR body when work changes coordination state.

## Useful coordination docs

- `rebuild/docs/architecture.md`
- `rebuild/docs/boot-protection.md`
- `rebuild/docs/plan-schema.md`
- `rebuild/docs/release-process.md`
- `rebuild/docs/stage-briefs.md`
- `rebuild/docs/issue-hierarchy.md`
- `rebuild/docs/dependency-map.md`
- `rebuild/docs/ownership-map.md`
- `rebuild/docs/coordination-rules.md`

## Current state reminder

The rebuild is still in the containment and foundation phase. Shared contracts, coordination docs, and issue hierarchy work must stay ahead of runtime replacement work.
