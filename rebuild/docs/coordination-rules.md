# Coordination Rules

## Branching

- The rebuild coordination branch is `Python-Rebuild`.
- Rebuild implementation branches should target `Python-Rebuild`, not `main`.
- Prefer one branch per issue or tightly related slice.

## Pull request discipline

- Keep each PR within a single workstream whenever possible.
- Do not combine build automation, Windows runtime, and Arch runtime changes in one PR unless the issue explicitly owns all touched boundaries.
- Safety-critical PRs must stay small and easy to review.

## Required PR checks

- Linked issue is present.
- Allowed files match the issue scope.
- Forbidden files were not touched.
- Acceptance criteria are restated and verified.
- Status ledger was updated if the coordination state changed.

## Blocking behavior

- If an upstream dependency is incomplete, mark the downstream issue blocked.
- Do not invent schema fields, boot assumptions, or handoff behavior to work around missing contracts.
- Do not move work across ownership boundaries for convenience.

## Safety-critical review areas

- EFI handling
- BCD handling
- BitLocker state
- Fast Startup handling
- Secure Boot behavior
- Partition shrink and creation logic
- Bootloader policy and Windows preservation
- Omarchy bootstrap location assumptions

## Definition of done

A rebuild issue is complete only when:

- the scoped files exist
- the issue stayed inside its ownership boundary
- acceptance criteria are satisfied
- the PR remains reviewable
- required coordination docs are updated
