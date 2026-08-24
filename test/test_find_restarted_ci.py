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

from ros_github_scripts.find_restarted_ci import (
    BuildResult,
    find_latest_job_build,
    parse_ci_comment,
    parse_comment_target,
    update_comment_body,
)


class TestFindRestartedCI(unittest.TestCase):

    def test_parse_comment_target(self):
        # 1. Full PR issuecomment URL
        repo, pr, cid = parse_comment_target(
            'https://github.com/ros2/rosidl_typesupport_fastrtps/pull/160#issuecomment-5349716978'
        )
        self.assertEqual(repo, 'ros2/rosidl_typesupport_fastrtps')
        self.assertEqual(pr, 160)
        self.assertEqual(cid, 5349716978)

        # 2. Issue comment URL
        repo, pr, cid = parse_comment_target(
            'https://github.com/ros2/launch/issues/comments/4637364085'
        )
        self.assertEqual(repo, 'ros2/launch')
        self.assertIsNone(pr)
        self.assertEqual(cid, 4637364085)

        # 3. PR URL without comment
        repo, pr, cid = parse_comment_target(
            'https://github.com/ros2/rmw_implementation/pull/99'
        )
        self.assertEqual(repo, 'ros2/rmw_implementation')
        self.assertEqual(pr, 99)
        self.assertIsNone(cid)

        # 4. org/repo#pr shorthand
        repo, pr, cid = parse_comment_target('ros2/rclcpp#3227')
        self.assertEqual(repo, 'ros2/rclcpp')
        self.assertEqual(pr, 3227)
        self.assertIsNone(cid)

    def test_parse_ci_comment_gist(self):
        sample_comment_body = (
            'Pulls: ros2/rosidl_typesupport_fastrtps#160\n'
            'Gist: https://gist.githubusercontent.com/wjwwood/2544c58104da04ad79b07646404951c1/raw/f2dd2f3ec0e144c7a903a82318fe0419a5fa857a/ros2.repos\n'
            'BUILD args:  --packages-above-and-dependencies rosidl_typesupport_fastrtps_c rosidl_typesupport_fastrtps_cpp\n'
            'TEST args:  --packages-above rosidl_typesupport_fastrtps_c rosidl_typesupport_fastrtps_cpp\n'
            'ROS Distro: rolling\n'
            'Job: ci_launcher\n'
            'ci_launcher ran: https://ci.ros2.org/job/ci_launcher/20109\n'
            '* Linux [![Build Status](http://ci.ros2.org/buildStatus/icon?job=ci_linux&build=30138)](http://ci.ros2.org/job/ci_linux/30138/)\n'
            '* Linux-aarch64 [![Build Status](http://ci.ros2.org/buildStatus/icon?job=ci_linux-aarch64&build=22870)](http://ci.ros2.org/job/ci_linux-aarch64/22870/)\n'
            '* Linux-rhel [![Build Status](http://ci.ros2.org/buildStatus/icon?job=ci_linux-rhel&build=9984)](http://ci.ros2.org/job/ci_linux-rhel/9984/)\n'
            '* Windows [![Build Status](http://ci.ros2.org/buildStatus/icon?job=ci_windows&build=29019)](http://ci.ros2.org/job/ci_windows/29019/)\n'
        )

        mock_comment = MagicMock()
        mock_comment.id = 5349716978
        mock_comment.html_url = 'https://github.com/ros2/rosidl_typesupport_fastrtps/pull/160#issuecomment-5349716978'
        mock_comment.body = sample_comment_body

        ci_info = parse_ci_comment(mock_comment)
        self.assertEqual(ci_info.comment_id, 5349716978)
        self.assertEqual(ci_info.gist_hash, '2544c58104da04ad79b07646404951c1')
        self.assertIsNone(ci_info.branch_name)
        self.assertEqual(ci_info.launcher_build, 20109)
        self.assertEqual(len(ci_info.jobs), 4)

        self.assertEqual(ci_info.jobs[0].platform, 'Linux')
        self.assertEqual(ci_info.jobs[0].job_name, 'ci_linux')
        self.assertEqual(ci_info.jobs[0].build_num, 30138)

    def test_parse_ci_comment_branch(self):
        sample_branch_comment = (
            'Branch: test_feature_branch\n'
            'BUILD args:  --packages-up-to rclcpp\n'
            'TEST args:  --packages-select rclcpp\n'
            'ROS Distro: rolling\n'
            'Job: ci_launcher\n'
            'ci_launcher ran: https://ci.ros2.org/job/ci_launcher/19000\n'
            '* Linux [![Build Status](http://ci.ros2.org/buildStatus/icon?job=ci_linux&build=28000)](http://ci.ros2.org/job/ci_linux/28000/)\n'
        )

        mock_comment = MagicMock()
        mock_comment.id = 12345
        mock_comment.html_url = 'https://github.com/ros2/rclcpp/pull/100#issuecomment-12345'
        mock_comment.body = sample_branch_comment

        ci_info = parse_ci_comment(mock_comment)
        self.assertIsNone(ci_info.gist_url)
        self.assertIsNone(ci_info.gist_hash)
        self.assertEqual(ci_info.branch_name, 'test_feature_branch')
        self.assertEqual(ci_info.launcher_build, 19000)
        self.assertEqual(len(ci_info.jobs), 1)
        self.assertEqual(ci_info.jobs[0].job_name, 'ci_linux')
        self.assertEqual(ci_info.jobs[0].build_num, 28000)

    def test_update_comment_body(self):
        sample_comment_body = (
            'Pulls: ros2/rosidl_typesupport_fastrtps#160\n'
            'Gist: https://gist.githubusercontent.com/wjwwood/2544c58104da04ad79b07646404951c1/raw/f2dd2f3ec0e144c7a903a82318fe0419a5fa857a/ros2.repos\n'
            'BUILD args:  --packages-above-and-dependencies rosidl_typesupport_fastrtps_c rosidl_typesupport_fastrtps_cpp\n'
            'TEST args:  --packages-above rosidl_typesupport_fastrtps_c rosidl_typesupport_fastrtps_cpp\n'
            'ROS Distro: rolling\n'
            'Job: ci_launcher\n'
            'ci_launcher ran: https://ci.ros2.org/job/ci_launcher/20109\n'
            '* Linux [![Build Status](http://ci.ros2.org/buildStatus/icon?job=ci_linux&build=30138)](http://ci.ros2.org/job/ci_linux/30138/)\n'
            '* Linux-aarch64 [![Build Status](http://ci.ros2.org/buildStatus/icon?job=ci_linux-aarch64&build=22870)](http://ci.ros2.org/job/ci_linux-aarch64/22870/)\n'
            '* Linux-rhel [![Build Status](http://ci.ros2.org/buildStatus/icon?job=ci_linux-rhel&build=9984)](http://ci.ros2.org/job/ci_linux-rhel/9984/)\n'
            '* Windows [![Build Status](http://ci.ros2.org/buildStatus/icon?job=ci_windows&build=29019)](http://ci.ros2.org/job/ci_windows/29019/)\n'
        )

        mock_comment = MagicMock()
        mock_comment.id = 5349716978
        mock_comment.html_url = 'https://github.com/ros2/rosidl_typesupport_fastrtps/pull/160#issuecomment-5349716978'
        mock_comment.body = sample_comment_body

        ci_info = parse_ci_comment(mock_comment)

        results = {
            'ci_linux': BuildResult(job_name='ci_linux', build_num=30141, status='SUCCESS'),
            'ci_linux-aarch64': BuildResult(job_name='ci_linux-aarch64', build_num=22875, status='SUCCESS'),
            'ci_linux-rhel': BuildResult(job_name='ci_linux-rhel', build_num=9987, status='SUCCESS'),
            'ci_windows': BuildResult(job_name='ci_windows', build_num=29041, status='SUCCESS'),
        }

        updated_body = update_comment_body(ci_info.body, ci_info.jobs, results)

        expected_body = (
            'Pulls: ros2/rosidl_typesupport_fastrtps#160\n'
            'Gist: https://gist.githubusercontent.com/wjwwood/2544c58104da04ad79b07646404951c1/raw/f2dd2f3ec0e144c7a903a82318fe0419a5fa857a/ros2.repos\n'
            'BUILD args:  --packages-above-and-dependencies rosidl_typesupport_fastrtps_c rosidl_typesupport_fastrtps_cpp\n'
            'TEST args:  --packages-above rosidl_typesupport_fastrtps_c rosidl_typesupport_fastrtps_cpp\n'
            'ROS Distro: rolling\n'
            'Job: ci_launcher\n'
            'ci_launcher ran: https://ci.ros2.org/job/ci_launcher/20109\n'
            '* Linux [![Build Status](http://ci.ros2.org/buildStatus/icon?job=ci_linux&build=30141)](http://ci.ros2.org/job/ci_linux/30141/)\n'
            '* Linux-aarch64 [![Build Status](http://ci.ros2.org/buildStatus/icon?job=ci_linux-aarch64&build=22875)](http://ci.ros2.org/job/ci_linux-aarch64/22875/)\n'
            '* Linux-rhel [![Build Status](http://ci.ros2.org/buildStatus/icon?job=ci_linux-rhel&build=9987)](http://ci.ros2.org/job/ci_linux-rhel/9987/)\n'
            '* Windows [![Build Status](http://ci.ros2.org/buildStatus/icon?job=ci_windows&build=29041)](http://ci.ros2.org/job/ci_windows/29041/)\n'
        )

        self.assertEqual(updated_body, expected_body)

    def test_find_latest_job_build_by_upstream_cause(self):
        session = MagicMock()

        def mock_get(url, timeout=5):
            resp = MagicMock()
            resp.status_code = 200
            if 'ci_linux/api/json' in url:
                resp.json.return_value = {
                    'builds': [{'number': 30138}, {'number': 30141}]
                }
            elif 'ci_linux/30138/api/json' in url:
                resp.json.return_value = {
                    'building': False,
                    'result': 'FAILURE',
                    'actions': [{
                        'causes': [{
                            'upstreamProject': 'ci_launcher',
                            'upstreamBuild': 20109
                        }]
                    }]
                }
            elif 'ci_linux/30141/api/json' in url:
                resp.json.return_value = {
                    'building': False,
                    'result': 'SUCCESS',
                    'actions': [{
                        'causes': [{
                            'upstreamProject': 'ci_launcher',
                            'upstreamBuild': 20109
                        }]
                    }]
                }
            else:
                resp.status_code = 404
            return resp

        session.get.side_effect = mock_get

        res = find_latest_job_build(
            session=session,
            ci_server='https://ci.ros2.org',
            job_name='ci_linux',
            start_build_num=30138,
            launcher_build=20109,
        )

        self.assertEqual(res.build_num, 30141)
        self.assertEqual(res.status, 'SUCCESS')
        self.assertFalse(res.is_queued)

    def test_find_latest_job_build_by_branch(self):
        session = MagicMock()

        def mock_get(url, timeout=5):
            resp = MagicMock()
            resp.status_code = 200
            if 'ci_linux/api/json' in url:
                resp.json.return_value = {
                    'builds': [{'number': 28000}, {'number': 28005}]
                }
            elif 'ci_linux/28000/api/json' in url:
                resp.json.return_value = {
                    'building': False,
                    'result': 'ABORTED',
                    'actions': [{
                        'parameters': [{'name': 'CI_BRANCH_TO_TEST', 'value': 'my_custom_branch'}]
                    }]
                }
            elif 'ci_linux/28005/api/json' in url:
                resp.json.return_value = {
                    'building': False,
                    'result': 'SUCCESS',
                    'actions': [{
                        'parameters': [{'name': 'CI_BRANCH_TO_TEST', 'value': 'my_custom_branch'}]
                    }]
                }
            else:
                resp.status_code = 404
            return resp

        session.get.side_effect = mock_get

        res = find_latest_job_build(
            session=session,
            ci_server='https://ci.ros2.org',
            job_name='ci_linux',
            start_build_num=28000,
            branch_name='my_custom_branch',
        )

        self.assertEqual(res.build_num, 28005)
        self.assertEqual(res.status, 'SUCCESS')

    def test_find_latest_job_queued(self):
        session = MagicMock()

        def mock_get(url, timeout=5):
            resp = MagicMock()
            resp.status_code = 200
            if 'ci_windows/api/json' in url:
                resp.json.return_value = {
                    'builds': [{'number': 29019}]
                }
            elif 'ci_windows/29019/api/json' in url:
                resp.json.return_value = {
                    'building': False,
                    'result': 'FAILURE',
                    'actions': []
                }
            elif 'queue/api/json' in url:
                resp.json.return_value = {
                    'items': [{
                        'id': 221,
                        'task': {'name': 'ci_windows'},
                        'causes': [{
                            'upstreamProject': 'ci_launcher',
                            'upstreamBuild': 20109
                        }],
                        'params': '\nCI_ROS2_REPOS_URL=https://gist.githubusercontent.com/user/2544c58104da04ad79b07646404951c1/raw/.../ros2.repos'
                    }]
                }
            else:
                resp.status_code = 404
            return resp

        session.get.side_effect = mock_get

        res = find_latest_job_build(
            session=session,
            ci_server='https://ci.ros2.org',
            job_name='ci_windows',
            start_build_num=29019,
            launcher_build=20109,
            gist_hash='2544c58104da04ad79b07646404951c1',
        )

        self.assertTrue(res.is_queued)
        self.assertEqual(res.status, 'QUEUED')
        self.assertEqual(res.queue_item_id, 221)
        self.assertEqual(res.queue_position, 1)


if __name__ == '__main__':
    unittest.main()
