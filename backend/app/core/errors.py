"""Domain errors for project upload, extraction and inspection."""


class ProjectError(Exception):
    """Base error carrying a user-safe message and an HTTP status code."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class UploadError(ProjectError):
    """The upload itself was rejected (type, size, not a ZIP)."""


class ExtractionError(ProjectError):
    """The archive is malformed, unsafe or exceeds extraction limits."""


class ProjectNotFoundError(ProjectError):
    def __init__(self, message: str = "Project not found.") -> None:
        super().__init__(message, 404)


class ScanError(ProjectError):
    """Static analysis scan could not be completed or loaded."""


class ScanNotFoundError(ProjectError):
    def __init__(self, message: str = "No scan results found for this project.") -> None:
        super().__init__(message, 404)


class AnalysisError(ProjectError):
    """AI root cause analysis failed or could not be read."""


class AnalysisNotFoundError(ProjectError):
    def __init__(self, message: str = "No analysis results found for this project.") -> None:
        super().__init__(message, 404)


class LLMConfigurationError(AnalysisError):
    def __init__(
        self,
        message: str = "LLM provider is not configured. Set ROOTPATCH_LLM_API_KEY or provider API key.",
    ) -> None:
        super().__init__(message, 503)


class LLMRateLimitError(AnalysisError):
    def __init__(self, message: str = "LLM provider rate limit exceeded.") -> None:
        super().__init__(message, 429)


class LLMTimeoutError(AnalysisError):
    def __init__(self, message: str = "LLM provider request timed out.") -> None:
        super().__init__(message, 504)


class LLMProviderError(AnalysisError):
    def __init__(self, message: str = "LLM provider request failed.", status_code: int = 502) -> None:
        super().__init__(message, status_code)


class PatchError(ProjectError):
    """Automated patch generation failed or persisted patches could not be read."""


class PatchNotFoundError(ProjectError):
    def __init__(self, message: str = "No generated patches found for this project.") -> None:
        super().__init__(message, 404)


class PatchValidationError(PatchError):
    def __init__(
        self,
        message: str = "Generated patch failed safety or unified diff validation.",
    ) -> None:
        super().__init__(message, 422)


class PatchConflictError(PatchError):
    def __init__(
        self,
        message: str = "Patch cannot transition from its current state.",
    ) -> None:
        super().__init__(message, 409)


class PatchApplicationError(PatchError):
    def __init__(
        self,
        message: str = "Failed to apply patch safely; original source file was preserved.",
    ) -> None:
        super().__init__(message, 500)
