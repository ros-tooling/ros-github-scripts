# Copyright 2026 Open Source Robotics Foundation, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from contextlib import redirect_stderr, redirect_stdout
import io
import unittest
from unittest.mock import MagicMock, patch

from ros_github_scripts.ci_for_pr import (
    create_ci_gist,
    parse_args,
    parse_pull_spec,
    validate_and_fetch_pull_list,
    validate_pulls_target,
)
import yaml


def make_pull(number, base_ref='rolling'):
    """Make a mock pull request in the ros2/rviz repository."""
    pull = MagicMock()
    pull.number = number
    pull.head.ref = f'branch-{number}'
    pull.head.repo.full_name = 'ros2/rviz'
    pull.base.ref = base_ref
    pull.base.repo.full_name = 'ros2/rviz'
    return pull


class TestParsePullSpec(unittest.TestCase):

    def test_valid_pull_descriptors(self):
        self.assertEqual(parse_pull_spec('ros2/rviz#1915'), ('ros2/rviz', 1915))
        self.assertEqual(
            parse_pull_spec('https://github.com/ros2/rviz/pull/1915'), ('ros2/rviz', 1915))

    def test_invalid_pull_descriptors(self):
        for pull in ('ros2/rviz', 'ros2/rviz#1#2', 'ros2/rviz#abc'):
            with self.subTest(pull=pull):
                with self.assertRaises(RuntimeError):
                    parse_pull_spec(pull)


class TestValidateAndFetchPullList(unittest.TestCase):

    def test_valid_pull_descriptors(self):
        repos = {'ros2/rclcpp': MagicMock(), 'ros2/rclpy': MagicMock()}
        github_instance = MagicMock()
        github_instance.get_repo.side_effect = repos.__getitem__

        pulls = validate_and_fetch_pull_list(
            github_instance, ['ros2/rclcpp#123', 'https://github.com/ros2/rclpy/pull/45'])

        rclcpp_get_pull = repos['ros2/rclcpp'].get_pull
        rclpy_get_pull = repos['ros2/rclpy'].get_pull
        rclcpp_get_pull.assert_called_once_with(123)
        rclpy_get_pull.assert_called_once_with(45)
        self.assertEqual(pulls, [rclcpp_get_pull.return_value, rclpy_get_pull.return_value])

    def test_invalid_pull_number(self):
        for pull in ('ros2/rclcpp#abc', 'ros2/rclcpp#12a', 'ros2/rclcpp#'):
            with self.subTest(pull=pull):
                with self.assertRaisesRegex(RuntimeError, "isn't a number"):
                    validate_and_fetch_pull_list(MagicMock(), [pull])


class TestValidatePullsTarget(unittest.TestCase):

    @patch('builtins.input')
    def test_target_match(self, mock_input):
        validate_pulls_target([make_pull(1), make_pull(2)], 'rolling')
        mock_input.assert_not_called()

    @patch('builtins.input', return_value='n')
    def test_target_mismatch_abort(self, mock_input):
        with redirect_stdout(io.StringIO()) as stdout:
            with self.assertRaisesRegex(RuntimeError, 'Target mismatch'):
                validate_pulls_target([make_pull(1), make_pull(2, 'lyrical')], 'rolling')
        self.assertIn('ros2/rviz#2: lyrical', stdout.getvalue())
        self.assertNotIn('ros2/rviz#1:', stdout.getvalue())

    @patch('builtins.input', return_value='y')
    def test_target_mismatch_continue(self, mock_input):
        with redirect_stdout(io.StringIO()):
            validate_pulls_target([make_pull(1, 'lyrical')], 'rolling')
        mock_input.assert_called_once()


class TestParseArgs(unittest.TestCase):

    # Can't use --pulls and --interactive together
    def test_pulls_interactive_exclusive(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parse_args(['--pulls', 'ros2/rclcpp#1', '--interactive'])


class TestCreateCIGist(unittest.TestCase):

    def run_create_ci_gist(self, pulls, description_pulls=None):
        """Create a gist for mock PRs, and return its repositories and its description."""
        github_instance = MagicMock()
        github_instance.get_repo.return_value.get_contents.return_value.decoded_content = (
            b'repositories:\n'
            b'  ros2/rviz:\n'
            b'    type: git\n'
            b'    url: https://github.com/ros2/rviz.git\n'
            b'    version: rolling\n')
        with patch('ros_github_scripts.ci_for_pr.InputFileContent') as input_file_content:
            create_ci_gist(github_instance, pulls, 'rolling', description_pulls=description_pulls)
        repos = yaml.safe_load(input_file_content.call_args.kwargs['content'])['repositories']
        create_gist = github_instance.get_user.return_value.create_gist
        return repos, create_gist.call_args.kwargs['description']

    def test_pulls(self):
        repos, description = self.run_create_ci_gist([make_pull(1915)])
        self.assertEqual(repos['ros2/rviz']['version'], 'branch-1915')
        self.assertEqual(description, 'CI input for PR ros2/rviz#1915')

    def test_description_pulls(self):
        pulls = [make_pull(1915), make_pull(1916)]
        repos, description = self.run_create_ci_gist([pulls[-1]], description_pulls=pulls)
        self.assertEqual(repos['ros2/rviz']['version'], 'branch-1916')
        self.assertEqual(description, 'CI input for PR ros2/rviz#1915 ros2/rviz#1916')
