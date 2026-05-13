"""
LLVM Monitor Multi-Agent System

This package contains specialized agents for monitoring the LLVM ecosystem:

- Orchestrator: Coordinates all other agents
- GitHubAgent: Fetches data from GitHub (releases, commits, issues, PRs)
- DiscourseAgent: Fetches discussions from LLVM Discourse
- BlogAgent: Parses LLVM blog posts
- AnalyzerAgent: Analyzes and prioritizes collected items
- ReporterAgent: Generates reports in various formats
"""

from .base import (
    BaseAgent,
    CollectorAgent,
    ProcessorAgent,
    AgentMessage,
    MessageType,
    NewsItem
)
from .github_agent import GitHubAgent
from .discourse_agent import DiscourseAgent
from .blog_agent import BlogAgent
from .analyzer_agent import AnalyzerAgent
from .reporter_agent import ReporterAgent
from .orchestrator import Orchestrator

__all__ = [
    'BaseAgent',
    'CollectorAgent',
    'ProcessorAgent',
    'AgentMessage',
    'MessageType',
    'NewsItem',
    'GitHubAgent',
    'DiscourseAgent',
    'BlogAgent',
    'AnalyzerAgent',
    'ReporterAgent',
    'Orchestrator',
]
