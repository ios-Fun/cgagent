"""Schema definitions for generate_advice skill."""

from typing import TypedDict, List, Dict, Any


class AdviceItem(TypedDict):
    """A single advice item."""
    category: str
    priority: str
    content: str


class FollowupPlan(TypedDict):
    """Follow-up plan."""
    timing: str
    items: List[str]
    note: str


class GenerateAdviceStructured(TypedDict):
    """Structured output from generate_advice."""
    advice_items: List[AdviceItem]
    followup_plan: FollowupPlan


class GenerateAdviceOutput(TypedDict):
    """Full output from generate_advice skill."""
    structured: GenerateAdviceStructured
    text: str
    metadata: Dict[str, Any]
