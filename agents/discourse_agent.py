"""
Discourse Agent - Collects discussions from LLVM Discourse forum.
"""

import requests
from datetime import datetime
from typing import Optional

from .base import CollectorAgent, NewsItem


class DiscourseAgent(CollectorAgent):
    """
    Agent for collecting discussions from LLVM Discourse.

    Monitors:
    - RFC proposals
    - Announcements
    - Component-specific categories (Clang, MLIR, etc.)
    - Hot topics
    """

    DISCOURSE_URL = "https://discourse.llvm.org"

    # Category name to ID mapping
    CATEGORY_IDS = {
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

    def __init__(self, config: dict = None):
        super().__init__("discourse", config)

        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'LLVM-Monitor-Agent/2.0'
        })

    def fetch(self) -> list[NewsItem]:
        """Fetch all Discourse topics."""
        items = []
        seen_ids = set()

        # Fetch from configured categories
        categories = self.get_config('discourse_categories', ['rfc', 'announce'])
        for cat_name in categories:
            cat_items = self._fetch_category(cat_name, seen_ids)
            items.extend(cat_items)

        # Fetch latest and top
        items.extend(self._fetch_feed('latest', seen_ids))
        items.extend(self._fetch_feed('top', seen_ids))

        return items

    def _fetch_category(self, category: str, seen_ids: set) -> list[NewsItem]:
        """Fetch topics from a specific category."""
        items = []
        cat_id = self.CATEGORY_IDS.get(category)

        if not cat_id:
            self.log_info(f"Unknown category: {category}")
            return items

        try:
            url = f"{self.DISCOURSE_URL}/c/{cat_id}.json"
            resp = self.session.get(url, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            for topic in data.get('topic_list', {}).get('topics', [])[:15]:
                if topic['id'] in seen_ids:
                    continue
                seen_ids.add(topic['id'])

                item = self._parse_topic(topic, category)
                if item:
                    items.append(item)

            self.log_info(f"Fetched {len(items)} topics from {category}")
        except Exception as e:
            self.log_error(f"Error fetching category {category}: {e}")

        return items

    def _fetch_feed(self, feed: str, seen_ids: set) -> list[NewsItem]:
        """Fetch topics from latest or top feed."""
        items = []

        try:
            url = f"{self.DISCOURSE_URL}/{feed}.json"
            resp = self.session.get(url, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            for topic in data.get('topic_list', {}).get('topics', [])[:20]:
                if topic['id'] in seen_ids:
                    continue
                seen_ids.add(topic['id'])

                item = self._parse_topic(topic, None)
                if item:
                    items.append(item)

            self.log_info(f"Fetched {len(items)} topics from {feed}")
        except Exception as e:
            self.log_error(f"Error fetching {feed}: {e}")

        return items

    def _parse_topic(self, topic: dict, category: str = None) -> Optional[NewsItem]:
        """Parse a single Discourse topic into NewsItem."""
        title = topic.get('title', '')
        slug = topic.get('slug', '')
        topic_id = topic['id']
        topic_url = f"{self.DISCOURSE_URL}/t/{slug}/{topic_id}"

        posts = topic.get('posts_count', 0)
        likes = topic.get('like_count', 0)
        views = topic.get('views', 0)

        # Filter old inactive topics
        max_age = self.get_config('filters.max_topic_age_days', 60)
        last_posted = topic.get('last_posted_at')
        if last_posted:
            try:
                last_date = datetime.fromisoformat(last_posted.replace('Z', '+00:00'))
                age_days = (datetime.now(last_date.tzinfo) - last_date).days
                if age_days > max_age:
                    return None
            except:
                pass

        tags = ['discussion']
        if category:
            tags.append(category)

        # Check if RFC
        is_rfc = category == 'rfc' or '[RFC]' in title.upper()
        if is_rfc:
            tags.append('rfc')

        return NewsItem(
            source='discourse',
            title=title,
            url=topic_url,
            date=topic.get('created_at'),
            summary=f"Replies: {posts} | Views: {views} | Likes: {likes}",
            importance='low',  # Will be re-evaluated by analyzer
            tags=tags,
            raw_data={
                'posts_count': posts,
                'like_count': likes,
                'views': views,
                'category': category,
                'is_rfc': is_rfc
            }
        )
