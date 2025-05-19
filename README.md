# ros-github-scripts
Utility scripts to ease management of GitHub projects for ROS / ROS 2

## Installation

This is a `setuptools`-based python package. To install it and all its dependencies:

```
# Note that this is by _path_, it's not the name of a package on PyPI - so substitute as appropriate for your working directory
pip3 install ./ros-github-scripts
```


## ros-ci-for-pr

### With a list of PRs

Creates a github gist containing a modified ros2.repos, with the source branches from one or more PRs.
Optionally, runs ci.ros2.org jobs and comments the status badges on the PRs in question - if the user has build access to ci.ros2.org.

See `ros-ci-for-pr --help` for full usage.

Example average case:

```
export GITHUB_ACCESS_TOKEN=$GITHUB_TOKEN
ros-ci-for-pr \
  --pulls ros2/rosbag2#654 \
  --packages rosbag2_cpp rosbag2_tests \
  --build \
  --colcon-build-args="--continue-on-error" \
  --comment
```

Note that the access token must have at least the "public_repo" permission (to be able to post comments), the "gist" permission (to be able to create gists), and the "read:org" permission (to be able to create the Jenkins job).

> [!IMPORTANT]
> Please use classic access token instead of fine-grained access token. (see [Fine-grained personal access tokens limitations](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens#fine-grained-personal-access-tokens-limitations))

### With a branch name

As an alternative to the above, a branch name can be provided using the `--branch` option.
CI tries to check out that branch in all ROS 2 core repositories; if such a branch exists, it then merges it into the distro's target branch and tests that.
This is useful when making changes to multiple repos at once, but it requires pushing branches to the actual repository and not a fork.

When using the `--branch` and `--comment` options, provide a list of PRs on which to comment using either `--pulls` or `--interactive`.

Example:

```
export GITHUB_ACCESS_TOKEN=$GITHUB_TOKEN
ros-ci-for-pr \
  --branch username/multi-repo-feature \
  --pulls ros2/repo1#123 ros2/repo2#456 ros2/repo3#789 \
  --packages pkg1 pkg2 pkg3 \
  --build \
  --comment
```

## ros-github-contribution-report

Generates a report of merged PRs on GitHub from a set of authors, optionally filtered by time and destination, and rendered to a variety of formats.

See `ros-github-contribution-report --help` for full usage.

Example average case:

```
ros-github-contribution-report \
  --since 2021-01-01 \
  --token $GITHUB_ACCESS_TOKEN \
  --authors emersonknapp \
  --orgs ros2 ros-tooling \
  --format table \
  --render > my_contributions_this_year.html
```



## Developing

Run tests by invoking `tox` in the repository directory.
