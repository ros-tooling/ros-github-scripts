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
import datetime
from string import Template
from typing import (
    Callable,
    Dict,
    List,
    NamedTuple,
    Optional,
)

from github import Github
import markdown2
import requests


CONTRIBUTION_QUERY = Template("""
{
  search(first: 100, after: $cursor, type: ISSUE, query: "$search_query") {
    pageInfo {
      startCursor
      hasNextPage
      endCursor
    }
    edges {
      node {
        ... on PullRequest {
          author {
            ... on User {
              name
              login
            }
          }
          createdAt
          permalink
          repository {
            nameWithOwner
          }
          title
          updatedAt
          mergedAt
        }
      }
    }
  }
}
""")


def graphql_query(query: str, token: Optional[str] = None) -> dict:
    # print(query)
    headers = {'Authorization': f'Bearer {token}'} if token else None
    request = requests.post(
        'https://api.github.com/graphql',
        json={'query': query},
        headers=headers)
    if request.status_code == 200:
        return request.json()
    else:
        raise RuntimeError(f'Query failed with code {request.status_code}')


def query_contributions(
    token: Optional[str],
    authors: List[str],
    orgs: List[str],
    repos: List[str],
    since: Optional[datetime.date] = None,
    until: Optional[datetime.date] = None,
) -> List[dict]:
    if since is None and until is None:
        merged = ''
    else:
        if until:
            date_range = f'{since.isoformat()}..{until.isoformat()}'
        else:
            date_range = f'>={since.isoformat()}'
        merged = f'merged:{date_range}'

    search_query = ' '.join([
        'sort:updated-desc',
        'is:pr is:merged',
        ' '.join([f'author:{a}' for a in authors]),
        ' '.join([f'org:{o}' for o in orgs]),
        ' '.join([f'repo:{r}' for r in repos]),
        merged,
    ])

    cursor = 'null'
    has_next_page = True
    contributions = []
    while has_next_page:
        contribution_query = CONTRIBUTION_QUERY.substitute(
            search_query=search_query,
            cursor=cursor)
        response = graphql_query(contribution_query, token)
        results = response['data']
        contributions += results['search']['edges']

        page_info = results['search']['pageInfo']
        end_cursor = page_info['endCursor']
        cursor = f'"{end_cursor}"'
        has_next_page = page_info['hasNextPage']

    return contributions


def query_members_of_org(org: str) -> List[str]:
    raise NotImplementedError(
      'Querying members of an organization for contributions is not yet implemented.')


def parse_github_time(value: str) -> datetime.datetime:
    return datetime.datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ')


def format_github_time_to_date(value: str) -> str:
    return parse_github_time(value).date().isoformat()


def line_format_contribution(node: dict) -> str:
    """Format an individual GitHub PR into our contribution line format."""
    title = node['title']
    author = node['author'].get('name')
    link = node['permalink']
    merged = format_github_time_to_date(node['mergedAt'])
    return f'[{title}]({link}) - {author} (merged {merged})'


def line_format_contributions(
    contributions: List[dict], since: datetime.date, authors: List[str], orgs: List[str]
) -> List[str]:
    """
    Format the contribution report in the TSC format.

    This is a bullet list of repositories, each having a sublist of PRs
    formatted in a simple 1-line format.

    :returns: A list of markdown lines
    """
    contrib_authors = {node['node'].get('author', {}).get('login', 'None') for node in contributions}
    lines = [
        '* By Authors: {}'.format(', '.join(contrib_authors)),
        '* To Repositories in Organizations: {}'.format(', '.join(orgs)), '',
        f'* Merged Since: {since.isoformat()}', '',
        f'* This report generated: {datetime.date.today().isoformat()}', '',
        f'* Contribution count (remember to update if you remove things): {len(contributions)}',
        '',
    ]

    byrepo: Dict[str, List[str]] = {}
    for contrib_json in contributions:
        node = contrib_json['node']
        repo = node['repository']['nameWithOwner']
        # skip bots
        if node['author'].get('login') is None:
            continue
        byrepo.setdefault(repo, []).append(line_format_contribution(node))

    for repo, contribs in sorted(byrepo.items()):
        lines.append(f'* {repo}')
        for contrib_str in contribs:
            lines.append(f'  * {contrib_str}')

    return lines


def table_format_contributions(
    contributions: List[dict], since: datetime.date, authors: List[str], orgs: List[str]
) -> List[str]:
    now = datetime.datetime.now()
    lines = [
        f'{len(contributions)} results',
        '',
        '| Repository | Title | Created | Merged | GH User | Link |',
        '| ---------- | ----- | ------- | ------ | ------- | ---- |',
    ]
    contributions = sorted(contributions, key=lambda c: c['node']['mergedAt'])
    for contrib in contributions:
        node = contrib['node']
        repo_name = node['repository']['nameWithOwner']
        title = node['title']
        created_at = parse_github_time(node['createdAt'])
        created_at_delta = (now - created_at).days + 1
        merged_at = parse_github_time(node['mergedAt'])
        merged_at_delta = (now - merged_at).days + 1
        author_node = node['author']
        author = author_node['name']
        if author is None:
            author_login = author_node['login']
            author = f'Unknown ({author_login})'
        permalink = node['permalink']
        lines.append(
            f'| {repo_name} '
            f'| {title} '
            f'| {created_at.date().isoformat()} ({created_at_delta} days ago) '
            f'| {merged_at.date().isoformat()} ({merged_at_delta} days ago) '
            f'| {author} '
            f'| [{permalink}]({permalink}) |'
        )
    return lines


def IsoDate(value: str) -> datetime.date:
    """Validate and translate an argparse input into a datetime.date from ISO format."""
    return datetime.datetime.strptime(value, '%Y-%m-%d').date()


class ContributionReportOptions(NamedTuple):
    since: datetime.date
    until: Optional[datetime.date]
    authors: List[str]
    orgs: List[str]
    repos: List[str]
    token: str
    formatter: Callable
    render_html: bool


def all_authors(
    users: List[str], members_from_org: Optional[str] = None, token: Optional[str] = None
) -> List[str]:
    out = users
    if members_from_org:
        github_client = Github(token)
        org = github_client.get_organization(members_from_org)
        org_members = org.get_members()
        out += [user.login for user in org_members]
    return out


def parse_args(args=None) -> ContributionReportOptions:
    formatters = {
        'tsc': line_format_contributions,
        'table': table_format_contributions,
    }
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-s', '--since',
        type=IsoDate,
        default=datetime.date.today() - datetime.timedelta(days=30),
        help='Report contributions merged on or after this date '
             '(format YYYY-MM-DD). Defaults to 30 days ago')
    parser.add_argument(
        '-u', '--until',
        type=IsoDate,
        default=None,
        help='Report contributions merged until this date (defaults to right now)'),
    parser.add_argument(
        '-t', '--token',
        default=None,
        help='Github access token. Optional but you might get rate limited without it')
    parser.add_argument(
        '-a', '--authors',
        nargs='+',
        required=False,
        default=[],
        help='Report contributions for these github usernames. Combines with --authors-from-org')
    parser.add_argument(
        '-m', '--authors-from-org',
        required=False,
        help='Report contributions from all members of this GitHub organization. '
             'Combines with --authors')
    parser.add_argument(
        '-o', '--orgs',
        nargs='+',
        required=False,
        default=[],
        help='Report contributions only to repos these github organizations')
    parser.add_argument(
        '--repos',
        nargs='+',
        required=False,
        default=[],
        help='Report contributions to these specific repositories (in addition to --orgs)')
    parser.add_argument(
        '-f', '--format',
        type=str,
        choices=formatters.keys(),
        default='tsc',
        help='Formatting option for the output. '
             '"tsc" creates a list in the style we report monthly to the ROS 2 TSC. '
             '"table" creates a table that can be rendered to HTML for internal email reports.')
    parser.add_argument(
        '-r', '--render-html',
        action='store_true',
        help='Render output markdown to HTML for easier display.')
    if args is None:
        parsed = parser.parse_args()
    else:
        parsed = parser.parse_args(args)

    if not parsed.authors and not parsed.authors_from_org:
        print(
            'Neither --authors nor --authors-from-org specified, '
            'the results might be huge...')

    authors = all_authors(parsed.authors, parsed.authors_from_org, parsed.token)

    return ContributionReportOptions(
        since=parsed.since,
        until=parsed.until,
        authors=authors,
        token=parsed.token,
        orgs=parsed.orgs,
        repos=parsed.repos,
        formatter=formatters[parsed.format],
        render_html=parsed.render_html)


def main(args=None):
    options = parse_args(args)
    contributions = query_contributions(
        options.token, options.authors, options.orgs, options.repos, options.since, options.until)
    lines = options.formatter(
        contributions, options.since, options.authors, options.orgs)
    md_content = '\n'.join(lines)
    if options.render_html:
        html_content = markdown2.markdown(md_content, extras=['tables', 'code-friendly'])
        print(html_content)
    else:
        print(md_content)


if __name__ == '__main__':
    main()
