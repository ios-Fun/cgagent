"""Tool system for Agent Skills Framework - Everything is a Tool."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from dataclasses import dataclass


@dataclass
class ToolInput:
    """Tool input definition."""
    name: str
    type: str  # "string" | "number" | "boolean" | "object" | "array"
    description: str = ""
    required: bool = True
    default: Any = None


@dataclass
class ToolOutput:
    """Tool output definition."""
    type: str
    description: str = ""


@dataclass
class ToolSpec:
    """Tool specification."""
    name: str
    description: str
    inputs: Dict[str, ToolInput]
    output: ToolOutput
    category: str = "general"


class Tool(ABC):
    """Abstract base class for tools.

    Everything is a Tool - whether it's an API call, knowledge source
    retrieval, or code script execution.
    """

    @property
    @abstractmethod
    def spec(self) -> ToolSpec:
        """Get tool specification."""
        pass

    @abstractmethod
    def execute(self, **kwargs) -> Any:
        """Execute the tool.

        Args:
            **kwargs: Tool input parameters

        Returns:
            Tool output
        """
        pass

    def validate_inputs(self, **kwargs) -> bool:
        """Validate input parameters.

        Args:
            **kwargs: Input parameters to validate

        Returns:
            True if valid

        Raises:
            ValueError: If validation fails
        """
        for name, input_spec in self.spec.inputs.items():
            if input_spec.required and name not in kwargs:
                raise ValueError(f"Required input missing: {name}")

            # Type validation
            if name in kwargs:
                value = kwargs[name]
                expected_type = input_spec.type
                actual_type = type(value).__name__

                type_map = {
                    "string": str,
                    "number": (int, float),
                    "boolean": bool,
                    "object": dict,
                    "array": list
                }

                if expected_type in type_map:
                    if not isinstance(value, type_map[expected_type]):
                        raise ValueError(
                            f"Invalid type for {name}: expected {expected_type}, got {actual_type}"
                        )

        return True


class ToolRegistry:
    """Registry for managing available tools."""

    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool.

        Args:
            tool: Tool instance to register
        """
        self._tools[tool.spec.name] = tool

    def unregister(self, name: str) -> bool:
        """Unregister a tool.

        Args:
            name: Tool name

        Returns:
            True if unregistered, False if not found
        """
        if name in self._tools:
            del self._tools[name]
            return True
        return False

    def get(self, name: str) -> Tool:
        """Get a tool by name.

        Args:
            name: Tool name

        Returns:
            Tool instance

        Raises:
            ValueError: If tool not found
        """
        if name not in self._tools:
            raise ValueError(f"Tool not found: {name}")
        return self._tools[name]

    def has(self, name: str) -> bool:
        """Check if tool exists.

        Args:
            name: Tool name

        Returns:
            True if exists
        """
        return name in self._tools

    def list_all(self) -> List[ToolSpec]:
        """List all tool specifications.

        Returns:
            List of tool specs
        """
        return [tool.spec for tool in self._tools.values()]

    def list_by_category(self, category: str) -> List[ToolSpec]:
        """List tools by category.

        Args:
            category: Category name

        Returns:
            List of tool specs in category
        """
        return [
            tool.spec for tool in self._tools.values()
            if tool.spec.category == category
        ]

    def execute(self, name: str, **kwargs) -> Any:
        """Execute a tool.

        Args:
            name: Tool name
            **kwargs: Tool parameters

        Returns:
            Tool output

        Raises:
            ValueError: If tool not found or inputs invalid
        """
        tool = self.get(name)
        tool.validate_inputs(**kwargs)
        return tool.execute(**kwargs)

    def get_summary(self) -> Dict:
        """Get registry summary.

        Returns:
            Summary dictionary
        """
        categories = {}
        for tool in self._tools.values():
            cat = tool.spec.category
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(tool.spec.name)

        return {
            "total_tools": len(self._tools),
            "categories": categories
        }


# ─── Example Tool Implementations ───

class ReferenceRangeChecker(Tool):
    """Check if a value is within reference range."""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="check_reference_range",
            description="Check if a value is within the reference range",
            inputs={
                "value": ToolInput("value", "number", "The value to check", required=True),
                "ref_low": ToolInput("ref_low", "number", "Lower reference limit", required=False),
                "ref_high": ToolInput("ref_high", "number", "Upper reference limit", required=False)
            },
            output=ToolOutput("object", "Status and deviation percent"),
            category="health"
        )

    def execute(self, **kwargs) -> Dict:
        value = kwargs["value"]
        ref_low = kwargs.get("ref_low")
        ref_high = kwargs.get("ref_high")

        if ref_low is not None and value < ref_low:
            status = "low"
            deviation_percent = ((ref_low - value) / ref_low) * 100 if ref_low != 0 else 0
        elif ref_high is not None and value > ref_high:
            status = "high"
            deviation_percent = ((value - ref_high) / ref_high) * 100 if ref_high != 0 else 0
        else:
            status = "normal"
            deviation_percent = 0

        return {
            "status": status,
            "deviation_percent": round(deviation_percent, 1)
        }


class BMICalculator(Tool):
    """Calculate Body Mass Index."""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="calculate_bmi",
            description="Calculate Body Mass Index from height and weight",
            inputs={
                "height_cm": ToolInput("height_cm", "number", "Height in centimeters", required=True),
                "weight_kg": ToolInput("weight_kg", "number", "Weight in kilograms", required=True)
            },
            output=ToolOutput("object", "BMI value and category"),
            category="health"
        )

    def execute(self, **kwargs) -> Dict:
        height_cm = kwargs["height_cm"]
        weight_kg = kwargs["weight_kg"]

        height_m = height_cm / 100
        bmi = weight_kg / (height_m * height_m)

        if bmi < 18.5:
            category = "偏瘦"
        elif bmi < 24:
            category = "正常"
        elif bmi < 28:
            category = "超重"
        else:
            category = "肥胖"

        return {
            "bmi": round(bmi, 1),
            "category": category
        }


class BloodPressureClassifier(Tool):
    """Classify blood pressure reading."""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="classify_blood_pressure",
            description="Classify blood pressure reading",
            inputs={
                "sbp": ToolInput("sbp", "number", "Systolic blood pressure", required=True),
                "dbp": ToolInput("dbp", "number", "Diastolic blood pressure", required=True)
            },
            output=ToolOutput("object", "Blood pressure category"),
            category="health"
        )

    def execute(self, **kwargs) -> Dict:
        sbp = kwargs["sbp"]
        dbp = kwargs["dbp"]

        if sbp >= 180 or dbp >= 110:
            category = "高血压3级"
        elif sbp >= 160 or dbp >= 100:
            category = "高血压2级"
        elif sbp >= 140 or dbp >= 90:
            category = "高血压1级"
        elif sbp >= 130 or dbp >= 85:
            category = "正常高值"
        elif sbp >= 90 and dbp >= 60:
            category = "正常"
        else:
            category = "低血压"

        return {
            "sbp": sbp,
            "dbp": dbp,
            "category": category
        }


def create_default_registry() -> ToolRegistry:
    """Create a tool registry with default tools."""
    registry = ToolRegistry()
    registry.register(ReferenceRangeChecker())
    registry.register(BMICalculator())
    registry.register(BloodPressureClassifier())
    return registry
