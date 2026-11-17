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
from unittest.mock import call, MagicMock, patch

from ros_github_scripts.ci_for_pr import (
    create_ci_gist,
    fetch_pull_stack,
    parse_args,
    parse_pull_spec,
    PullStack,
    validate_and_fetch_pull_list,
    validate_pulls_target,
    validate_stack_target,
    validate_stack_up_to_date,
)
import yaml


def make_pull(number, base_ref='rolling', position=None):
    """Make a mock pull request in the ros2/rviz repository."""
    pull = MagicMock()
    pull.number = number
    pull.head.ref = f'branch-{number}'
    pull.head.sha = f'sha-{number}'
    pull.head.repo.full_name = 'ros2/rviz'
    pull.base.ref = base_ref
    pull.base.repo.full_name = 'ros2/rviz'
    pull.raw_data = {'stack': {'position': position}} if position else {}
    return pull


def make_stack_json(number, base_ref, pulls):
    """Make a PR stack, as returned by the REST API, from (number, state, merged) tuples."""
    return {
        'number': number,
        'base': {'ref': base_ref},
        'pull_requests': [
            {
                'number': pull_number,
                'state': state,
                'merged_at': '2026-10-01T20:57:11Z' if merged else None,
                'head': {'ref': f'branch-{pull_number}', 'sha': f'sha-{pull_number}'},
            }
            for pull_number, state, merged in pulls
        ],
    }


def make_github(stacks, positions):
    """Make a mock GitHub instance where ros2/rviz has the given PR stacks."""
    repo = MagicMock()
    repo.full_name = 'ros2/rviz'
    repo.url = 'https://api.github.com/repos/ros2/rviz'
    repo._requester.requestJsonAndCheck.return_value = ({}, stacks)
    repo.get_pull.side_effect = lambda number: make_pull(number, position=positions[number])
    github_instance = MagicMock()
    github_instance.get_repo.return_value = repo
    return github_instance


def make_pull_stack(base_ref, numbers):
    """Make a PR stack in ros2/rviz with mock pull requests."""
    repo = MagicMock()
    repo.full_name = 'ros2/rviz'
    return PullStack(
        repo=repo, number=100, base_ref=base_ref, pulls=[make_pull(number) for number in numbers])


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


class TestFetchPullStack(unittest.TestCase):

    def test_not_in_stack(self):
        with self.assertRaisesRegex(RuntimeError, 'not part of a GitHub PR stack'):
            fetch_pull_stack(make_github([], {}), 'ros2/rviz#1234')

    def test_stack(self):
        stack = make_stack_json(1917, 'lyrical', [(1915, 'open', False), (1916, 'open', False)])
        github_instance = make_github([stack], {1915: 1, 1916: 2})

        pull_stack = fetch_pull_stack(github_instance, 'https://github.com/ros2/rviz/pull/1915')

        github_instance.get_repo.assert_called_once_with('ros2/rviz')
        repo = github_instance.get_repo.return_value
        repo._requester.requestJsonAndCheck.assert_called_once_with(
            'GET',
            'https://api.github.com/repos/ros2/rviz/stacks',
            parameters={'pull_request': 1915})
        self.assertEqual(pull_stack.number, 1917)
        self.assertEqual(pull_stack.base_ref, 'lyrical')
        self.assertEqual([pull.number for pull in pull_stack.pulls], [1915, 1916])
        self.assertEqual(pull_stack.top.number, 1916)

    def test_order_by_position(self):
        # The top PR of github/gh-stack's stack #530 has the lowest number
        numbers = [526, 527, 528, 529, 521]
        positions = {number: index + 1 for index, number in enumerate(numbers)}
        stack = make_stack_json(530, 'main', [(number, 'open', False) for number in numbers])
        # The order of the PRs in the API response should not matter
        stack['pull_requests'].reverse()

        pull_stack = fetch_pull_stack(make_github([stack], positions), 'ros2/rviz#527')

        self.assertEqual([pull.number for pull in pull_stack.pulls], numbers)
        self.assertEqual(pull_stack.top.number, 521)

    def test_closed_pulls(self):
        stack = make_stack_json(100, 'rolling', [
            (10, 'closed', True),  # merged
            (11, 'closed', False),  # closed without being merged
            (12, 'open', False),
            (13, 'open', False),
        ])

        with self.assertLogs('ros_github_scripts.ci_for_pr', level='WARNING') as logs:
            pull_stack = fetch_pull_stack(make_github([stack], {12: 3, 13: 4}), 'ros2/rviz#12')

        self.assertEqual([pull.number for pull in pull_stack.pulls], [12, 13])
        # Only the PR that was closed without being merged should be reported
        self.assertEqual(len(logs.output), 1)
        self.assertIn('ros2/rviz#11', logs.output[0])

    def test_no_open_pulls(self):
        stack = make_stack_json(580, 'main', [(578, 'closed', True), (579, 'closed', True)])
        with self.assertRaisesRegex(RuntimeError, 'does not have any open PRs'):
            fetch_pull_stack(make_github([stack], {}), 'ros2/rviz#578')

    def test_multiple_stacks(self):
        stacks = [
            make_stack_json(1, 'rolling', [(10, 'open', False)]),
            make_stack_json(2, 'rolling', [(10, 'open', False)]),
        ]
        with self.assertRaisesRegex(RuntimeError, 'multiple GitHub PR stacks'):
            fetch_pull_stack(make_github(stacks, {}), 'ros2/rviz#10')


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


class TestValidateStack(unittest.TestCase):

    @patch('builtins.input')
    def test_target_match(self, mock_input):
        validate_stack_target(make_pull_stack('rolling', [1, 2]), 'rolling')
        mock_input.assert_not_called()

    @patch('builtins.input', return_value='n')
    def test_target_mismatch_abort(self, mock_input):
        with redirect_stdout(io.StringIO()) as stdout:
            with self.assertRaisesRegex(RuntimeError, 'Target mismatch'):
                validate_stack_target(make_pull_stack('lyrical', [1, 2]), 'rolling')
        self.assertIn('ros2/rviz stack #100: lyrical', stdout.getvalue())

    @patch('builtins.input', return_value='y')
    def test_target_mismatch_continue(self, mock_input):
        with redirect_stdout(io.StringIO()):
            validate_stack_target(make_pull_stack('lyrical', [1, 2]), 'rolling')
        mock_input.assert_called_once()

    @patch('builtins.input')
    def test_up_to_date(self, mock_input):
        pull_stack = make_pull_stack('rolling', [1, 2, 3])
        pull_stack.repo.compare.return_value.status = 'ahead'

        validate_stack_up_to_date(pull_stack)

        pull_stack.repo.compare.assert_has_calls([call('sha-1', 'sha-3'), call('sha-2', 'sha-3')])
        mock_input.assert_not_called()

    @patch('builtins.input', return_value='n')
    def test_not_up_to_date_abort(self, mock_input):
        pull_stack = make_pull_stack('rolling', [1, 2, 3])
        # The top PR's branch does not contain the latest changes to the bottom PR's branch
        pull_stack.repo.compare.side_effect = lambda base, head: MagicMock(
            status='diverged' if base == 'sha-1' else 'ahead')

        with redirect_stdout(io.StringIO()) as stdout:
            with self.assertRaisesRegex(RuntimeError, 'not up to date'):
                validate_stack_up_to_date(pull_stack)

        self.assertIn('ros2/rviz#1:', stdout.getvalue())
        self.assertNotIn('ros2/rviz#2:', stdout.getvalue())


class TestParseArgs(unittest.TestCase):

    # Can't use --pulls and --interactive together
    def test_pulls_interactive_exclusive(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parse_args(['--pulls', 'ros2/rclcpp#1', '--interactive'])

    # Can't use --stack with --pulls, --interactive, or --branch
    def test_stack_exclusive(self):
        for other_args in (['--pulls', 'ros2/rclcpp#1'], ['--interactive'], ['--branch', 'b']):
            with self.subTest(other_args=other_args):
                with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    parse_args(['--stack', 'ros2/rviz#1915'] + other_args)


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
