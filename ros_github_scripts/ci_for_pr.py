# Copyright 2021 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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

import argparse
import logging
import os
import re
from typing import Dict
from typing import List
from typing import Optional

import github
from github import Github, InputFileContent
import requests
import yaml

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DEFAULT_JOB = 'ci_launcher'
REPOS_URL = 'https://raw.githubusercontent.com/ros2/ros2/{}/ros2.repos'
DEFAULT_TARGET = 'rolling'
CI_SERVER = 'https://ci.ros2.org'
SERVER_RETRIES = 2

ROS_DISTRO_TO_UBUNTU_DISTRO = {
    'noetic': 'focal',
    'humble': 'jammy',
    'iron': 'jammy',
    'jazzy': 'noble',
    'kilted': 'noble',
    'rolling': ''  # use default
}

ROS_DISTRO_TO_RHEL_DISTRO = {
    'humble': '8',
    'iron': '9',
    'jazzy': '9',
    'kilted': '9',
    'rolling': ''  # use default
}

def panic(msg: str) -> None:
    raise RuntimeError('Panic: ' + msg)


def fetch_repos(target_release: str) -> dict:
    """Fetch the repos file for the specific release."""
    branch = target_release
    repos_response = requests.get(REPOS_URL.format(branch))

    repos_text = repos_response.text
    toplevel_dict = yaml.safe_load(repos_text)
    return toplevel_dict['repositories']


def create_ci_gist(
    github_instance: Github,
    pulls: List[github.PullRequest.PullRequest],
    target_release: str
) -> github.Gist.Gist:
    """Create gist for the list of pull requests."""
    logger.info('Creating ros2.repos Gist for PRs')
    master_repos = fetch_repos(target_release)
    shortnames = []
    for github_pr in pulls:
        pr_ref = github_pr.head.ref
        pr_repo = github_pr.head.repo.full_name
        base_repo = github_pr.base.repo.full_name

        shortnames.append(f'{base_repo}#{github_pr.number}')

        # Remove the existing repository from the list
        repo_entry = master_repos.pop(base_repo, None)
        if repo_entry:
            if repo_entry['type'] != 'git':
                panic('Chosen repository is not git-based')
        else:
            logger.warn(
                f'PR Repository "{pr_repo}" not found in ros2.repos, be aware that this is not '
                'part of the default build set and is not guaranteed to work.')

        # Add the same package from the PR's repository to the list
        master_repos[pr_repo] = {
            'type': 'git',
            'url': 'https://github.com/{}.git'.format(pr_repo),
            'version': pr_ref
        }

    yaml_out = yaml.dump({'repositories': master_repos}, default_flow_style=False)

    input_file = InputFileContent(content=yaml_out)
    gist = github_instance.get_user().create_gist(
        public=True,
        files={'ros2.repos': input_file},
        description='CI input for PR {}'.format(' '.join(shortnames)))
    return gist


def fetch_user_pulls(
    github_instance: Github
) -> github.PaginatedList.PaginatedList:
    """
    Return a list of github.PullRequest objects for the user associated with the github API token.

    Panic if none are found.
    """
    user = github_instance.get_user()
    if not user:
        panic('Github Instance not associated with an authenticated user')
    if not user.login:
        panic("Couldn't get user login to search for PRs")

    prs = github_instance.search_issues(
        'is:open is:pr author:{} archived:false'.format(user.login))
    if not prs.totalCount:
        panic('It seems that you have no open PRs')

    return prs


def print_format_issue(issue: github.Issue.Issue) -> str:
    return '{}#{}'.format(issue.repository.full_name, issue.number)


def prompt_pull_selection(
    pulls: github.PaginatedList.PaginatedList
) -> List[github.PullRequest.PullRequest]:
    """
    Prompt user to select from the list of their authored pull requests.

    Return the list of chosen PRs.
    """
    choices: Dict[int, github.Issue.Issue] = {}
    texts = []
    while True:
        print('\n>>> Choose a PR to add to Gist <<<\n')
        for i, option in enumerate(pulls):
            if i in choices:
                continue
            print('[{}]: {}: {}'.format(i, print_format_issue(option), option.title))
        print('')
        if len(choices):
            print('Chosen: [{}]'.format(', '.join(
                print_format_issue(issue) for issue in choices.values())))

        choice = input('Choose PR to add to Gist [leave empty to finish]> ')

        if not choice:
            if not len(choices):
                print('You must choose at least one PR')
            else:
                break

        try:
            choice_index = int(choice)
            current_choice = pulls[choice_index]
            texts.append(print_format_issue(current_choice))
            choices[choice_index] = current_choice
        except (ValueError, IndexError):
            print('{} is not a valid choice'.format(choice))

    return (texts, [issue.as_pull_request() for issue in choices.values()])


def validate_and_fetch_pull_list(
    github_instance: Github, pull_list: List[str]
) -> List[github.PullRequest.PullRequest]:
    """Fetch GitHub pull requests given the "org/repo#N" string input specifier format."""
    github_url_re = re.compile(r'https://github.com/(.*)/(.*)/pull/([0-9]+)')
    repos_to_prs = {}
    for pull in pull_list:
        url_match = re.match(github_url_re, pull)
        if url_match is not None:
            repo = '/'.join([url_match[1], url_match[2]])
            pull_number_str = url_match[3]
        else:
            if pull.count('#') != 1:
                panic("Pull request descriptor doesn't match org/repo#number format: {}".format(pull))
            repo, pull_number_str = pull.split('#')

        try:
            pull_number = int(pull_number_str)
        except TypeError:
            panic("Pull request number '{}' isn't a number...".format(pull_number_str))

        if repo in repos_to_prs:
            panic(f"Can't simultaneously test multiple PRs for the same repository ({repo})")

        repos_to_prs[repo] = pull_number

    return_prs = []
    for repo_name, pull_number in repos_to_prs.items():
        gh_repo = github_instance.get_repo(repo_name)
        return_prs.append(gh_repo.get_pull(pull_number))

    return return_prs


def format_ci_details(
    *,
    gist_url: Optional[str],
    extra_build_args: str,
    extra_test_args: str,
    target_release: str,
    target_pulls: Optional[List[str]],
    branch_name: Optional[str],
) -> str:
    details = []
    if target_pulls:
        details.append(f"Pulls: {', '.join(target_pulls)}")
    if gist_url:
        details.append(f'Gist: {gist_url}')
    if branch_name:
        details.append(f'Branch: {branch_name}')
    return '\n'.join(details + [
        f'BUILD args: {extra_build_args}',
        f'TEST args: {extra_test_args}',
        f'ROS Distro: {target_release}',
        'Job: {}'.format(DEFAULT_JOB),
    ])


def run_jenkins_build(
    *,
    build_args: str,
    test_args: str,
    gist_url: Optional[str],
    branch_name: Optional[str],
    github_login: str,
    github_token: str,
    target_release: str,
) -> str:
    """
    Run a ci_launcher build for the selected packages, with the given gist as sources.

    :returns: Text containing markdown of the build status badges for the launched build.
    """
    assert gist_url or branch_name, 'Either a gist URL or a branch name must be provided'

    # intentionally raises key_error on unknown distro
    ubuntu_distro = ROS_DISTRO_TO_UBUNTU_DISTRO[target_release]
    rhel_distro = ROS_DISTRO_TO_RHEL_DISTRO[target_release]

    from jenkinsapi.jenkins import Jenkins
    logger.info('Connecting to Jenkins server')
    jenkins = Jenkins(CI_SERVER, username=github_login, password=github_token, use_crumb=True)
    retries_remaining = SERVER_RETRIES
    build_job = None
    while retries_remaining >= 0:
        try:
            logger.info(f'Fetching build job info for "{DEFAULT_JOB}"')
            build_job = jenkins[DEFAULT_JOB]
            break
        except requests.exceptions.ConnectionError as e:
            logger.warn(f'Failed to fetch job info, retries remaining: {retries_remaining}')
            retries_remaining -= 1
            if retries_remaining < 0:
                raise e
    param_spec = build_job.get_params()

    # start by taking all the default parameters
    build_params = {
        p['name']: p['defaultParameterValue']['value']
        for p in param_spec
    }
    # augment with specific values for this PR
    if gist_url:
        build_params['CI_ROS2_REPOS_URL'] = gist_url
    if branch_name:
        build_params['CI_BRANCH_TO_TEST'] = branch_name
    build_params['CI_ROS_DISTRO'] = target_release
    build_params['CI_BUILD_ARGS'] += f' {build_args}'
    build_params['CI_TEST_ARGS'] += f' {test_args}'
    if ubuntu_distro:
        build_params['CI_UBUNTU_DISTRO'] = ubuntu_distro
    if rhel_distro:
        build_params['CI_EL_RELEASE'] = rhel_distro

    # Start the build and wait until it is completed. ci_launcher exits immediately after
    # queuing the child builds, so this should only take a few seconds
    logger.info(f'Invoking build job with params: {build_params}')
    queue_item = build_job.invoke(block=True, build_params=build_params)
    logger.info('Build complete, fetching console output')
    build_instance = queue_item.get_build()
    console_output = build_instance.get_console()
    console_lines = console_output.split('\n')
    """
    # Example output (note that the build badges are on markdown list lines starting with *):

    Started by user Example User
    Running as SYSTEM
    Building on master in workspace /var/lib/jenkins/jobs/ci_launcher/workspace
    * Linux [![Build Status](http://ci.ros2.org/buildStatus/icon?job=ci_linux&build=13344)](http://ci.ros2.org/job/ci_linux/13344/)
    * Linux-aarch64 [![Build Status](http://ci.ros2.org/buildStatus/icon?job=ci_linux-aarch64&build=8272)](http://ci.ros2.org/job/ci_linux-aarch64/8272/)
    * macOS [![Build Status](http://ci.ros2.org/buildStatus/icon?job=ci_osx&build=11074)](http://ci.ros2.org/job/ci_osx/11074/)
    * Windows [![Build Status](http://ci.ros2.org/buildStatus/icon?job=ci_windows&build=13396)](http://ci.ros2.org/job/ci_windows/13396/)
    Triggering a new build of ci_linux
    Triggering a new build of ci_linux-aarch64
    Triggering a new build of ci_osx
    Triggering a new build of ci_windows
    Finished: SUCCESS
    """  # NOQA
    link_lines = [line for line in console_lines if line.startswith('*')]

    info_lines = [f'{DEFAULT_JOB} ran: {build_instance.baseurl}'] + link_lines
    return '\n'.join(info_lines)


def comment_results(
    send_to_github: bool, contents: str, pulls: List[github.PullRequest.PullRequest]
) -> None:
    """
    Print final info about the build and optionally create as a comment on GitHub.

    :param send_to_github: If True, automatically create the comment on each PR
    :param contents: All collected information about the build in question
    :param pulls: List of GitHub Pull Requests being built
    """
    if send_to_github:
        for pull in pulls:
            logger.info(f'Posting info as comment on {pull.html_url}')
            pull.create_issue_comment(body=contents)
        print('\n>>> AUTO-COMMENTED BELOW CONTENT ON ALL PRS <<<')
    else:
        print('\n>>> COPY-PASTE BELOW CONTENT TO PRS <<<')
    print(contents)


def parse_args():
    parser = argparse.ArgumentParser(
        description='Generate a CI build request for Pull Request(s)',
        add_help=False)

    select_group = parser.add_argument_group(
        title='change selection',
        description='Select the PRs or branch to test.')
    select_group.add_argument(
        '--branch', type=str,
        help='Branch to test across the repositories in the .repos files that have it. Corresponds '
             'to the CI_BRANCH_TO_TEST ci.ros2.org parameter, which means that this branch gets '
             'merged into the distro target branch for testing. When using this option with '
             '--comment, the list of PRs to comment on must be specified using the --pulls or '
             '--interactive option.')
    pulls_group = select_group.add_mutually_exclusive_group()
    pulls_group.add_argument(
        '-p', '--pulls', type=str, nargs='+',
        help='Space-separated list of pull requests to process, in format ORG/REPO#PULLNUMBER '
             '(e.g. ros2/rclpy#353) or https://github.com/ORG/REPO/pull/PULLNUMBER. When using '
             'the --branch and --comment options, comments will be posted on these PRs.')
    pulls_group.add_argument(
        '-i', '--interactive', action='store_true',
        help='Prompt me to select my pull requests from a list, instead of specifying. When using '
            'the --branch and --comment options, comments will be posted on these PRs.')

    # Create a group for these so that they are displayed below the 'change selection' group
    group = parser.add_argument_group(title='other options')
    group.add_argument('-h', '--help', action='help')
    group.add_argument(
        '-k', '--packages', type=str, nargs='+', default=None,
        help='Space-separated list of packages to be built and tested.')
    group.add_argument(
        '-t', '--target', type=str, default=DEFAULT_TARGET,
        help='Target distro for PRs; assumes {}.'.format(DEFAULT_TARGET))
    group.add_argument(
        '-b', '--build', action='store_true',
        help='Automatically start the build job on Jenkins and print out the resulting badges. '
             'Only works if your GitHub user is authorized to run builds.')
    group.add_argument(
        '-c', '--comment', action='store_true',
        help='Automatically post a comment on the PRs being built, containing relevant content.')
    group.add_argument(
        '--only-fixes-test', action='store_true',
        help='The fix being tested only fixes a test, which causes CI to be shorter')
    group.add_argument(
        '--colcon-build-args', type=str, default='',
        help='Arbitrary colcon arguments to specify to build; must be specified with -b')
    group.add_argument(
        '--colcon-test-args', type=str, default='',
        help='Arbitrary colcon arguments to specify to test; must be specified with -b')
    group.add_argument(
        '--cmake-args', type=str, default='',
        help='Arbitrary CMake arguments to specify to build; Each argument shall be prefixed'
             ' with -D. CMake arguments shall only be used with -b --build option.')
    return parser.parse_args()


def main():
    parsed = parse_args()

    github_access_token = os.environ.get('GITHUB_ACCESS_TOKEN')
    if not github_access_token:
        github_access_token = os.environ.get('GITHUB_TOKEN')
    if not github_access_token:
        panic('Neither environment variable GITHUB_ACCESS_TOKEN nor GITHUB_TOKEN are set')
    github_instance = Github(github_access_token)

    branch_name = parsed.branch
    pull_texts = parsed.pulls
    chosen_pulls = []
    if parsed.interactive:
        all_user_pulls = fetch_user_pulls(github_instance)
        pull_texts, chosen_pulls = prompt_pull_selection(all_user_pulls)
    elif parsed.pulls:
        chosen_pulls = validate_and_fetch_pull_list(github_instance, parsed.pulls)

    # Have to select PRs when not providing branch
    if not branch_name and not chosen_pulls:
        panic(
            'When not using --branch, you must select PRs either using --interactive '
            'or by providing them using --pulls')
    # Have to select PRs when providing branch and enabling comments
    if branch_name and parsed.comment and not chosen_pulls:
        panic(
            'When using --branch and --comment, you must select PRs to comment on either using '
            '--interactive or by providing them using --pulls')

    # Only create a gist if we specified PRs and not a branch
    # We can set both options for ci.ros2.org, but it does not make sense if we select PRs
    gist_url = None
    if chosen_pulls and not branch_name:
        gist = create_ci_gist(github_instance, chosen_pulls, parsed.target)
        gist_url = gist.files['ros2.repos'].raw_url

    if not parsed.build and \
            (parsed.colcon_build_args or parsed.colcon_test_args or parsed.cmake_args):
        panic('colcon build, cmake or test args can only be specified when doing a build')

    extra_build_args = parsed.colcon_build_args
    extra_test_args = parsed.colcon_test_args
    if parsed.packages:
        packages_changed = ' '.join(parsed.packages)
        if parsed.only_fixes_test:
            extra_build_args += f' --packages-up-to {packages_changed}'
            extra_test_args += f' --packages-select {packages_changed}'
        else:
            extra_build_args += f' --packages-above-and-dependencies {packages_changed}'
            extra_test_args += f' --packages-above {packages_changed}'

    if parsed.cmake_args:
        extra_build_args += f' --cmake-args {parsed.cmake_args}'

    comment_texts = []
    comment_texts.append(
        format_ci_details(
            gist_url=gist_url,
            extra_build_args=extra_build_args,
            extra_test_args=extra_test_args,
            target_release=parsed.target,
            target_pulls=pull_texts,
            branch_name=branch_name))
    if parsed.build:
        user = github_instance.get_user().login
        comment_texts.append(
            run_jenkins_build(
                build_args=extra_build_args,
                test_args=extra_test_args,
                gist_url=gist_url,
                branch_name=branch_name,
                github_login=user,
                github_token=github_access_token,
                target_release=parsed.target))

    comment_results(parsed.comment, '\n'.join(comment_texts), chosen_pulls)


if __name__ == '__main__':
    main()
