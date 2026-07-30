# Loop 01 — ship

```
queue/*.md ──▶ implementer ──▶ gate.sh ──┬─fail─▶ back to implementer (trip+1)
                                          └─pass─▶ adversary (read-only) ──┬─BLOCK─▶ punchlist ──▶ trip+1
                                                                            └─PASS──▶ commit ──▶ shipped/ + ledger
```

**Cycle bound:** 3 trips. **Gate:** `scripts/gate.sh`, exit 0 required.
**Enforcement:** the `Stop` hook refuses to let the session end while the gate is red.

## Directories
| dir | meaning | writable by agent |
|---|---|---|
| `queue/` | inbox — specs waiting | **no** (except appending to `_found.md`) |
| `work/` | active slug marker | yes |
| `evidence/<slug>/` | gate output, reviews, punch lists | yes |
| `shipped/` | specs that made it | yes (move only) |
| `ledger.jsonl` | append-only via `scripts/ledger.sh` | via script only |

## Spec format (required)
A spec without numbered acceptance criteria is not admitted to the loop. Push it back.

```markdown
# <title>
## Context
## Acceptance criteria
1. <observable, testable statement>
2. ...
## Out of scope
## Non-functional
```

## Rules
- The implementer never reviews its own diff. The adversary never edits.
- Changing `gate.sh` or a test to reach green is the one unforgivable move in this loop.
- Trip 3 failure → `BLOCKED.md` and stop. Escalate to a human with a single clear decision.
- Anything discovered but out of scope goes to `queue/_found.md`, never into the diff.
