# Dependency Map

This document records the minimum dependency ordering for the rebuild. If a provider is incomplete, downstream work stays blocked instead of inventing missing contracts.

| Provider Layer                   | Consumer Layer                                     | Contract                                                               | Why It Matters                                              | Status   |
| -------------------------------- | -------------------------------------------------- | ---------------------------------------------------------------------- | ----------------------------------------------------------- | -------- |
| Rebuild containment scaffold     | All other workstreams                              | Stable `rebuild/` directory boundaries and coordination docs           | Prevents legacy/new overlap and establishes ownership       | Complete |
| Shared schema and compatibility  | Windows preparation                                | `plan_schema.py`, version compatibility, release manifest contract     | Windows plan generation must not invent fields              | Pending  |
| Shared schema and compatibility  | Arch live installer                                | `plan.json` loading, validation, compatibility checks                  | Live installer must validate instead of guessing            | Pending  |
| Shared models                    | Arch disk matcher                                  | Stable disk, EFI, Windows, and free-space identity models              | Prevents device-name-based guesses                          | Pending  |
| Windows checks and backups       | Windows Ventoy and plan writer                     | Verified machine state and backup destination metadata                 | Prevents unsafe handoff preparation                         | Pending  |
| Windows Ventoy and ISO placement | Arch live handoff discovery                        | Deterministic USB path and handoff file placement                      | Live installer must find the correct payload                | Pending  |
| Arch live install foundation     | Omarchy handoff                                    | Installed target, boot policy, and persisted first-boot wrapper inputs | Omarchy must only run after a valid install completes       | Pending  |
| Boot policy implementation       | Boot guardian                                      | Expected boot state JSON and repair policy                             | Guardian must measure against a defined target state        | Pending  |
| Packaging configuration          | Windows EXE workflow                               | PyInstaller inputs and version metadata                                | CI cannot package reliably without stable inputs            | Pending  |
| ISO payload structure            | ISO workflow                                       | Payload tree, entrypoint, and runtime dependency contract              | CI cannot inject or rebuild correctly without stable layout | Pending  |
| Release manifest contract        | Windows updates and Omarchy location health checks | Compatible build metadata and upstream bootstrap expectations          | Prevents stale or unsafe pairings                           | Pending  |

## Blocking policy

- Downstream issues must be marked blocked when an upstream contract is incomplete.
- Safety-critical downstream code must not create placeholder behavior to bypass missing dependencies.
- Shared contracts should be versioned explicitly before multiple consumers depend on them.
