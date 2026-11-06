# Releasing trialmark-forge

trialmark-forge is published to PyPI by trusted publishing from `.github/workflows/publish.yml`, through
the GitHub environment `pypi`. No PyPI token exists or is needed. Pushing a version tag starts
the publish.

1. Raise the version number in both `pyproject.toml` and `src/trialmark_forge/__init__.py`, and add a
   `## <version>, <date>` entry at the top of `CHANGELOG.md`.
2. Run the tests with `pytest -q`.
3. Commit, push to `main`, and wait for the tests on GitHub to pass.
4. Run the release script, from any folder:

   ```bash
   ~/claude/trialmark-forge/scripts/release.sh --dry-run   # checks everything, tags nothing
   ~/claude/trialmark-forge/scripts/release.sh             # checks, asks, then tags and pushes
   ```

   It works in the repository it belongs to, whatever folder you run it from, so a tag cannot
   land in another repository. Before tagging it checks that:

   - the repository's remote is `peshwar9/trialmark-forge`;
   - you are on `main`, with nothing uncommitted, and level with GitHub;
   - the version is the same in `pyproject.toml` and `src/trialmark_forge/__init__.py`;
   - the tag does not exist yet, here or on GitHub;
   - `CHANGELOG.md` has an entry for the version;
   - the tests passed on GitHub for this commit (when `gh` is installed).

5. The publish workflow runs the tests, checks the tag matches the package version, builds the
   package and publishes it. Check the run with
   `gh run list -R peshwar9/trialmark-forge --workflow publish.yml --limit 1`, and the release at
   https://pypi.org/project/trialmark-forge/.

A version number can be published to PyPI only once. If a release is wrong, fix it and publish
the next version.
