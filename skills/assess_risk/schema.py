"""Schema definitions for assess_risk skill."""

from typing import TypedDict, List, Dict, Any


class RiskDimension(TypedDict):
    """Risk assessment for one dimension."""
    score: int
    level: str
    factors: List[str]


class OverallRisk(TypedDict):
    """Overall risk assessment."""
    score: float
    level: str
    recommendation: str


class AssessRiskStructured(TypedDict):
    """Structured output from assess_risk."""
    risk_scores: Dict[str, RiskDimension]
    overall_risk: OverallRisk


class AssessRiskOutput(TypedDict):
    """Full output from assess_risk skill."""
    structured: AssessRiskStructured
    text: str
    metadata: Dict[str, Any]
