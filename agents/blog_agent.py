"""
Blog Agent - Parses LLVM blog for posts.
"""

import re
import requests
from bs4 import BeautifulSoup

from .base import CollectorAgent, NewsItem


class BlogAgent(CollectorAgent):
    """
    Agent for collecting posts from LLVM blog.
    """

    BLOG_URL = "https://blog.llvm.org/"

    def __init__(self, config: dict = None):
        super().__init__("blog", config)

        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'LLVM-Monitor-Agent/2.0'
        })

    def fetch(self) -> list[NewsItem]:
        """Fetch blog posts."""
        items = []

        try:
            resp = self.session.get(self.BLOG_URL, timeout=30)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')

            # Find article elements
            for article in soup.find_all(['article', 'div'],
                                         class_=re.compile(r'post|entry|article')):
                item = self._parse_article(article)
                if item:
                    items.append(item)

            self.log_info(f"Fetched {len(items)} blog posts")
        except Exception as e:
            self.log_error(f"Error fetching blog: {e}")

        return items

    def _parse_article(self, article) -> NewsItem:
        """Parse a single blog article."""
        # Find title
        title_elem = article.find(['h1', 'h2', 'h3', 'a'])
        if not title_elem:
            return None

        title = title_elem.get_text(strip=True)
        if not title:
            return None

        # Find link
        link = title_elem.get('href')
        if not link:
            link_elem = title_elem.find('a')
            link = link_elem.get('href') if link_elem else ''

        if link and not link.startswith('http'):
            link = f"{self.BLOG_URL.rstrip('/')}/{link.lstrip('/')}"

        # Find date
        date_elem = article.find(['time', 'span'], class_=re.compile(r'date|time'))
        date_str = date_elem.get_text(strip=True) if date_elem else None

        # Find summary
        summary_elem = article.find(['p', 'div'], class_=re.compile(r'summary|excerpt|content'))
        summary = summary_elem.get_text(strip=True)[:300] if summary_elem else ''

        return NewsItem(
            source='blog',
            title=title,
            url=link or self.BLOG_URL,
            date=date_str,
            summary=summary,
            importance='low',  # Will be re-evaluated by analyzer
            tags=['blog'],
            raw_data={}
        )
