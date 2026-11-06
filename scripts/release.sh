#!/bin/sh
# Tags and publishes a trialmark-forge release, from any folder.
#
#   scripts/release.sh             check everything, ask, then tag and push
#   scripts/release.sh --dry-run   check everything and stop
#
# It works in the repository this script belongs to, whatever folder you run it
# from, so a tag can never land in another repository. Pushing the tag starts the
# publish workflow (.github/workflows/publish.yml), which publishes to PyPI.
set -eu

DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1

ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
fail() { echo "release: $1" >&2; exit 1; }

# The right repository.
URL=$(git remote get-url origin 2>/dev/null || true)
case "$URL" in
  # Exact, so the Trialmark repository (whose name this one starts with) cannot match.
  *peshwar9/trialmark-forge|*peshwar9/trialmark-forge.git) ;;
  *) fail "origin is '$URL', not peshwar9/trialmark-forge. Run the script from the trialmark-forge repository." ;;
esac

# On main, clean, and level with GitHub.
[ "$(git branch --show-current)" = "main" ] || fail "not on main."
[ -z "$(git status --porcelain)" ] || fail "there are uncommitted changes. Commit or stash them first."
git fetch -q origin main
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] || fail "main differs from GitHub. Push or pull first."

# One version, in both places.
V1=$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)
V2=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' src/trialmark_forge/__init__.py)
[ -n "$V1" ] && [ "$V1" = "$V2" ] || fail "pyproject.toml says '$V1' but src/trialmark_forge/__init__.py says '$V2'."
TAG="v$V1"

# Not released already.
git rev-parse -q --verify "refs/tags/$TAG" >/dev/null && fail "$TAG already exists here. Raise the version first."
git ls-remote --exit-code --tags origin "refs/tags/$TAG" >/dev/null 2>&1 && fail "$TAG already exists on GitHub. Raise the version first."
grep -q "^## $V1," CHANGELOG.md || fail "CHANGELOG.md has no entry for $V1."

# The tests passed on GitHub for this commit, when gh can tell.
if command -v gh >/dev/null 2>&1; then
  SHA=$(git rev-parse HEAD)
  RESULT=$(gh run list -R peshwar9/trialmark-forge --workflow test.yml --commit "$SHA" --limit 1 \
           --json status,conclusion --jq '.[0].status + " " + .[0].conclusion' 2>/dev/null || true)
  case "$RESULT" in
    "completed success") echo "Tests passed on GitHub for $(git rev-parse --short HEAD)." ;;
    "") fail "no test run on GitHub for this commit yet. Wait for it, then run this again." ;;
    *) fail "the tests on GitHub for this commit are '$RESULT'. Fix them first." ;;
  esac
else
  echo "gh is not installed, so the GitHub test result was not checked."
fi

echo "Ready to release trialmark-forge $V1 from $(git rev-parse --short HEAD) in $ROOT."
if [ "$DRY" = 1 ]; then
  echo "Dry run: nothing tagged."
  exit 0
fi
printf "Tag %s and publish it to PyPI? [y/N] " "$TAG"
read -r ANSWER
[ "$ANSWER" = "y" ] || [ "$ANSWER" = "Y" ] || fail "nothing tagged."

git tag "$TAG"
git push -q origin "$TAG"
echo "Pushed $TAG. Publishing: gh run list -R peshwar9/trialmark-forge --workflow publish.yml --limit 1"
echo "Then check https://pypi.org/project/trialmark-forge/$V1/"
