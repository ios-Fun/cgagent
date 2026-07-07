"""Schema definitions for parse_report skill."""

from typing import TypedDict, List, Optional, Dict, Any


class IndicatorResult(TypedDict):
    """Single indicator result."""
    name: str
    value: float
    unit: str
    status: str  # "normal" | "high" | "low"
    deviation_percent: float
    ref_low: Optional[float]
    ref_high: Optional[float]


class BasicInfoResult(TypedDict):
    """Basic information result."""
    bmi: Dict[str, Any]
    blood_pressure: Dict[str, Any]


class ParseReportStructured(TypedDict):
    """Structured output from parse_report."""
    basic_info: BasicInfoResult
    indicators: List[IndicatorResult]
    summary: Dict[str, Any]


class ParseReportOutput(TypedDict):
    """Full output from parse_report skill."""
    structured: ParseReportStructured
    text: str
    metadata: Dict[str, Any]
