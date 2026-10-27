# Agent guidance for ros-github-scripts

This file is for AI coding agents (Claude, Codex, Cursor, or similar) driving
these CLI tools on a human's behalf, instead of clicking through the Jenkins
UI by hand. It covers the three tools in this repo: `ros-ci-for-pr`,
`ros-find-restarted-ci`, and `ros-github-contribution-report`.

## Setup (check before first use)

```bash
command -v ros-ci-for-pr >/dev/null || echo "not installed"
```

If missing, install from a local clone (not a PyPI package name):

```bash
git clone https://github.com/ros-tooling/ros-github-scripts /tmp/ros-github-scripts
uv tool install /tmp/ros-github-scripts
```

All three tools need a GitHub token. Check `GITHUB_ACCESS_TOKEN` or
`GITHUB_TOKEN` is set before running anything:

```bash
[ -n "${GITHUB_ACCESS_TOKEN:-${GITHUB_TOKEN:-}}" ] && echo "token set" || echo "token unset"
```

For `ros-ci-for-pr --build --comment`, the token must be a **classic**
personal access token (fine-grained tokens are not supported) with scopes:
`public_repo` (post comments), `gist` (create the repos-file gist), and
`read:org` (trigger the Jenkins job). Without build access on ci.ros2.org
(membership in the `ros2/ci-builders` GitHub team), omit `--build` and just
hand the user the gist/branch info to paste themselves.

If no token env var is set, fall back to a `gh auth token` lookup if the
user is authenticated via the `gh` CLI, and tell them which scopes to check
if a call fails with a permissions error.

## ros-ci-for-pr: launch a CI build for one or more PRs

This drives the `ci_launcher` job on ci.ros2.org from the command line.

**Default to `--pulls` with `--build` and `--comment` together.** The
normal case is testing a PR off someone's fork, which needs a gist built
from that fork/branch — `--pulls` does this automatically. `--branch` only
applies when the branch was pushed directly to the upstream repo (no fork
involved), which is rare — reach for it only for coordinated multi-repo
changes pushed straight to `ros2/*`, not for an ordinary PR. Always pair
the run with `--comment` so the status badges land on the PR itself
instead of sitting in a terminal for someone to paste manually — don't run
it without `--comment` unless the user explicitly wants a dry run or
doesn't have comment permissions on the target repo.

**Always show the exact command before running it.** `--build` triggers a
real Jenkins run and `--comment` posts a public, visible comment on
someone else's PR — both are externally-visible, hard-to-undo actions
worth a quick look before executing, even when the user has already asked
to launch CI. Print the full `ros-ci-for-pr ...` invocation you're about
to run (repo/PR, packages, any extra colcon args) and get a go-ahead
first.

### Typical invocation

```bash
export GITHUB_ACCESS_TOKEN=$(gh auth token)
ros-ci-for-pr \
  --pulls ros2/rosbag2#2542 \
  --packages rosbag2_tests \
  --build \
  --comment
```

- `--pulls` takes one or more `ORG/REPO#NUM` strings (or full
  `https://github.com/ORG/REPO/pull/NUM` URLs), space-separated. One PR per
  repo max per invocation — if the user names multiple PRs in the same
  repo, that's an error from the tool, not something to work around.
- `--packages` restricts the colcon build/test scope. **Always pass this**
  when you know which packages the PR touches (check with
  `gh pr view <num> -R <repo> --json files`) — a default run builds and
  tests 300+ packages across four platforms and ties up shared CI capacity
  for hours. By default this expands to
  `--packages-above-and-dependencies <pkgs>` for the build and
  `--packages-above <pkgs>` for the test step (build everything that could
  be affected, test everything downstream). If the PR is a test-only fix
  (no library code changed), add `--only-fixes-test` instead, which
  narrows this to `--packages-up-to`/`--packages-select` on just those
  packages — much faster, only use it when you're sure no other package's
  tests could be affected.
- `--build` actually invokes the Jenkins job and prints the per-platform
  build-status badges. Without it, the tool only prints what *would* be
  sent (gist URL + params) — useful as a dry run, or for a user without
  build access who will trigger it by hand.
- `--comment` posts the output as a comment on the PR(s) in `--pulls`.
  Without it, the tool prints the same text to paste manually — always
  show the user this output either way.
- `--target <distro>` defaults to `rolling`; set it explicitly if the PR's
  base branch is a different distro (the tool will prompt/warn on a
  mismatch between `--target` and the PR's actual base branch when
  `--build` is set).
- `--colcon-build-args` / `--colcon-test-args` / `--cmake-args` pass
  through raw extra arguments to colcon/CMake; only valid together with
  `--build`.
- `-i`/`--interactive` lets the user pick from their own open PRs instead
  of naming them — offer this if they're vague about which PR they mean.

### Multi-repo branch example

```bash
export GITHUB_ACCESS_TOKEN=$(gh auth token)
ros-ci-for-pr \
  --branch mjcarroll/multi-repo-feature \
  --pulls ros2/rclcpp#123 ros2/rclpy#456 \
  --packages rclcpp rclpy \
  --build \
  --comment
```

`--pulls` here is only used for the `--comment` target list, not for
sourcing the diff (the branch name is).

### Checking on a build afterwards

Pass the printed `ci_launcher` build URL (e.g.
`https://ci.ros2.org/job/ci_launcher/19468`) back in with `--test-report`
to pull JUnit results from all four child platform builds and format a
pass/fail summary table, once the build has finished:

```bash
ros-ci-for-pr --test-report https://ci.ros2.org/job/ci_launcher/19468 \
  --pulls ros2/rosbag2#2542 --comment
```

Mutually exclusive with `--build` — this reads an existing run, it doesn't
start one.

## ros-find-restarted-ci: diagnose a "failed" build that was actually restarted

Jenkins workers on ci.ros2.org sometimes get interrupted (preemption,
infra issues) mid-build and silently reschedule — the GitHub comment still
points at the original, now-stale build/badge, which can read as a failure
even though a newer build of the same `ci_launcher` invocation actually
passed. Reach for this when the user says a CI comment "looks wrong",
"says failed but I think it reran", or a badge is stuck. It only relinks
genuine infra restarts (same upstream `ci_launcher` build ID) — a build
that failed for real (code/test error) is left alone, since Jenkins
doesn't auto-reschedule those.

```bash
# inspect only, no changes:
ros-find-restarted-ci ros2/rosidl_typesupport_fastrtps#160

# or with a specific comment:
ros-find-restarted-ci "https://github.com/ros2/rmw_implementation/pull/99#issuecomment-5349858725"

# apply the fix (edits the GitHub comment in place):
ros-find-restarted-ci -u "https://github.com/ros2/rmw_implementation/pull/99"
```

Run it once without `-u`/`--update-comment` first and show the user what
it found before applying — editing someone else's PR comment is a
visible, hard-to-undo action worth confirming first. `--jenkins-user`/
`--jenkins-token` override the defaults (authenticated GitHub user + the
same GitHub token) only if the user's Jenkins credentials differ.

## ros-github-contribution-report: merged-PR activity report

For "who merged what" rollups (e.g. monthly TSC reports), not for anything
CI-related.

```bash
ros-github-contribution-report \
  --since 2026-10-01 \
  --authors mjcarroll \
  --orgs ros2 ros-tooling \
  --format table \
  --render-html > report.html
```

- `--authors` and/or `--authors-from-org <org>` select whose merges to
  report — at least one should normally be given, or the query runs
  against every merged PR the token can see.
- `--orgs`/`--repos` scope which repos count; omit both and it searches
  everywhere, which is usually too broad.
- `--format tsc` (default) matches the monthly ROS 2 TSC report style;
  `--format table` is for an HTML table — pair with `--render-html` to get
  actual HTML instead of raw markdown.
- `--token` is optional here (unauthenticated GitHub API calls work, just
  rate-limited harder) — still prefer passing one for anything beyond a
  tiny date range.

## Quick reference

| Task | Command |
|---|---|
| Launch CI for a PR | `ros-ci-for-pr --pulls ORG/REPO#N --packages PKG... --build --comment` |
| Launch CI for a cross-repo branch | `ros-ci-for-pr --branch NAME --pulls ORG/REPO#N... --packages PKG... --build --comment` |
| Dry run (no Jenkins call) | same as above, minus `--build` |
| Pull test results from a finished run | `ros-ci-for-pr --test-report <ci_launcher URL> --pulls ORG/REPO#N --comment` |
| Fix a stale "failed" badge from a restarted build | `ros-find-restarted-ci -u <PR or comment URL>` |
| Monthly contribution report | `ros-github-contribution-report --since DATE --authors ... --format table --render-html` |
