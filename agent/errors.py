"""Error definitions for Agent Skills Framework."""


class AgentError(Exception):
    """Base error class for Agent Skills Framework."""

    def __init__(self, message: str, recoverable: bool = True):
        self.recoverable = recoverable
        super().__init__(message)


class SkillNotFoundError(AgentError):
    """Raised when a requested Skill is not found."""

    def __init__(self, skill_name: str):
        self.skill_name = skill_name
        super().__init__(f"Skill not found: {skill_name}", recoverable=False)


class SkillExecutionError(AgentError):
    """Raised when Skill execution fails."""

    def __init__(
        self,
        skill_name: str,
        message: str,
        recoverable: bool = True,
        details: dict = None
    ):
        self.skill_name = skill_name
        self.details = details or {}
        super().__init__(f"[{skill_name}] {message}", recoverable)


class TokenBudgetExceeded(AgentError):
    """Raised when token budget is exceeded."""

    def __init__(self, message: str, used: int = 0, limit: int = 0):
        self.used = used
        self.limit = limit
        super().__init__(message, recoverable=False)


class ContextValidationError(AgentError):
    """Raised when context validation fails."""

    def __init__(self, message: str, field: str = None):
        self.field = field
        super().__init__(f"Context validation failed: {message}", recoverable=False)


class PlannerError(AgentError):
    """Raised when planning fails."""

    def __init__(self, message: str, details: dict = None):
        self.details = details or {}
        super().__init__(f"Planning error: {message}", recoverable=True)


class ExecutorError(AgentError):
    """Raised when executor encounters critical error."""

    def __init__(self, message: str, step: dict = None):
        self.step = step or {}
        super().__init__(f"Executor error: {message}", recoverable=True)
