# ros-github-scripts
Utility scripts to ease management of GitHub projects for ROS / ROS 2

## ros-ci-for-pr

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

Dependencies you likely need to install first:
```
pip3 install PyGithub
pip3 install markdown2
```

## Developing

Run tests by invoking `tox` in the repository directory.
