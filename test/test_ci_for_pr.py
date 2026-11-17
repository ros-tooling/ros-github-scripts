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

import unittest
from unittest.mock import MagicMock

from ros_github_scripts.ci_for_pr import validate_and_fetch_pull_list


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
