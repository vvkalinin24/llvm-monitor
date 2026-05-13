"""
SemiAnalysis Agent - Monitors SemiAnalysis newsletter for AMD-related news.
"""

import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime

from .base import CollectorAgent, NewsItem


class SemiAnalysisAgent(CollectorAgent):
    """
    Agent for collecting AMD-related articles from SemiAnalysis newsletter.
    """

    ARCHIVE_URL = "https://www.semianalysis.com/archive"

    AMD_KEYWORDS = [
        'amd', 'radeon', 'epyc', 'ryzen', 'instinct', 'mi300', 'mi400',
        'rocm', 'hip', 'cdna', 'rdna', 'zen', 'genoa', 'bergamo', 'turin',
        'xilinx', 'alveo', 'versal', 'lisa su', 'advanced micro devices'
    ]

    RELATED_KEYWORDS = [
        'nvidia', 'intel', 'gpu', 'ai chip', 'datacenter', 'hpc',
        'semiconductor', 'tsmc', 'hbm', 'chiplet', 'ai accelerator',
        'training', 'inference', 'llm', 'compute'
    ]

    def __init__(self, config: dict = None):
        super().__init__("semianalysis", config)

        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'LLVM-Monitor-Agent/2.0'
        })

    def fetch(self) -> list[NewsItem]:
        """Fetch AMD-related articles from SemiAnalysis."""
        items = []

        try:
            resp = self.session.get(self.ARCHIVE_URL, timeout=30)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')

            for article in soup.find_all('a', href=re.compile(r'semianalysis\.com/\d{4}/\d{2}/\d{2}/')):
                item = self._parse_article(article)
                if item:
                    items.append(item)

            self.log_info(f"Fetched {len(items)} AMD-related articles from SemiAnalysis")
        except Exception as e:
            self.log_error(f"Error fetching SemiAnalysis: {e}")

        return items

    def _parse_article(self, article_elem) -> NewsItem:
        """Parse a single article element and filter for AMD relevance."""
        try:
            url = article_elem.get('href', '')
            if not url:
                return None

            title = article_elem.get_text(strip=True)
            if not title:
                return None

            # Extract date from URL pattern: /2025/09/16/
            date_match = re.search(r'/(\d{4})/(\d{2})/(\d{2})/', url)
            date_str = None
            if date_match:
                year, month, day = date_match.groups()
                date_str = f"{year}-{month}-{day}"

            # Check AMD relevance
            title_lower = title.lower()
            url_lower = url.lower()
            combined_text = f"{title_lower} {url_lower}"

            # Direct AMD mention = high priority
            is_amd_direct = any(kw in combined_text for kw in self.AMD_KEYWORDS)

            # Related topics (competitors, industry) = medium priority
            is_related = any(kw in combined_text for kw in self.RELATED_KEYWORDS)

            if not is_amd_direct and not is_related:
                return None

            # Determine importance
            if is_amd_direct:
                importance = 'high'
                tags = ['semianalysis', 'amd', 'industry']
            else:
                importance = 'medium'
                tags = ['semianalysis', 'industry', 'competitor']

            return NewsItem(
                source='semianalysis',
                title=f"[SemiAnalysis] {title}",
                url=url,
                date=date_str,
                summary=f"Industry analysis article. AMD relevance: {'direct' if is_amd_direct else 'related'}",
                importance=importance,
                tags=tags,
                raw_data={'is_amd_direct': is_amd_direct}
            )

        except Exception as e:
            self.log_error(f"Error parsing article: {e}")
            return None

    def fetch_article_content(self, url: str) -> str:
        """Fetch full article content for deeper analysis."""
        try:
            resp = self.session.get(url, timeout=30)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')

            # Find main content
            content = soup.find('article') or soup.find('div', class_=re.compile(r'post|content|body'))
            if content:
                return content.get_text(strip=True)[:2000]
            return ""
        except Exception as e:
            self.log_error(f"Error fetching article content: {e}")
            return ""
