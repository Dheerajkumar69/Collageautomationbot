from dataclasses import dataclass, field
from typing import List

@dataclass
class FeedbackItem:
    """Represents a single feedback form entry."""
    index: int
    title: str = "Unknown"
    submitted: bool = False
    skipped: bool = False
    error: str = ""

@dataclass
class Subject:
    """Represents a subject with pending feedback."""
    name: str
    pending_count: int = 0
    items: List[FeedbackItem] = field(default_factory=list)
    processed: bool = False

@dataclass
class ProgressSummary:
    """Summary of feedback automation progress."""
    total_subjects_found: int = 0
    total_pending_found: int = 0
    total_submitted: int = 0
    total_skipped: int = 0
    total_failed: int = 0
