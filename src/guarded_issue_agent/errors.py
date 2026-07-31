"""Expected, user-facing failures for the guarded pipeline."""


class GuardedAgentError(Exception):
    """Base class for failures that should be shown without a traceback."""


class InputValidationError(GuardedAgentError):
    """An issue, plan, path, or configuration failed validation."""


class PolicyViolation(GuardedAgentError):
    """A proposed operation crossed a configured safety boundary."""


class PlanningError(GuardedAgentError):
    """The model adapter could not produce an unambiguous plan."""


class PlanIntegrityError(GuardedAgentError):
    """A saved plan no longer matches its recorded digest."""


class ApprovalError(GuardedAgentError):
    """The operator did not approve the exact saved plan."""


class StalePlanError(GuardedAgentError):
    """The workspace changed after evidence was collected."""


class ApplyError(GuardedAgentError):
    """An approved plan could not be applied safely."""
