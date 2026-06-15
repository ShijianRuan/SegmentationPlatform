class SegPlatformError(RuntimeError):
    """Expected user-facing workflow error."""


class ValidationError(SegPlatformError):
    """A contract or QC validation failed."""


class ConfigurationError(SegPlatformError):
    """A workstation or workflow configuration is invalid."""

