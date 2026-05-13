"""
GitHub Agent - Collects data from GitHub (releases, commits, issues, PRs, discussions).
"""

import os
import requests
from datetime import datetime, timedelta
from typing import Optional

from .base import CollectorAgent, NewsItem


class GitHubAgent(CollectorAgent):
    """
    Agent for collecting LLVM updates from GitHub.

    Fetches:
    - Releases
    - Important commits
    - Hot issues and PRs (with GITHUB_TOKEN)
    - Discussions (with GITHUB_TOKEN)
    """

    GITHUB_API = "https://api.github.com"
    REPO = "llvm/llvm-project"

    def __init__(self, config: dict = None):
        super().__init__("github", config)

        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'LLVM-Monitor-Agent/2.0',
            'Accept': 'application/vnd.github.v3+json'
        })

        # GitHub token from config or environment
        token = self.get_config('github.token') or os.environ.get('GITHUB_TOKEN')
        if token:
            self.session.headers['Authorization'] = f'token {token}'
            self.has_token = True
        else:
            self.has_token = False
            self.log_info("No GITHUB_TOKEN found, some features will be limited")

    def fetch(self) -> list[NewsItem]:
        """Fetch all GitHub data."""
        items = []

        # Always available without token
        items.extend(self._fetch_releases())
        items.extend(self._fetch_commits())

        # Requires token for GraphQL API
        if self.has_token:
            items.extend(self._fetch_discussions())
            items.extend(self._fetch_issues_prs())
        else:
            self.log_info("Skipping discussions and issues (no token)")

        return items

    def _fetch_releases(self) -> list[NewsItem]:
        """Fetch latest releases."""
        items = []
        try:
            url = f"{self.GITHUB_API}/repos/{self.REPO}/releases"
            resp = self.session.get(url, params={'per_page': 10}, timeout=30)
            resp.raise_for_status()

            for release in resp.json():
                items.append(NewsItem(
                    source='github-releases',
                    title=release['name'] or release['tag_name'],
                    url=release['html_url'],
                    date=release['published_at'],
                    summary=release.get('body', '')[:500] if release.get('body') else '',
                    importance='medium',  # Will be re-evaluated by analyzer
                    tags=['release'],
                    raw_data=release
                ))
            self.log_info(f"Fetched {len(items)} releases")
        except Exception as e:
            self.log_error(f"Error fetching releases: {e}")

        return items

    def _fetch_commits(self) -> list[NewsItem]:
        """Fetch recent commits."""
        items = []
        days = self.get_config('filters.commits_days', 7)
        since = (datetime.now() - timedelta(days=days)).isoformat()

        try:
            url = f"{self.GITHUB_API}/repos/{self.REPO}/commits"
            resp = self.session.get(
                url,
                params={'since': since, 'per_page': 100},
                timeout=30
            )
            resp.raise_for_status()

            for commit in resp.json():
                message = commit['commit']['message']
                items.append(NewsItem(
                    source='github-commits',
                    title=message.split('\n')[0][:100],
                    url=commit['html_url'],
                    date=commit['commit']['author']['date'],
                    summary=message[:500],
                    importance='low',  # Will be re-evaluated by analyzer
                    tags=[],
                    raw_data=commit
                ))
            self.log_info(f"Fetched {len(items)} commits")
        except Exception as e:
            self.log_error(f"Error fetching commits: {e}")

        return items

    def _fetch_discussions(self) -> list[NewsItem]:
        """Fetch GitHub Discussions using GraphQL API."""
        items = []

        query = """
        query {
          repository(owner: "llvm", name: "llvm-project") {
            discussions(first: 30, orderBy: {field: UPDATED_AT, direction: DESC}) {
              nodes {
                title
                url
                createdAt
                category { name }
                comments { totalCount }
                upvoteCount
              }
            }
          }
        }
        """

        try:
            resp = self.session.post(
                'https://api.github.com/graphql',
                json={'query': query},
                timeout=30
            )
            resp.raise_for_status()
            data = resp.json()

            discussions = data.get('data', {}).get('repository', {}).get('discussions', {}).get('nodes', [])

            for disc in discussions:
                comments = disc.get('comments', {}).get('totalCount', 0)
                upvotes = disc.get('upvoteCount', 0)

                items.append(NewsItem(
                    source='github-discussions',
                    title=disc.get('title', ''),
                    url=disc['url'],
                    date=disc.get('createdAt'),
                    summary=f"Category: {disc.get('category', {}).get('name', 'N/A')} | "
                           f"Comments: {comments} | Upvotes: {upvotes}",
                    importance='low',
                    tags=['discussion', 'github'],
                    raw_data={'comments': comments, 'upvotes': upvotes}
                ))
            self.log_info(f"Fetched {len(items)} discussions")
        except Exception as e:
            self.log_error(f"Error fetching discussions: {e}")

        return items

    def _fetch_issues_prs(self) -> list[NewsItem]:
        """Fetch hot issues and PRs using GraphQL API."""
        items = []
        min_comments = self.get_config('filters.min_comments_issues', 5)

        query = f"""
        query {{
          search(query: "repo:llvm/llvm-project is:open comments:>{min_comments} sort:updated",
                 type: ISSUE, first: 30) {{
            nodes {{
              ... on Issue {{
                title
                url
                createdAt
                comments {{ totalCount }}
                labels(first: 5) {{ nodes {{ name }} }}
              }}
              ... on PullRequest {{
                title
                url
                createdAt
                comments {{ totalCount }}
                labels(first: 5) {{ nodes {{ name }} }}
              }}
            }}
          }}
        }}
        """

        try:
            resp = self.session.post(
                'https://api.github.com/graphql',
                json={'query': query},
                timeout=30
            )
            resp.raise_for_status()
            data = resp.json()

            nodes = data.get('data', {}).get('search', {}).get('nodes', [])

            for node in nodes:
                if not node:
                    continue

                labels = [l['name'] for l in node.get('labels', {}).get('nodes', [])]
                comments = node.get('comments', {}).get('totalCount', 0)

                items.append(NewsItem(
                    source='github-issues',
                    title=node.get('title', ''),
                    url=node['url'],
                    date=node.get('createdAt'),
                    summary=f"Comments: {comments} | Labels: {', '.join(labels[:3]) or 'none'}",
                    importance='low',
                    tags=labels[:3],
                    raw_data={'comments': comments, 'labels': labels}
                ))
            self.log_info(f"Fetched {len(items)} issues/PRs")
        except Exception as e:
            self.log_error(f"Error fetching issues/PRs: {e}")

        return items
