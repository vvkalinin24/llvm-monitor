#!/usr/bin/env python3
"""
LLVM Monitor Agent
Monitors llvm.org and GitHub for important updates.
Configured via config.yaml
"""

import json
import hashlib
import requests
import yaml
import time
import subprocess
import os
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional
import re
from bs4 import BeautifulSoup


@dataclass
class NewsItem:
    """Represents a single news/update item."""
    source: str
    title: str
    url: str
    date: Optional[str]
    summary: str
    importance: str      # high, medium, low
    tags: list[str]

    @property
    def id(self) -> str:
        return hashlib.md5(f"{self.source}:{self.url}".encode()).hexdigest()


class LLVMMonitor:
    """Agent for monitoring the LLVM ecosystem."""

    GITHUB_API = "https://api.github.com"
    LLVM_BLOG_URL = "https://blog.llvm.org/"
    DISCOURSE_URL = "https://discourse.llvm.org"

    # Discourse category name to ID mapping
    DISCOURSE_CATEGORY_IDS = {
        'rfc': 5,
        'announce': 43,
        'clang': 6,
        'mlir': 42,
        'llvm-dev': 7,
        'code-review': 36,
        'flang': 33,
        'lldb': 35,
        'lld': 34,
        'openmp': 37,
    }

    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = Path(config_path)
        self.config = self._load_config()

        self.state_file = Path(self.config.get('state_file', 'llvm_monitor_state.json'))
        self.state = self._load_state()

        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'LLVM-Monitor-Agent/2.0'
        })

        # GitHub token from config or environment
        github_token = self.config.get('github', {}).get('token') or os.environ.get('GITHUB_TOKEN')
        if github_token:
            self.session.headers['Authorization'] = f'token {github_token}'
            self.has_github_token = True
        else:
            self.has_github_token = False

        # Collect keywords from config
        self.high_keywords = set(self.config.get('high_priority_keywords', []))
        self.medium_keywords = set(self.config.get('medium_priority_keywords', []))

        # Add tracked components as high priority keywords
        for comp in self.config.get('components', []):
            self.high_keywords.add(comp.lower())

    def _load_config(self) -> dict:
        """Load configuration from YAML file."""
        if self.config_path.exists():
            return yaml.safe_load(self.config_path.read_text())
        return {}

    def _load_state(self) -> dict:
        """Load previous state (seen items)."""
        if self.state_file.exists():
            return json.loads(self.state_file.read_text())
        return {
            'seen_ids': [],
            'last_check': None,
        }

    def _save_state(self):
        """Save current state."""
        self.state['last_check'] = datetime.now().isoformat()
        self.state_file.write_text(json.dumps(self.state, indent=2))

    def _determine_importance(self, text: str) -> str:
        """Determine importance level based on keywords."""
        text_lower = text.lower()

        for keyword in self.high_keywords:
            if keyword in text_lower:
                return 'high'

        for keyword in self.medium_keywords:
            if keyword in text_lower:
                return 'medium'

        return 'low'

    def _extract_tags(self, text: str) -> list[str]:
        """Extract relevant tags from text."""
        tags = []
        text_lower = text.lower()

        tag_keywords = {
            'clang': ['clang', 'clang-tidy', 'clang-format'],
            'lldb': ['lldb', 'debugger'],
            'lld': ['lld', 'linker'],
            'mlir': ['mlir'],
            'flang': ['flang', 'fortran'],
            'amdgpu': ['amdgpu', 'amd', 'rocm', 'hip'],
            'security': ['security', 'cve', 'vulnerability'],
            'performance': ['performance', 'optimization', 'fast'],
            'release': ['release', 'version'],
            'codegen': ['codegen', 'code generation', 'backend'],
        }

        for tag, keywords in tag_keywords.items():
            if any(kw in text_lower for kw in keywords):
                tags.append(tag)

        return tags

    def _is_source_enabled(self, source: str) -> bool:
        """Check if a source is enabled in config."""
        sources = self.config.get('sources', {})
        return sources.get(source, True)

    def fetch_github_releases(self) -> list[NewsItem]:
        """Fetch latest releases from GitHub."""
        if not self._is_source_enabled('github_releases'):
            return []

        items = []
        try:
            url = f"{self.GITHUB_API}/repos/llvm/llvm-project/releases"
            resp = self.session.get(url, params={'per_page': 10}, timeout=30)
            resp.raise_for_status()

            for release in resp.json():
                content = f"{release['name']} {release.get('body', '')}"
                items.append(NewsItem(
                    source='github-releases',
                    title=release['name'] or release['tag_name'],
                    url=release['html_url'],
                    date=release['published_at'],
                    summary=release.get('body', '')[:500] if release.get('body') else '',
                    importance=self._determine_importance(content),
                    tags=self._extract_tags(content) + ['release'],
                ))
        except Exception as e:
            print(f"[WARN] Error fetching GitHub releases: {e}")

        return items

    def fetch_github_commits(self) -> list[NewsItem]:
        """Fetch important commits from GitHub."""
        if not self._is_source_enabled('github_commits'):
            return []

        items = []
        days = self.config.get('filters', {}).get('commits_days', 7)
        since = (datetime.now() - timedelta(days=days)).isoformat()

        try:
            url = f"{self.GITHUB_API}/repos/llvm/llvm-project/commits"
            resp = self.session.get(url, params={
                'since': since,
                'per_page': 100
            }, timeout=30)
            resp.raise_for_status()

            for commit in resp.json():
                message = commit['commit']['message']
                importance = self._determine_importance(message)

                # Only include important commits
                if importance in ('high', 'medium'):
                    items.append(NewsItem(
                        source='github-commits',
                        title=message.split('\n')[0][:100],
                        url=commit['html_url'],
                        date=commit['commit']['author']['date'],
                        summary=message[:500],
                        importance=importance,
                        tags=self._extract_tags(message),
                    ))
        except Exception as e:
            print(f"[WARN] Error fetching commits: {e}")

        return items

    def fetch_blog_posts(self) -> list[NewsItem]:
        """Parse LLVM blog for posts."""
        if not self._is_source_enabled('blog'):
            return []

        items = []
        try:
            resp = self.session.get(self.LLVM_BLOG_URL, timeout=30)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')

            for article in soup.find_all(['article', 'div'], class_=re.compile(r'post|entry|article')):
                title_elem = article.find(['h1', 'h2', 'h3', 'a'])
                if not title_elem:
                    continue

                title = title_elem.get_text(strip=True)
                link = title_elem.get('href') or (title_elem.find('a') or {}).get('href', '')

                if not link.startswith('http'):
                    link = f"{self.LLVM_BLOG_URL.rstrip('/')}/{link.lstrip('/')}"

                date_elem = article.find(['time', 'span'], class_=re.compile(r'date|time'))
                date_str = date_elem.get_text(strip=True) if date_elem else None

                summary_elem = article.find(['p', 'div'], class_=re.compile(r'summary|excerpt|content'))
                summary = summary_elem.get_text(strip=True)[:300] if summary_elem else ''

                content = f"{title} {summary}"
                items.append(NewsItem(
                    source='blog',
                    title=title,
                    url=link,
                    date=date_str,
                    summary=summary,
                    importance=self._determine_importance(content),
                    tags=self._extract_tags(content) + ['blog'],
                ))
        except Exception as e:
            print(f"[WARN] Error parsing blog: {e}")

        return items

    def fetch_discourse_topics(self) -> list[NewsItem]:
        """Fetch topics from LLVM Discourse forum."""
        if not self._is_source_enabled('discourse'):
            return []

        items = []
        seen_ids = set()
        enabled_categories = self.config.get('discourse_categories', ['rfc', 'announce'])
        max_age_days = self.config.get('filters', {}).get('max_topic_age_days', 60)

        try:
            # Fetch from configured categories
            for cat_name in enabled_categories:
                cat_id = self.DISCOURSE_CATEGORY_IDS.get(cat_name)
                if not cat_id:
                    continue

                url = f"{self.DISCOURSE_URL}/c/{cat_id}.json"
                try:
                    resp = self.session.get(url, timeout=30)
                    resp.raise_for_status()
                    data = resp.json()

                    for topic in data.get('topic_list', {}).get('topics', [])[:15]:
                        if topic['id'] in seen_ids:
                            continue
                        seen_ids.add(topic['id'])

                        item = self._parse_discourse_topic(topic, cat_name, max_age_days)
                        if item:
                            items.append(item)
                except Exception as e:
                    print(f"[WARN] Error fetching category {cat_name}: {e}")

            # Fetch latest and top topics
            for feed in ['latest', 'top']:
                url = f"{self.DISCOURSE_URL}/{feed}.json"
                try:
                    resp = self.session.get(url, timeout=30)
                    resp.raise_for_status()
                    data = resp.json()

                    for topic in data.get('topic_list', {}).get('topics', [])[:20]:
                        if topic['id'] in seen_ids:
                            continue
                        seen_ids.add(topic['id'])

                        item = self._parse_discourse_topic(topic, None, max_age_days)
                        if item:
                            items.append(item)
                except Exception as e:
                    print(f"[WARN] Error fetching {feed}: {e}")

        except Exception as e:
            print(f"[WARN] Error fetching Discourse: {e}")

        return items

    def _parse_discourse_topic(self, topic: dict, category: str = None,
                               max_age_days: int = 60) -> Optional[NewsItem]:
        """Parse a single Discourse topic."""
        title = topic.get('title', '')
        topic_url = f"{self.DISCOURSE_URL}/t/{topic.get('slug', '')}/{topic['id']}"

        importance = self._determine_importance(title)

        # RFCs are always high priority
        if category == 'rfc' or '[RFC]' in title.upper():
            importance = 'high'

        # Announcements are important
        if category == 'announce':
            if importance == 'low':
                importance = 'medium'

        posts = topic.get('posts_count', 0)
        likes = topic.get('like_count', 0)
        views = topic.get('views', 0)

        # Hot topics get priority boost
        if posts > 30 or likes > 20 or views > 1000:
            if importance == 'low':
                importance = 'medium'
        if posts > 50 or likes > 50:
            importance = 'high'

        # Filter out old inactive topics
        last_posted = topic.get('last_posted_at')
        if last_posted:
            try:
                last_date = datetime.fromisoformat(last_posted.replace('Z', '+00:00'))
                age_days = (datetime.now(last_date.tzinfo) - last_date).days
                if age_days > max_age_days and importance == 'low':
                    return None
            except:
                pass

        tags = self._extract_tags(title) + ['discussion']
        if category:
            tags.append(category)

        return NewsItem(
            source='discourse',
            title=title,
            url=topic_url,
            date=topic.get('created_at'),
            summary=f"Replies: {posts} | Views: {views} | Likes: {likes}",
            importance=importance,
            tags=tags,
        )

    def fetch_github_issues_pr(self) -> list[NewsItem]:
        """Fetch hot Issues and PRs from GitHub."""
        if not self._is_source_enabled('github_issues_pr'):
            return []

        if not self.has_github_token:
            print("[INFO] GitHub Issues/PR requires GITHUB_TOKEN, skipping")
            return []

        items = []
        min_comments = self.config.get('filters', {}).get('min_comments_issues', 5)

        try:
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
                title = node.get('title', '')
                labels = [l['name'] for l in node.get('labels', {}).get('nodes', [])]
                content = f"{title} {' '.join(labels)}"

                importance = self._determine_importance(content)
                comments = node.get('comments', {}).get('totalCount', 0)

                if comments > 20:
                    if importance == 'low':
                        importance = 'medium'
                    elif importance == 'medium':
                        importance = 'high'

                items.append(NewsItem(
                    source='github-issues',
                    title=title,
                    url=node['url'],
                    date=node.get('createdAt'),
                    summary=f"Comments: {comments} | Labels: {', '.join(labels[:3]) or 'none'}",
                    importance=importance,
                    tags=self._extract_tags(content) + labels[:3],
                ))
        except Exception as e:
            print(f"[WARN] Error fetching GitHub Issues/PR: {e}")

        return items

    def fetch_github_discussions(self) -> list[NewsItem]:
        """Fetch discussions from GitHub Discussions."""
        if not self._is_source_enabled('github_discussions'):
            return []

        if not self.has_github_token:
            print("[INFO] GitHub Discussions requires GITHUB_TOKEN, skipping")
            return []

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
                title = disc.get('title', '')
                content = f"{title} {disc.get('category', {}).get('name', '')}"
                importance = self._determine_importance(content)

                comments = disc.get('comments', {}).get('totalCount', 0)
                upvotes = disc.get('upvoteCount', 0)

                if comments > 10 or upvotes > 5:
                    if importance == 'low':
                        importance = 'medium'

                items.append(NewsItem(
                    source='github-discussions',
                    title=title,
                    url=disc['url'],
                    date=disc.get('createdAt'),
                    summary=f"Category: {disc.get('category', {}).get('name', 'N/A')} | "
                           f"Comments: {comments} | Upvotes: {upvotes}",
                    importance=importance,
                    tags=self._extract_tags(content) + ['discussion', 'github'],
                ))
        except Exception as e:
            print(f"[WARN] Error fetching GitHub Discussions: {e}")

        return items

    def run(self, include_seen: bool = False) -> list[NewsItem]:
        """Run full monitoring cycle."""
        all_items = []

        print("Checking GitHub releases...")
        all_items.extend(self.fetch_github_releases())

        print("Checking important commits...")
        all_items.extend(self.fetch_github_commits())

        print("Checking LLVM blog...")
        all_items.extend(self.fetch_blog_posts())

        print("Checking Discourse (RFC, discussions)...")
        all_items.extend(self.fetch_discourse_topics())

        print("Checking GitHub Discussions...")
        all_items.extend(self.fetch_github_discussions())

        print("Checking hot Issues/PRs...")
        all_items.extend(self.fetch_github_issues_pr())

        # Filter already seen items
        if not include_seen:
            new_items = [item for item in all_items
                        if item.id not in self.state['seen_ids']]
        else:
            new_items = all_items

        # Filter by minimum importance level
        min_importance = self.config.get('filters', {}).get('min_importance', 'low')
        if min_importance == 'medium':
            new_items = [i for i in new_items if i.importance in ('high', 'medium')]
        elif min_importance == 'high':
            new_items = [i for i in new_items if i.importance == 'high']

        # Update state
        for item in new_items:
            if item.id not in self.state['seen_ids']:
                self.state['seen_ids'].append(item.id)

        # Limit history size
        self.state['seen_ids'] = self.state['seen_ids'][-2000:]
        self._save_state()

        # Sort by importance
        priority = {'high': 0, 'medium': 1, 'low': 2}
        new_items.sort(key=lambda x: (priority[x.importance], x.date or ''))

        return new_items

    def generate_report(self, items: list[NewsItem], format: str = None) -> str:
        """Generate report in specified format."""
        fmt = format or self.config.get('notifications', {}).get('file', {}).get('format', 'markdown')

        if fmt == 'markdown':
            return self._generate_markdown_report(items)
        elif fmt == 'json':
            return json.dumps([asdict(item) for item in items], indent=2, ensure_ascii=False)
        else:
            return self._generate_text_report(items)

    def _generate_markdown_report(self, items: list[NewsItem]) -> str:
        """Generate Markdown report."""
        components = ', '.join(self.config.get('components', ['all']))

        lines = [
            f"# LLVM Monitor Report",
            f"",
            f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            f"**Updates found:** {len(items)}",
            f"**Tracked components:** {components}",
            f"",
        ]

        high = [i for i in items if i.importance == 'high']
        medium = [i for i in items if i.importance == 'medium']
        low = [i for i in items if i.importance == 'low']

        if high:
            lines.append("## High Priority - Action Required")
            lines.append("")
            for item in high:
                lines.extend(self._format_item_md(item))

        if medium:
            lines.append("## Medium Priority - Worth Reviewing")
            lines.append("")
            for item in medium:
                lines.extend(self._format_item_md(item))

        if low:
            lines.append("## Low Priority - Informational")
            lines.append("")
            for item in low[:15]:
                lines.extend(self._format_item_md(item))
            if len(low) > 15:
                lines.append(f"*... and {len(low) - 15} more updates*")
                lines.append("")

        if not items:
            lines.append("*No new updates*")

        return '\n'.join(lines)

    def _format_item_md(self, item: NewsItem) -> list[str]:
        """Format a single item as Markdown."""
        lines = [
            f"### [{item.title}]({item.url})",
            f"",
            f"- **Source:** {item.source}",
        ]
        if item.date:
            lines.append(f"- **Date:** {item.date}")
        if item.tags:
            lines.append(f"- **Tags:** {', '.join(item.tags)}")
        if item.summary:
            lines.append(f"")
            lines.append(f"> {item.summary[:300]}")
        lines.append("")
        return lines

    def _generate_text_report(self, items: list[NewsItem]) -> str:
        """Generate plain text report."""
        lines = [
            "=" * 60,
            "LLVM MONITOR REPORT",
            f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            f"Found: {len(items)} updates",
            "=" * 60,
            "",
        ]

        for item in items:
            icon = {'high': '[!!!]', 'medium': '[!!]', 'low': '[i]'}[item.importance]
            lines.append(f"{icon} [{item.source}] {item.title}")
            lines.append(f"    URL: {item.url}")
            if item.summary:
                lines.append(f"    {item.summary[:100]}...")
            lines.append("")

        return '\n'.join(lines)

    def send_notification(self, items: list[NewsItem]):
        """Send notification based on config settings."""
        notif_config = self.config.get('notifications', {})
        notif_type = notif_config.get('type', 'file')

        if notif_type == 'desktop':
            self._send_desktop_notification(items, notif_config.get('desktop', {}))
        elif notif_type == 'file':
            self._save_report_file(items, notif_config.get('file', {}))

    def _send_desktop_notification(self, items: list[NewsItem], config: dict):
        """Send desktop notification via notify-send."""
        only_high = config.get('only_high_priority', True)
        if only_high:
            items = [i for i in items if i.importance == 'high']

        if not items:
            return

        try:
            title = f"LLVM Monitor: {len(items)} updates"
            body = '\n'.join([f"- {i.title[:50]}" for i in items[:5]])
            subprocess.run(['notify-send', title, body], check=True)
        except Exception as e:
            print(f"[WARN] notify-send error: {e}")

    def _save_report_file(self, items: list[NewsItem], config: dict):
        """Save report to file."""
        output_dir = Path(config.get('output_dir', 'reports'))
        output_dir.mkdir(exist_ok=True)

        fmt = config.get('format', 'markdown')
        ext = {'markdown': 'md', 'json': 'json', 'text': 'txt'}.get(fmt, 'md')

        filename = f"report_{datetime.now().strftime('%Y-%m-%d_%H%M')}.{ext}"
        filepath = output_dir / filename

        report = self.generate_report(items, fmt)
        filepath.write_text(report)
        print(f"Report saved: {filepath}")

        # Clean up old reports
        keep_days = config.get('keep_days', 30)
        self._cleanup_old_reports(output_dir, keep_days)

    def _cleanup_old_reports(self, output_dir: Path, keep_days: int):
        """Remove reports older than N days."""
        cutoff = datetime.now() - timedelta(days=keep_days)
        for f in output_dir.glob('report_*'):
            try:
                if datetime.fromtimestamp(f.stat().st_mtime) < cutoff:
                    f.unlink()
            except:
                pass


def run_daemon(monitor: LLVMMonitor, interval_minutes: int = 60):
    """Run monitor in daemon mode."""
    print(f"LLVM Monitor daemon started (interval: {interval_minutes} min)")

    while True:
        try:
            print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Running check...")
            items = monitor.run()
            print(f"Found {len(items)} new updates")

            if items:
                monitor.send_notification(items)

        except KeyboardInterrupt:
            print("\nStopping daemon...")
            break
        except Exception as e:
            print(f"[ERROR] {e}")

        time.sleep(interval_minutes * 60)


def main():
    import argparse

    parser = argparse.ArgumentParser(description='LLVM Monitor Agent')
    parser.add_argument('--config', '-c', default='config.yaml',
                       help='Path to configuration file')
    parser.add_argument('--format', choices=['markdown', 'text', 'json'],
                       help='Output format (overrides config)')
    parser.add_argument('--output', '-o', help='Output file path')
    parser.add_argument('--all', action='store_true',
                       help='Show all items including already seen')
    parser.add_argument('--daemon', action='store_true',
                       help='Run in daemon mode')

    args = parser.parse_args()

    # Find config relative to script
    script_dir = Path(__file__).parent
    config_path = script_dir / args.config
    if not config_path.exists():
        config_path = Path(args.config)

    monitor = LLVMMonitor(config_path=str(config_path))

    if args.daemon:
        interval = monitor.config.get('schedule', {}).get('interval_minutes', 60)
        run_daemon(monitor, interval)
    else:
        print("Starting LLVM Monitor...")
        items = monitor.run(include_seen=args.all)
        print(f"Found {len(items)} updates")

        report = monitor.generate_report(items, format=args.format)

        if args.output:
            Path(args.output).write_text(report)
            print(f"Report saved: {args.output}")
        else:
            print("\n" + report)


if __name__ == '__main__':
    main()
