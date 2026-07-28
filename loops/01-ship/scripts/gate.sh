#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# THE GATE — loop 01, configured for telegram_agent (DealWing). Deterministic,
# no model judgement. Exit 0 = shippable.
#
# Two independent apps, both checked every run:
#   be/     FastAPI + Telethon, Python   (pytest — be/tests/, ~90 files)
#   next/   Next 15 + TypeScript         (tsc --noEmit)
#
# There is no .github/workflows, no Makefile, no CONTRIBUTING and no git hooks
# in this repo, so there is no CI to copy. Commands below were derived from
# be/pyproject.toml ([tool.pytest.ini_options]) and next/package.json.
#
# TWO CHECKS THAT SHOULD EXIST BUT CANNOT YET — see the notes at each site:
#   * backend lint/format — no ruff/black installed or configured
#   * frontend lint       — `next lint` has no eslint installed and no config
# Neither is stubbed out as passing. Fix the root cause, then add the step.
#
# Configure via .loops.env (NOT by editing this file — see guard 3 at the
# bottom, which this script enforces on itself).
#
#   GATE_BASE=main       base branch for diffing
#   GATE_SKIP=pytest     steps to skip (rarely, and with an expiry note)
# ─────────────────────────────────────────────────────────────────────────────
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOOPS_ROOT="$(cd "$HERE/../../.." && pwd)"
[ -f "$LOOPS_ROOT/.loops.env" ] && . "$LOOPS_ROOT/.loops.env"

ROOT="${GATE_PROJECT_ROOT:-$LOOPS_ROOT}"
BASE="${GATE_BASE:-main}"
SKIP="${GATE_SKIP:-}"
cd "$ROOT" || { echo "gate: cannot cd to $ROOT" >&2; exit 1; }

fail=0; ran=0; t0=$(date +%s)
RED=''; GRN=''; DIM=''; RST=''
[ -t 1 ] && { RED=$'\033[31m'; GRN=$'\033[32m'; DIM=$'\033[2m'; RST=$'\033[0m'; }

skipped() { case ",$SKIP," in *",$1,"*) return 0 ;; *) return 1 ;; esac; }

step() {
  name="$1"; shift
  skipped "$name" && { echo "  ${DIM}- $name (skipped via GATE_SKIP)${RST}"; return; }
  ran=$((ran+1))
  s=$(date +%s)
  if out=$("$@" 2>&1); then
    echo "  ${GRN}✓${RST} $name ${DIM}($(( $(date +%s) - s ))s)${RST}"
  else
    echo "  ${RED}✗ $name${RST} ${DIM}($(( $(date +%s) - s ))s)${RST}"
    echo "$out" | tail -25 | sed 's/^/      /'
    fail=1
  fi
}

echo "gate: root=$ROOT base=$BASE"
echo

# ── toolchain preconditions. Fail closed and loud: a gate that skips its checks
#    because a tool is missing has proved nothing, which is worse than a red gate.
PY=""
for c in be/.venv/Scripts/python.exe be/.venv/bin/python; do
  [ -x "$ROOT/$c" ] && { PY="$ROOT/$c"; break; }
done
if [ -z "$PY" ]; then
  echo "${RED}gate: FAIL — be/.venv not found${RST}"
  echo "  cd be && python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt"
  exit 1
fi
if [ ! -d "$ROOT/next/node_modules" ]; then
  echo "${RED}gate: FAIL — next/node_modules not found${RST}"
  echo "  cd next && npm ci"
  exit 1
fi

# ── be/ — from be/pyproject.toml: testpaths=["tests"], pythonpath=["."]
echo "be ${DIM}[python / .venv]${RST}"
step "pytest" sh -c "cd '$ROOT/be' && '$PY' -m pytest -q --no-header"
# MISSING: lint + format. be/requirements-dev.txt pins only pytest; pyproject
# configures no ruff/black/mypy. Nothing to run — so nothing is claimed here.
# To close this: add ruff to requirements-dev.txt, add [tool.ruff] to
# pyproject.toml, then add a `step "ruff" ...` line above.
echo "  ${DIM}- lint/format: not configured in this repo (see note in gate.sh)${RST}"
echo

# ── next/ — from next/package.json + next/tsconfig.json
echo "next ${DIM}[next 15 / npm]${RST}"
# package.json has no `typecheck` script, but typescript is a devDependency and
# tsconfig.json exists, so tsc is the real type gate here.
step "typecheck" sh -c "cd '$ROOT/next' && npx --no-install tsc --noEmit"
# MISSING: lint. `npm run lint` is `next lint`, but eslint is not in
# devDependencies and there is no eslint config file. On Next 15 that command
# drops into an INTERACTIVE installer prompt, which would hang this gate
# forever. Deliberately not wired up.
# To close this: cd next && npm i -D eslint eslint-config-next && npx next lint
# --strict to generate a config, then add a `step "lint" ...` line above.
echo "  ${DIM}- lint: eslint not installed/configured (see note in gate.sh)${RST}"
echo

# ── loop guards (keep these; they are why the loop stays honest)
echo "guards"

# 0. Guards 1-3 all diff against $BASE. If $BASE does not resolve, git errors,
#    grep matches nothing, and all three report green — a silent pass, the worst
#    possible failure mode for a gate. Check it explicitly first.
if ! git rev-parse --verify "$BASE" >/dev/null 2>&1; then
  echo "  ${RED}✗ base branch '$BASE' does not resolve${RST} — guards below cannot run"
  echo "      Set GATE_BASE in .loops.env to a branch that exists."
  fail=1
else
  echo "  ${GRN}✓${RST} base '$BASE' resolves"
fi

# 1. Nothing ships with debug statements left in.
if git diff "$BASE"...HEAD -U0 2>/dev/null | grep -nE '^\+.*(debugger;|breakpoint\(\)|import pdb|binding\.pry|console\.log\(["'"'"']?DEBUG)' >/dev/null; then
  echo "  ${RED}✗ debug statements in the diff${RST}"
  git diff "$BASE"...HEAD -U0 2>/dev/null | grep -nE '^\+.*(debugger;|breakpoint\(\)|import pdb|console\.log\(["'"'"']?DEBUG)' | head -5 | sed 's/^/      /'
  fail=1
else
  echo "  ${GRN}✓${RST} no debug statements"
fi

# 2. Skipped tests must be justified in the same line.
# NOTE: upstream shipped this pattern as `xit\(`, unanchored. That also matches
# `sys.exit(`, `SystemExit(` and `typer.Exit(` — 20 false hits on this repo
# alone, which would pin the gate red forever. `\bxit\(` still catches a real
# disabled `xit(...)` but no longer matches the tail of another identifier.
if git diff "$BASE"...HEAD -U0 2>/dev/null | grep -E '^\+.*(it\.skip|describe\.skip|test\.skip|@pytest\.mark\.skip|\bxit\()' | grep -vq 'TODO('; then
  echo "  ${RED}✗ newly skipped tests without a TODO(owner) justification${RST}"; fail=1
else
  echo "  ${GRN}✓${RST} no unjustified test skips"
fi

# 3. The gate cannot be part of the change it is gating.
if git diff --name-only "$BASE"...HEAD 2>/dev/null | grep -qE 'loops/01-ship/scripts/gate\.sh|\.loops\.env'; then
  echo "  ${RED}✗ this change modifies the gate or its config — not allowed inside the loop${RST}"
  echo "      Change the gate in a separate, human-reviewed commit." | sed 's/^/  /'
  fail=1
else
  echo "  ${GRN}✓${RST} gate unmodified by this change"
fi

# ── verdict. Fail closed: zero steps run means the gate proved nothing.
echo
if [ "$ran" -eq 0 ] && [ "${GATE_ALLOW_EMPTY:-0}" != "1" ]; then
  echo "${RED}gate: FAIL — 0 checks ran.${RST} A gate that finds nothing to check has not"
  echo "verified anything."
  exit 1
fi
if [ "$fail" -eq 0 ]; then
  echo "${GRN}gate: PASS${RST} ${DIM}($ran checks, $(( $(date +%s) - t0 ))s)${RST}"
else
  echo "${RED}gate: FAIL${RST} ${DIM}($ran checks, $(( $(date +%s) - t0 ))s)${RST}"
fi
exit $fail
