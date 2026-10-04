#!/usr/bin/env bash

# -----------------------------------------------------------------------------
# CTO NOTE:
# This script standardizes local commit hygiene.
# It reduces friction, enforces consistency, and removes emotional overhead
# from repetitive Git operations.
# -----------------------------------------------------------------------------

# Fail fast on errors to avoid partial state (optional but recommended)
# set -e

# -----------------------------------------------------------------------------
# Visual feedback matters.
# Clear, colorized output improves developer experience and reduces mistakes
# during repetitive workflows.
# -----------------------------------------------------------------------------
GREEN="\033[0;32m"
BLUE="\033[0;34m"
YELLOW="\033[1;33m"
NC="\033[0m" # No Color

# -----------------------------------------------------------------------------
# CTO NOTE:
# Commit messages are intentionally lightweight and human.
# Not every change deserves ceremony; velocity beats perfection here.
#
# IMPORTANT:
# This script is designed for *non-critical* or *iterative* changes.
# For regulated or production-critical flows, conventional commits
# or ticket-linked messages should be enforced via CI.
# -----------------------------------------------------------------------------
messages=(
  "Refactoring the universe"
  "Fixing stuff nobody asked for"
  "Performance boosted by 0.0001%"
  "Code cleanup: because hygiene matters"
  "Microservice unlocked"
  "Stabilizing the unstable"
  "Improved readability for future generations"
  "Another day, another commit"
  "Removed dead code. RIP."
  "Optimized like a pro"
  "Fixing bugs I created earlier"
  "Production-ready... I hope"
  "Better logs, better life"
  "Future-proofing the past"
  "Documentation added. Miracles happen!"
  "Secret feature deployed"
  "Made everything 1% faster"
  "Less code, more power"
  "Patch applied bravely"
  "Making it work... eventually"
  "Chasing performance ghosts"
  "Removing TODOs from 2 months ago"
  "Test coverage? Slightly better"
  "Stabilizing chaos"
  "Hotfixing like a firefighter"
  "Upgraded logic from 'meh' to 'ok'"
  "Unbreaking things"
  "Unlocking Level 2 DevOps"
  "Injecting quality"
  "Deploying pure magic"
  "Fixing the mess I found"
  "Cleaned code. Mom would be proud"
  "Because Git forced me"
  "Auto-commit: trust me, I'm a developer"
  "Refactor: Now with 30% more elegance"
  "This commit deserves a coffee"
  "Making things smoother than butter"
  "Feature delivered. Customer happy. Probably."
  "Quality increased by ±5%"
)

# -----------------------------------------------------------------------------
# Randomization reduces decision fatigue.
# Engineers should think about architecture, not wording.
# -----------------------------------------------------------------------------
RANDOM_MESSAGE="${messages[$RANDOM % ${#messages[@]}]}"

echo -e "${BLUE}>> Pulling latest changes...${NC}"
# -----------------------------------------------------------------------------
# CTO NOTE:
# Always sync before committing to minimize merge conflicts
# and accidental overwrites in shared branches.
# -----------------------------------------------------------------------------
git pull

echo -e "${BLUE}>> Adding changes...${NC}"
# -----------------------------------------------------------------------------
# This script assumes intentional working directory state.
# In high-risk repos, consider scoped `git add` instead.
# -----------------------------------------------------------------------------
git add .

# -----------------------------------------------------------------------------
# Guardrail:
# Prevents empty commits which pollute history and confuse audits.
# -----------------------------------------------------------------------------
if git diff --cached --quiet; then
  echo -e "${YELLOW}>> No changes staged. Nothing to commit.${NC}"
  exit 0
fi

echo -e "${GREEN}>> Committing with message:${NC} \"$RANDOM_MESSAGE\""
# -----------------------------------------------------------------------------
# CTO NOTE:
# Commit messages here optimize for flow, not traceability.
# Traceability should live in PRs, tickets, and CI metadata — not commits.
# -----------------------------------------------------------------------------
git commit -m "$RANDOM_MESSAGE"

echo -e "${GREEN}>> Pushing...${NC}"
# -----------------------------------------------------------------------------
# Automation principle:
# If a step is always executed manually, it should be scripted.
# -----------------------------------------------------------------------------
git push

echo -e "${GREEN}✔ All done!${NC}"

# -----------------------------------------------------------------------------
# CTO FINAL NOTE:
# Tools like this are culture.
# They signal trust in engineers, bias toward delivery,
# and respect for cognitive load.
# -----------------------------------------------------------------------------

