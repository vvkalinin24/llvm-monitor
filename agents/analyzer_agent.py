"""
Analyzer Agent - Analyzes and prioritizes collected items.
"""

from .base import ProcessorAgent, NewsItem


class AnalyzerAgent(ProcessorAgent):
    """
    Agent for analyzing and prioritizing news items.

    Responsibilities:
    - Determine importance (high/medium/low)
    - Extract and assign tags
    - Filter duplicates
    - Filter by configured components
    """

    # Default keywords if not in config
    DEFAULT_HIGH_KEYWORDS = [
        'amdgpu', 'amd', 'rocm', 'hip', 'gpu',
        'breaking', 'security', 'vulnerability', 'cve',
        'critical', 'deprecat', 'removed', 'backend'
    ]

    DEFAULT_MEDIUM_KEYWORDS = [
        'clang', 'mlir', 'codegen', 'llvm',
        'optimization', 'performance', 'release',
        'new feature', 'lldb', 'lld', 'flang'
    ]

    TAG_PATTERNS = {
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

    def __init__(self, config: dict = None):
        super().__init__("analyzer", config)

        # Build keyword sets from config
        self.high_keywords = set(
            self.get_config('high_priority_keywords', self.DEFAULT_HIGH_KEYWORDS)
        )
        self.medium_keywords = set(
            self.get_config('medium_priority_keywords', self.DEFAULT_MEDIUM_KEYWORDS)
        )

        # Add tracked components as high priority
        components = self.get_config('components', [])
        for comp in components:
            self.high_keywords.add(comp.lower())

    def process(self, items: list[NewsItem]) -> list[NewsItem]:
        """Process and prioritize items."""
        self.log_info(f"Analyzing {len(items)} items...")

        # Remove duplicates by URL
        seen_urls = set()
        unique_items = []
        for item in items:
            if item.url not in seen_urls:
                seen_urls.add(item.url)
                unique_items.append(item)

        self.log_info(f"Removed {len(items) - len(unique_items)} duplicates")

        # Analyze each item
        analyzed = []
        for item in unique_items:
            analyzed_item = self._analyze_item(item)
            analyzed.append(analyzed_item)

        # Sort by importance
        priority = {'high': 0, 'medium': 1, 'low': 2}
        analyzed.sort(key=lambda x: (priority[x.importance], x.date or ''))

        # Log summary
        high_count = sum(1 for i in analyzed if i.importance == 'high')
        medium_count = sum(1 for i in analyzed if i.importance == 'medium')
        low_count = sum(1 for i in analyzed if i.importance == 'low')
        self.log_info(f"Analysis complete: {high_count} high, {medium_count} medium, {low_count} low")

        return analyzed

    def _analyze_item(self, item: NewsItem) -> NewsItem:
        """Analyze a single item and update its importance and tags."""
        # Build text to analyze
        text = f"{item.title} {item.summary}".lower()

        # Determine importance
        importance = self._determine_importance(item, text)

        # Extract additional tags
        tags = self._extract_tags(text, item.tags)

        # Create updated item
        return NewsItem(
            source=item.source,
            title=item.title,
            url=item.url,
            date=item.date,
            summary=item.summary,
            importance=importance,
            tags=tags,
            raw_data=item.raw_data
        )

    def _determine_importance(self, item: NewsItem, text: str) -> str:
        """Determine importance level."""
        # Check for high priority keywords
        for keyword in self.high_keywords:
            if keyword in text:
                return 'high'

        # Check raw_data for special cases
        raw = item.raw_data

        # RFCs are always high priority
        if raw.get('is_rfc'):
            return 'high'

        # Hot discussions
        if raw.get('posts_count', 0) > 50 or raw.get('like_count', 0) > 50:
            return 'high'

        # Active discussions
        if raw.get('posts_count', 0) > 30 or raw.get('comments', 0) > 20:
            return 'medium'

        # Check for medium priority keywords
        for keyword in self.medium_keywords:
            if keyword in text:
                return 'medium'

        # Releases are at least medium
        if item.source == 'github-releases':
            return 'medium'

        return 'low'

    def _extract_tags(self, text: str, existing_tags: list[str]) -> list[str]:
        """Extract tags from text."""
        tags = set(existing_tags)

        for tag, patterns in self.TAG_PATTERNS.items():
            if any(p in text for p in patterns):
                tags.add(tag)

        return list(tags)
