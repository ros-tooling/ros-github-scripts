# Agent guidance for ros-github-scripts

Guidance for AI coding agents driving `ros-ci-for-pr` and
`ros-find-restarted-ci` on a human's behalf.

## Before running anything

- Check the CLI is installed: `command -v ros-ci-for-pr`. If not, `uv tool
  install` from a local clone of this repo (not a PyPI name).
- Check a token is set: `GITHUB_ACCESS_TOKEN` or `GITHUB_TOKEN`. If unset,
  fall back to `gh auth token`. `--build --comment` needs a **classic**
  PAT with `public_repo`, `gist`, and `read:org` scopes (fine-grained
  tokens aren't supported). Without build access on ci.ros2.org
  (`ros2/ci-builders` team membership), drop `--build` and hand the user
  the gist/params to run themselves.
- **Always show the exact command and get a go-ahead before running it.**
  `--build` triggers a real Jenkins run; `--comment` posts publicly on
  someone else's PR; `ros-find-restarted-ci -u` edits an existing comment.
  All three are visible, hard-to-undo actions.

## ros-ci-for-pr

```bash
export GITHUB_ACCESS_TOKEN=$(gh auth token)
ros-ci-for-pr --pulls ros2/rosbag2#2542 --packages rosbag2_tests --build --comment
```

- Default to `--pulls ORG/REPO#N` (one PR per repo) with `--build` and
  `--comment` together. Use `--branch NAME` only for a branch pushed
  directly to `ros2/*` (no fork), e.g. a coordinated multi-repo change.
- **Always pass `--packages`** when you know what the PR touches (`gh pr
  view N -R ORG/REPO --json files`) — an unscoped run builds/tests 300+
  packages across four platforms. It expands to
  `--packages-above-and-dependencies` for build and `--packages-above` for
  test. If the change is test-only, use `--only-fixes-test` instead for a
  much narrower/faster run.
- `--target <distro>` defaults to `rolling`; set explicitly if the PR's
  base branch differs.
- Once the build finishes, pull results with `--test-report <ci_launcher
  URL> --pulls ORG/REPO#N --comment` (mutually exclusive with `--build`).

## ros-find-restarted-ci

Fixes a stale "failed" badge when Jenkins silently restarted a build after
an infra interruption (preemption, agent disconnect) — the PR comment
still points at the original, now-stale build. It only relinks genuine
restarts of the same `ci_launcher` build; a real failure is left alone.

```bash
ros-find-restarted-ci ros2/rosidl_typesupport_fastrtps#160   # inspect only
ros-find-restarted-ci -u "https://github.com/ros2/rmw_implementation/pull/99"  # apply fix
```

Run without `-u` first and show the user what it found before applying.

## Quick reference

| Task | Command |
|---|---|
| Launch CI for a PR | `ros-ci-for-pr --pulls ORG/REPO#N --packages PKG... --build --comment` |
| Dry run (no Jenkins call) | same, minus `--build` |
| Pull test results from a finished run | `ros-ci-for-pr --test-report <ci_launcher URL> --pulls ORG/REPO#N --comment` |
| Fix a stale "failed" badge | `ros-find-restarted-ci -u <PR or comment URL>` |
