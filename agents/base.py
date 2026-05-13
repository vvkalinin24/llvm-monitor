"""
Base Agent class for LLVM Monitor multi-agent system.
All agents inherit from this base class.
"""

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from enum import Enum


class MessageType(Enum):
    """Types of messages agents can exchange."""
    TASK = "task"
    RESULT = "result"
    ERROR = "error"
    STATUS = "status"


@dataclass
class AgentMessage:
    """Message passed between agents."""
    sender: str
    receiver: str
    msg_type: MessageType
    payload: dict
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    correlation_id: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d['msg_type'] = self.msg_type.value
        return d

    @classmethod
    def from_dict(cls, data: dict) -> 'AgentMessage':
        data['msg_type'] = MessageType(data['msg_type'])
        return cls(**data)


@dataclass
class NewsItem:
    """Represents a single news/update item."""
    source: str
    title: str
    url: str
    date: Optional[str]
    summary: str
    importance: str  # high, medium, low
    tags: list[str]
    raw_data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'NewsItem':
        return cls(**data)


class BaseAgent(ABC):
    """
    Base class for all agents in the system.

    Each agent has:
    - A unique name
    - Ability to send/receive messages
    - Logging
    - Configuration access
    """

    def __init__(self, name: str, config: dict = None):
        self.name = name
        self.config = config or {}
        self.logger = logging.getLogger(f"agent.{name}")
        self._message_queue: list[AgentMessage] = []
        self._results: list[Any] = []

    @abstractmethod
    def run(self, task: dict = None) -> dict:
        """
        Execute the agent's main task.

        Args:
            task: Optional task parameters

        Returns:
            Result dictionary
        """
        pass

    def send_message(self, receiver: str, msg_type: MessageType,
                     payload: dict, correlation_id: str = "") -> AgentMessage:
        """Create and return a message to send to another agent."""
        msg = AgentMessage(
            sender=self.name,
            receiver=receiver,
            msg_type=msg_type,
            payload=payload,
            correlation_id=correlation_id
        )
        self.logger.debug(f"Sending {msg_type.value} to {receiver}")
        return msg

    def receive_message(self, message: AgentMessage):
        """Receive and queue a message from another agent."""
        self._message_queue.append(message)
        self.logger.debug(f"Received {message.msg_type.value} from {message.sender}")

    def process_messages(self) -> list[dict]:
        """Process all queued messages and return results."""
        results = []
        while self._message_queue:
            msg = self._message_queue.pop(0)
            result = self._handle_message(msg)
            if result:
                results.append(result)
        return results

    def _handle_message(self, message: AgentMessage) -> Optional[dict]:
        """Handle a single message. Override in subclasses for custom handling."""
        if message.msg_type == MessageType.TASK:
            return self.run(message.payload)
        return None

    def get_config(self, key: str, default: Any = None) -> Any:
        """Get a configuration value."""
        keys = key.split('.')
        value = self.config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k, default)
            else:
                return default
        return value

    def log_info(self, message: str):
        self.logger.info(f"[{self.name}] {message}")

    def log_error(self, message: str):
        self.logger.error(f"[{self.name}] {message}")

    def log_debug(self, message: str):
        self.logger.debug(f"[{self.name}] {message}")


class CollectorAgent(BaseAgent):
    """
    Base class for agents that collect data from external sources.
    """

    def __init__(self, name: str, config: dict = None):
        super().__init__(name, config)
        self.items: list[NewsItem] = []

    @abstractmethod
    def fetch(self) -> list[NewsItem]:
        """Fetch items from the data source."""
        pass

    def run(self, task: dict = None) -> dict:
        """Run the collector and return results."""
        self.log_info("Starting data collection...")
        try:
            self.items = self.fetch()
            self.log_info(f"Collected {len(self.items)} items")
            return {
                "status": "success",
                "agent": self.name,
                "count": len(self.items),
                "items": [item.to_dict() for item in self.items]
            }
        except Exception as e:
            self.log_error(f"Collection failed: {e}")
            return {
                "status": "error",
                "agent": self.name,
                "error": str(e),
                "items": []
            }


class ProcessorAgent(BaseAgent):
    """
    Base class for agents that process/transform data.
    """

    @abstractmethod
    def process(self, items: list[NewsItem]) -> list[NewsItem]:
        """Process items and return transformed items."""
        pass

    def run(self, task: dict = None) -> dict:
        """Run the processor on provided items."""
        items_data = task.get('items', []) if task else []
        items = [NewsItem.from_dict(i) for i in items_data]

        self.log_info(f"Processing {len(items)} items...")
        try:
            processed = self.process(items)
            self.log_info(f"Processed into {len(processed)} items")
            return {
                "status": "success",
                "agent": self.name,
                "count": len(processed),
                "items": [item.to_dict() for item in processed]
            }
        except Exception as e:
            self.log_error(f"Processing failed: {e}")
            return {
                "status": "error",
                "agent": self.name,
                "error": str(e),
                "items": items_data
            }
