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

import argparse
import dataclasses
import logging
import os
import re
import sys
import textwrap
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

import github
from github import Github
import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DEFAULT_CI_SERVER = 'https://ci.ros2.org'
DEFAULT_LAUNCHER_JOB = 'ci_launcher'


@dataclasses.dataclass
class JobReference:
    platform: str
    job_name: str
    build_num: int
    badge_url: str
    job_url: str
    full_line: str


@dataclasses.dataclass
class CICommentInfo:
    comment_id: int
    html_url: str
    body: str
    gist_url: Optional[str]
    gist_hash: Optional[str]
    branch_name: Optional[str]
    launcher_build: Optional[int]
    jobs: List[JobReference]


@dataclasses.dataclass
class BuildResult:
    job_name: str
    build_num: Optional[int]
    status: str
    is_queued: bool = False
    queue_item_id: Optional[int] = None
    queue_position: Optional[int] = None


def parse_comment_target(target: str) -> Tuple[str, Optional[int], Optional[int]]:
    """
    Parse a comment or PR target string into (repo_full_name, pr_number, comment_id).

    Supported formats:
    - https://github.com/org/repo/pull/123#issuecomment-456789
    - https://github.com/org/repo/issues/123#issuecomment-456789
    - https://github.com/org/repo/issues/comments/456789
    - https://github.com/org/repo/pull/123
    - org/repo#123
    """
    # 1. Full issuecomment anchor URL
    m = re.search(
        r'github\.com/(?P<org>[^/]+)/(?P<repo>[^/#]+)/(?:pull|issues)/(?P<pr>\d+)#issuecomment-(?P<cid>\d+)',
        target)
    if m:
        repo = f"{m.group('org')}/{m.group('repo')}"
        return repo, int(m.group('pr')), int(m.group('cid'))

    # 2. Standalone issue comment URL
    m = re.search(
        r'github\.com/(?P<org>[^/]+)/(?P<repo>[^/#]+)/issues/comments/(?P<cid>\d+)',
        target)
    if m:
        repo = f"{m.group('org')}/{m.group('repo')}"
        return repo, None, int(m.group('cid'))

    # 3. Pull request URL
    m = re.search(
        r'github\.com/(?P<org>[^/]+)/(?P<repo>[^/#]+)/pull/(?P<pr>\d+)',
        target)
    if m:
        repo = f"{m.group('org')}/{m.group('repo')}"
        return repo, int(m.group('pr')), None

    # 4. org/repo#pr shorthand
    m = re.search(
        r'^(?P<org>[a-zA-Z0-9_\-]+)/(?P<repo>[a-zA-Z0-9_\-]+)#(?P<pr>\d+)$',
        target.strip())
    if m:
        repo = f"{m.group('org')}/{m.group('repo')}"
        return repo, int(m.group('pr')), None

    raise ValueError(f"Could not parse target comment or PR reference from: '{target}'")


def fetch_target_comment(
    github_instance: Github,
    repo_name: str,
    pr_num: Optional[int],
    comment_id: Optional[int]
) -> github.IssueComment.IssueComment:
    """Fetch the specific IssueComment object from GitHub."""
    gh_repo = github_instance.get_repo(repo_name)

    if comment_id:
        if pr_num:
            issue = gh_repo.get_issue(pr_num)
            return issue.get_comment(comment_id)
        # Direct lookup via PyGithub using issue comment
        issue_comments = gh_repo.get_issues_comments()
        for c in issue_comments:
            if c.id == comment_id:
                return c
        raise RuntimeError(f'Comment ID {comment_id} not found in {repo_name}')

    if pr_num:
        issue = gh_repo.get_issue(pr_num)
        comments = list(issue.get_comments())
        # Find the latest comment with CI job badges
        for c in reversed(comments):
            if 'ci_launcher' in c.body or 'ci_linux' in c.body:
                logger.info(f'Found latest CI comment #{c.id} on {repo_name}#{pr_num}')
                return c
        raise RuntimeError(f'No CI comment found on {repo_name}#{pr_num}')

    raise ValueError('Must provide either a comment ID or a PR number')


def parse_ci_comment(comment: github.IssueComment.IssueComment) -> CICommentInfo:
    """Parse the body of a CI comment to extract Gist, Branch, launcher run, and platform job lines."""
    body = comment.body

    gist_url = None
    gist_hash = None
    m_gist = re.search(r'Gist:\s*(?P<url>https://gist\.githubusercontent\.com/[^\s]+)', body)
    if m_gist:
        gist_url = m_gist.group('url')
        parts = urlparse(gist_url).path.strip('/').split('/')
        if len(parts) >= 2:
            gist_hash = parts[1]

    branch_name = None
    m_branch = re.search(r'Branch:\s*(?P<branch>[^\s]+)', body)
    if m_branch:
        branch_name = m_branch.group('branch')

    launcher_build = None
    m_launch = re.search(
        r'(?:ci_launcher ran:\s*https?://[^/\s]+/job/ci_launcher/|ci_launcher/)(?P<num>\d+)',
        body)
    if m_launch:
        launcher_build = int(m_launch.group('num'))

    job_pattern = re.compile(
        r'^(?P<line>\s*\*\s*(?P<platform>[^\[\n]+?)\s*\[!\[Build Status\]\('
        r'(?P<badge_url>https?://[^)]*?job=(?P<job_name>[a-zA-Z0-9_\-]+)&build=(?P<build_num>\d+)[^)]*)\)'
        r'\]\((?P<job_url>https?://[^)]+)\))',
        re.MULTILINE)

    jobs = []
    for m in job_pattern.finditer(body):
        jobs.append(JobReference(
            platform=m.group('platform').strip(),
            job_name=m.group('job_name'),
            build_num=int(m.group('build_num')),
            badge_url=m.group('badge_url'),
            job_url=m.group('job_url'),
            full_line=m.group('line'),
        ))

    if not jobs:
        raise RuntimeError(f'No platform CI job references found in comment #{comment.id}')

    return CICommentInfo(
        comment_id=comment.id,
        html_url=comment.html_url,
        body=body,
        gist_url=gist_url,
        gist_hash=gist_hash,
        branch_name=branch_name,
        launcher_build=launcher_build,
        jobs=jobs,
    )


def get_jenkins_session(
    ci_server: str,
    username: Optional[str] = None,
    token: Optional[str] = None
) -> requests.Session:
    """Create an authenticated requests Session with Jenkins crumb if enabled."""
    session = requests.Session()
    if username and token:
        session.auth = (username, token)

    try:
        r = session.get(f'{ci_server.rstrip("/")}/crumbIssuer/api/json', timeout=5)
        if r.status_code == 200:
            crumb_data = r.json()
            session.headers.update({crumb_data['crumbRequestField']: crumb_data['crumb']})
            logger.debug('Obtained Jenkins crumb.')
    except Exception as e:
        logger.debug(f'Crumb issuer not available: {e}')

    return session


def find_latest_job_build(
    session: requests.Session,
    ci_server: str,
    job_name: str,
    start_build_num: int,
    launcher_build: Optional[int] = None,
    gist_hash: Optional[str] = None,
    branch_name: Optional[str] = None,
) -> BuildResult:
    """
    Search Jenkins for restarted builds of a specific job associated with the launcher run or test parameters.

    Discrimination Methodology and Core Assumptions:
    1. Primary Lineage — `ci_launcher` Upstream Cause:
       When Jenkins automatically reschedules an interrupted build (e.g. following a worker runner
       disconnect or agent node preemption), the rescheduled build maintains the exact same
       UpstreamCause (`upstreamProject: 'ci_launcher'`, `upstreamBuild: <launcher_id>`).
       Matching `upstreamBuild == launcher_build` is the primary and definitive signal that a build
       is a direct continuation/restart of that CI launcher invocation.
    2. Code / Test Failures vs. Infrastructure Restarts:
       When a build fails legitimately due to code errors, compiler warnings, or test assertion
       failures, Jenkins completes the build with FAILURE or UNSTABLE and does NOT automatically
       schedule another build. In this scenario, only `start_build_num` exists for that launcher run.
       Because the latest matching build number equals the initial build number, the tool concludes
       that no restart occurred and leaves the PR comment unchanged.
    3. Secondary / Fallback Parameter Matching:
       For branch-based testing (`CI_BRANCH_TO_TEST = branch_name`) or Gist-based testing
       (`CI_ROS2_REPOS_URL = ...<gist_hash>...`), parameter matching provides secondary verification
       when inspecting queued items or if the launcher ID was not present in the comment.
    4. Isolation from Subsequent Fresh CI Invocations:
       Each fresh CI invocation initiated via `ros-ci-for-pr` runs a separate `ci_launcher` build
       (and generates a distinct Gist if testing PRs). Because candidate builds are matched
       against the specific launcher run ID and test parameters of the target comment, newer
       independent CI runs are not conflated with restarted builds of the target run.

    Step-by-step process:
    1. Query the Jenkins REST API for the build history of the target platform job
       (e.g., `ci_linux`, `ci_linux-aarch64`, `ci_windows`, `ci_linux-rhel`).
    2. Filter builds to examine only those with a build number greater than or equal to
       `start_build_num` (the build originally listed in the PR comment).
    3. For each candidate build, fetch its build parameters and cause metadata:
       a. If `launcher_build` is known: check if `upstreamProject == 'ci_launcher'` and
          `upstreamBuild == launcher_build`.
       b. If `launcher_build` is not known: check if `CI_ROS2_REPOS_URL` contains `gist_hash`
          or if `CI_BRANCH_TO_TEST` matches `branch_name`.
       If any matching condition is satisfied, the build belongs to this CI invocation.
    4. If matching builds were found:
       Sort the matching builds in ascending order and select the highest (latest) build number
       and its execution result (e.g. 'SUCCESS', 'UNSTABLE', 'FAILURE', or 'RUNNING').
    5. If no executed builds were found beyond `start_build_num`:
       Query the active Jenkins queue endpoint (`/queue/api/json`) to check whether a restarted
       job is currently queued waiting for an available container or agent node executor.
       If found in the queue, record the queue item ID and position in line.
    6. Fall back to returning the initial build number with its current status.

    :param session: Authenticated requests session with Jenkins crumb header.
    :param ci_server: Base URL of the Jenkins CI server.
    :param job_name: Name of the Jenkins job (e.g. 'ci_linux').
    :param start_build_num: Initial build number from the GitHub comment.
    :param launcher_build: Upstream ci_launcher build number, if known.
    :param gist_hash: Unique identifier of the ros2.repos gist, if applicable.
    :param branch_name: Branch name under test, if applicable.
    :return: BuildResult containing the latest build number and status, or queue info.
    """
    server = ci_server.rstrip('/')

    # Check the build list on Jenkins
    url = f'{server}/job/{job_name}/api/json?tree=builds[number,result,building]'
    try:
        r = session.get(url, timeout=10)
        if r.status_code != 200:
            logger.warn(f'Failed to fetch builds for {job_name}: HTTP {r.status_code}')
            return BuildResult(job_name=job_name, build_num=start_build_num, status='UNKNOWN')
        build_list = r.json().get('builds', [])
    except Exception as e:
        logger.warn(f'Error fetching builds for {job_name}: {e}')
        return BuildResult(job_name=job_name, build_num=start_build_num, status='ERROR')

    matching_builds = []

    for b in build_list:
        b_num = b['number']
        if b_num < start_build_num:
            continue

        b_url = (
            f'{server}/job/{job_name}/{b_num}/api/json?'
            'tree=result,building,actions[causes[upstreamBuild,upstreamProject],'
            'parameters[name,value]]'
        )
        try:
            b_r = session.get(b_url, timeout=5)
            if b_r.status_code != 200:
                continue
            b_data = b_r.json()

            is_match = False
            for action in b_data.get('actions', []):
                # 1. Primary check: matching upstream ci_launcher build number
                if 'causes' in action and launcher_build is not None:
                    for cause in action['causes']:
                        if (cause.get('upstreamProject') == DEFAULT_LAUNCHER_JOB and
                                cause.get('upstreamBuild') == launcher_build):
                            is_match = True

                # 2. Secondary fallback check: matching parameters (Gist hash or branch name)
                if not is_match and 'parameters' in action:
                    for param in action['parameters']:
                        p_name = param.get('name')
                        p_val = param.get('value')
                        if isinstance(p_val, str):
                            if gist_hash and p_name == 'CI_ROS2_REPOS_URL' and gist_hash in p_val:
                                is_match = True
                            elif branch_name and p_name == 'CI_BRANCH_TO_TEST' and p_val == branch_name:
                                is_match = True

            if is_match:
                status = 'RUNNING' if b_data.get('building') else b_data.get('result', 'UNKNOWN')
                matching_builds.append((b_num, status))
        except Exception:
            continue

    if matching_builds:
        matching_builds.sort(key=lambda x: x[0])
        latest_num, latest_status = matching_builds[-1]
        return BuildResult(job_name=job_name, build_num=latest_num, status=latest_status)

    # If no builds found, check if it's currently waiting in the Jenkins queue
    try:
        q_r = session.get(f'{server}/queue/api/json', timeout=5)
        if q_r.status_code == 200:
            q_items = q_r.json().get('items', [])
            job_queue = [
                item for item in q_items
                if item.get('task', {}).get('name') == job_name
            ]
            for idx, item in enumerate(job_queue):
                is_queue_match = False
                # Check causes in queue item
                for cause in item.get('causes', []):
                    if (launcher_build is not None and
                            cause.get('upstreamProject') == DEFAULT_LAUNCHER_JOB and
                            cause.get('upstreamBuild') == launcher_build):
                        is_queue_match = True

                params_str = item.get('params', '')
                if gist_hash and gist_hash in params_str:
                    is_queue_match = True
                elif branch_name and f'CI_BRANCH_TO_TEST={branch_name}' in params_str:
                    is_queue_match = True

                if is_queue_match:
                    return BuildResult(
                        job_name=job_name,
                        build_num=None,
                        status='QUEUED',
                        is_queued=True,
                        queue_item_id=item.get('id'),
                        queue_position=idx + 1,
                    )
    except Exception as e:
        logger.debug(f'Error checking queue for {job_name}: {e}')

    return BuildResult(job_name=job_name, build_num=start_build_num, status='UNKNOWN')


def update_comment_body(
    original_body: str,
    jobs: List[JobReference],
    results: Dict[str, BuildResult]
) -> str:
    """Update job build numbers and links in the comment markdown."""
    updated_body = original_body

    for job in jobs:
        res = results.get(job.job_name)
        if not res or not res.build_num or res.build_num == job.build_num:
            continue

        old_build_str = str(job.build_num)
        new_build_str = str(res.build_num)

        # Replace build number in badge URL and target job URL
        new_badge_url = re.sub(
            rf'build={re.escape(old_build_str)}',
            f'build={new_build_str}',
            job.badge_url)
        new_job_url = re.sub(
            rf'/{re.escape(job.job_name)}/{re.escape(old_build_str)}/?',
            f'/{job.job_name}/{new_build_str}/',
            job.job_url)

        new_line = f'* {job.platform} [![Build Status]({new_badge_url})]({new_job_url})'
        updated_body = updated_body.replace(job.full_line, new_line)

    return updated_body


def parse_args():
    description = textwrap.dedent("""\
        Find restarted Jenkins CI jobs and optionally update the GitHub PR comment in-place.

        Why this tool is useful:
          During ROS 2 CI runs on ci.ros2.org, worker runner instances or swarm nodes can
          occasionally disconnect or encounter infrastructure hiccups (e.g. node restarts,
          lost workspace connections). When this occurs, Jenkins will automatically re-run or
          reschedule the interrupted job on another available executor.

          However, the CI status comment originally posted to GitHub by ros-ci-for-pr still
          points to the old, aborted or failed build number. In the past, maintainers had to
          manually navigate ci.ros2.org, search through the job history by inspecting upstream
          launcher runs or test parameters, locate the restarted build number, and manually edit
          the GitHub comment markdown.

          This tool automates that entire discovery workflow by parsing the GitHub comment,
          querying Jenkins for matching rescheduled builds or active queue items, and
          optionally editing the comment in-place with the updated links and status badges.

        How it discriminates between restarted jobs and code/test failures:
          1. Upstream Cause Lineage:
             When Jenkins automatically reschedules an interrupted build, the new build inherits
             the exact same upstream cause (the `ci_launcher` build ID) as the initial build.
             Matching the `ci_launcher` run ID is the primary and definitive signal that a build
             belongs to that specific CI invocation.
          2. Infrastructure Restarts vs. Legitimate Failures:
             When a build completes and fails legitimately due to code errors or test assertion
             failures, Jenkins does NOT automatically create a new downstream build. In that case,
             only the initial build number exists for that launcher run, so this tool recognizes
             that no restart occurred and leaves the GitHub comment unchanged.
          3. Gist and Branch Isolation:
             For PR testing (using Gists) or branch testing (using CI_BRANCH_TO_TEST), test
             parameters are also checked. Separate CI invocations use distinct launcher runs,
             ensuring fresh CI passes are never conflated with restarted builds.\
    """)

    epilog = textwrap.dedent("""\
        Examples:
          # Dry-run inspection using a full comment URL:
          ros-find-restarted-ci "https://github.com/ros2/rmw_implementation/pull/99#issuecomment-5349858725"

          # Inspect latest CI comment on a PR by shorthand reference:
          ros-find-restarted-ci ros2/rosidl_typesupport_fastrtps#160

          # Automatically update the GitHub comment in-place:
          ros-find-restarted-ci -u "https://github.com/ros2/rmw_implementation/pull/99"\
    """)

    parser = argparse.ArgumentParser(
        description=description,
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter)

    parser.add_argument(
        'target',
        type=str,
        help='GitHub comment URL, PR URL, or org/repo#pr shorthand '
             '(e.g. https://github.com/ros2/rosidl_typesupport_fastrtps/pull/160#issuecomment-5349716978 '
             'or ros2/rosidl_typesupport_fastrtps#160)')
    parser.add_argument(
        '--github-token',
        type=str,
        default=None,
        help='GitHub personal access token (defaults to GITHUB_ACCESS_TOKEN or GITHUB_TOKEN env var)')
    parser.add_argument(
        '--jenkins-url',
        type=str,
        default=DEFAULT_CI_SERVER,
        help='URL of the Jenkins CI server (default: %(default)s)')
    parser.add_argument(
        '--jenkins-user',
        type=str,
        default=None,
        help='Jenkins username (defaults to authenticated GitHub user)')
    parser.add_argument(
        '--jenkins-token',
        type=str,
        default=None,
        help='Jenkins API token or password (defaults to GitHub token)')
    parser.add_argument(
        '-u', '--update-comment',
        action='store_true',
        help='Automatically update the GitHub comment with restarted build links')
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose debug logging')

    return parser.parse_args()


def main():
    args = parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    github_token = args.github_token or os.environ.get('GITHUB_ACCESS_TOKEN') or os.environ.get('GITHUB_TOKEN')
    if not github_token:
        try:
            import subprocess
            github_token = subprocess.check_output('gh auth token', shell=True).decode().strip()
        except Exception:
            pass

    if not github_token:
        logger.error('No GitHub access token provided. Set GITHUB_TOKEN or provide --github-token.')
        sys.exit(1)

    gh = Github(github_token)
    current_user = None
    try:
        current_user = gh.get_user().login
    except Exception:
        pass

    jenkins_user = args.jenkins_user or current_user
    jenkins_token = args.jenkins_token or github_token

    try:
        repo_name, pr_num, comment_id = parse_comment_target(args.target)
    except ValueError as e:
        logger.error(str(e))
        sys.exit(1)

    logger.info(f'Target: repo={repo_name}, PR={pr_num}, comment_id={comment_id}')

    logger.info('Fetching comment from GitHub...')
    try:
        comment = fetch_target_comment(gh, repo_name, pr_num, comment_id)
        ci_info = parse_ci_comment(comment)
    except Exception as e:
        logger.error(f'Failed to fetch/parse CI comment: {e}')
        sys.exit(1)

    logger.info(f'Found CI comment with {len(ci_info.jobs)} jobs:')
    if ci_info.gist_url:
        logger.info(f'  Gist URL: {ci_info.gist_url}')
    if ci_info.branch_name:
        logger.info(f'  Branch: {ci_info.branch_name}')
    logger.info(f'  Launcher Build: {ci_info.launcher_build}')

    session = get_jenkins_session(args.jenkins_url, username=jenkins_user, token=jenkins_token)

    results: Dict[str, BuildResult] = {}
    has_changes = False

    print('\n==================== CI JOB STATUS REPORT ====================')
    for job in ci_info.jobs:
        logger.info(f'Checking {job.platform} ({job.job_name}) starting from build {job.build_num}...')
        res = find_latest_job_build(
            session=session,
            ci_server=args.jenkins_url,
            job_name=job.job_name,
            start_build_num=job.build_num,
            launcher_build=ci_info.launcher_build,
            gist_hash=ci_info.gist_hash,
            branch_name=ci_info.branch_name)
        results[job.job_name] = res

        if res.is_queued:
            status_desc = f'QUEUED (item #{res.queue_item_id}, pos #{res.queue_position})'
            print(f'* {job.platform:15} | Initial: {job.build_num:5} | Current: {status_desc}')
        elif res.build_num and res.build_num != job.build_num:
            has_changes = True
            print(f'* {job.platform:15} | Initial: {job.build_num:5} | Latest: {res.build_num:5} -> {res.status}')
        else:
            print(f'* {job.platform:15} | Current: {job.build_num:5} -> {res.status}')

    updated_body = update_comment_body(ci_info.body, ci_info.jobs, results)

    if has_changes:
        print('\n==================== UPDATED COMMENT PREVIEW ====================')
        print(updated_body)

        if args.update_comment:
            logger.info(f'Updating GitHub comment #{ci_info.comment_id} on {repo_name}...')
            comment.edit(body=updated_body)
            print('\n>>> Successfully updated GitHub comment in-place! <<<')
        else:
            print('\n(Run with -u / --update-comment to update the GitHub comment automatically)')
    else:
        print('\nNo build number changes detected in CI jobs.')


if __name__ == '__main__':
    main()
