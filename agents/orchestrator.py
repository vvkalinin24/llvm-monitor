"""
Orchestrator Agent - Coordinates all other agents in the system.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

from .base import BaseAgent, AgentMessage, MessageType, NewsItem
from .github_agent import GitHubAgent
from .discourse_agent import DiscourseAgent
from .blog_agent import BlogAgent
from .analyzer_agent import AnalyzerAgent
from .reporter_agent import ReporterAgent


class Orchestrator(BaseAgent):
    """
    Main orchestrator that coordinates all agents.

    Workflow:
    1. Spawn collector agents (GitHub, Discourse, Blog) in parallel
    2. Aggregate collected items
    3. Send to Analyzer agent for prioritization
    4. Send to Reporter agent for report generation
    5. Handle notifications
    """

    def __init__(self, config: dict = None):
        super().__init__("orchestrator", config)

        # State file for tracking seen items
        self.state_file = Path(self.get_config('state_file', 'llvm_monitor_state.json'))
        self.state = self._load_state()

        # Initialize all agents
        self.agents = {
            'github': GitHubAgent(config),
            'discourse': DiscourseAgent(config),
            'blog': BlogAgent(config),
            'analyzer': AnalyzerAgent(config),
            'reporter': ReporterAgent(config),
        }

        self.log_info(f"Initialized with {len(self.agents)} agents")

    def _load_state(self) -> dict:
        """Load state from file."""
        if self.state_file.exists():
            return json.loads(self.state_file.read_text())
        return {
            'seen_ids': [],
            'last_check': None,
        }

    def _save_state(self):
        """Save state to file."""
        self.state['last_check'] = datetime.now().isoformat()
        self.state_file.write_text(json.dumps(self.state, indent=2))

    def run(self, task: dict = None) -> dict:
        """
        Run the full monitoring pipeline.

        Args:
            task: Optional task parameters
                - include_seen: bool - Include already seen items
                - format: str - Report format (markdown/text/json)
                - output_path: str - Where to save the report
        """
        task = task or {}
        include_seen = task.get('include_seen', False)
        report_format = task.get('format', 'markdown')
        output_path = task.get('output_path')

        self.log_info("=" * 50)
        self.log_info("Starting LLVM Monitor pipeline")
        self.log_info("=" * 50)

        # Step 1: Collect data from all sources in parallel
        self.log_info("Step 1: Collecting data...")
        all_items = self._collect_parallel()
        self.log_info(f"Collected {len(all_items)} total items")

        # Step 2: Filter seen items
        if not include_seen:
            new_items = self._filter_seen(all_items)
            self.log_info(f"After filtering seen: {len(new_items)} new items")
        else:
            new_items = all_items

        # Step 3: Analyze and prioritize
        self.log_info("Step 2: Analyzing items...")
        analyzer = self.agents['analyzer']
        analyze_result = analyzer.run({'items': [i.to_dict() for i in new_items]})

        if analyze_result['status'] != 'success':
            self.log_error(f"Analysis failed: {analyze_result.get('error')}")
            return analyze_result

        analyzed_items = [NewsItem.from_dict(i) for i in analyze_result['items']]

        # Step 4: Generate report
        self.log_info("Step 3: Generating report...")
        reporter = self.agents['reporter']
        report_result = reporter.run({
            'items': [i.to_dict() for i in analyzed_items],
            'format': report_format,
            'output_path': output_path
        })

        # Step 5: Update state
        self._update_state(analyzed_items)
        self._save_state()

        # Summary
        high_count = sum(1 for i in analyzed_items if i.importance == 'high')
        medium_count = sum(1 for i in analyzed_items if i.importance == 'medium')
        low_count = sum(1 for i in analyzed_items if i.importance == 'low')

        self.log_info("=" * 50)
        self.log_info(f"Pipeline complete!")
        self.log_info(f"  Total: {len(analyzed_items)} items")
        self.log_info(f"  High: {high_count}, Medium: {medium_count}, Low: {low_count}")
        self.log_info("=" * 50)

        return {
            "status": "success",
            "agent": self.name,
            "summary": {
                "total": len(analyzed_items),
                "high": high_count,
                "medium": medium_count,
                "low": low_count,
            },
            "report": report_result.get('report', ''),
            "output_path": report_result.get('output_path'),
            "items": [i.to_dict() for i in analyzed_items]
        }

    def _collect_parallel(self) -> list[NewsItem]:
        """Run collector agents in parallel."""
        collectors = ['github', 'discourse', 'blog']
        enabled_sources = self.get_config('sources', {})

        # Filter to enabled collectors
        active_collectors = []
        for name in collectors:
            source_key = {
                'github': 'github_releases',  # Just check one github source
                'discourse': 'discourse',
                'blog': 'blog'
            }.get(name, name)

            if enabled_sources.get(source_key, True):
                active_collectors.append(name)

        self.log_info(f"Running collectors: {active_collectors}")

        all_items = []

        # Run in parallel
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {}
            for name in active_collectors:
                agent = self.agents[name]
                future = executor.submit(agent.run)
                futures[future] = name

            for future in as_completed(futures):
                name = futures[future]
                try:
                    result = future.result()
                    if result['status'] == 'success':
                        items = [NewsItem.from_dict(i) for i in result['items']]
                        all_items.extend(items)
                        self.log_info(f"  {name}: {len(items)} items")
                    else:
                        self.log_error(f"  {name}: failed - {result.get('error')}")
                except Exception as e:
                    self.log_error(f"  {name}: exception - {e}")

        return all_items

    def _filter_seen(self, items: list[NewsItem]) -> list[NewsItem]:
        """Filter out already seen items."""
        import hashlib

        new_items = []
        for item in items:
            item_id = hashlib.md5(f"{item.source}:{item.url}".encode()).hexdigest()
            if item_id not in self.state['seen_ids']:
                new_items.append(item)
        return new_items

    def _update_state(self, items: list[NewsItem]):
        """Update state with newly seen items."""
        import hashlib

        for item in items:
            item_id = hashlib.md5(f"{item.source}:{item.url}".encode()).hexdigest()
            if item_id not in self.state['seen_ids']:
                self.state['seen_ids'].append(item_id)

        # Limit history size
        self.state['seen_ids'] = self.state['seen_ids'][-2000:]

    def get_agent(self, name: str) -> Optional[BaseAgent]:
        """Get an agent by name."""
        return self.agents.get(name)

    def call_agent(self, agent_name: str, task: dict = None) -> dict:
        """
        Call a specific agent with a task.

        This allows external callers to invoke specific agents through the orchestrator.
        """
        agent = self.agents.get(agent_name)
        if not agent:
            return {
                "status": "error",
                "error": f"Unknown agent: {agent_name}"
            }

        self.log_info(f"Calling agent: {agent_name}")
        return agent.run(task)
