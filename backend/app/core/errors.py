"""Domain errors for project upload, extraction and inspection."""


class ProjectError(Exception):
    """Base error carrying a user-safe message, HTTP status and machine-readable code."""

    default_code: str = "project_error"

    def __init__(
        self, message: str, status_code: int = 400, code: str | None = None
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code or self.default_code


class UploadError(ProjectError):
    default_code = "upload_error"
    """The upload itself was rejected (type, size, not a ZIP)."""


class ExtractionError(ProjectError):
    default_code = "extraction_error"
    """The archive is malformed, unsafe or exceeds extraction limits."""


class ProjectNotFoundError(ProjectError):
    default_code = "project_not_found"
    def __init__(self, message: str = "Project not found.") -> None:
        super().__init__(message, 404)


class ScanError(ProjectError):
    default_code = "scan_error"
    """Static analysis scan could not be completed or loaded."""


class ScanNotFoundError(ProjectError):
    default_code = "scan_not_found"
    def __init__(self, message: str = "No scan results found for this project.") -> None:
        super().__init__(message, 404)


class AnalysisError(ProjectError):
    default_code = "analysis_error"
    """AI root cause analysis failed or could not be read."""


class AnalysisNotFoundError(ProjectError):
    default_code = "analysis_not_found"
    def __init__(self, message: str = "No analysis results found for this project.") -> None:
        super().__init__(message, 404)
        if message == "Analysis item not found.":
            self.code = "analysis_item_not_found"


class LLMConfigurationError(AnalysisError):
    default_code = "llm_not_configured"
    def __init__(
        self,
        message: str = "LLM provider is not configured. Set ROOTPATCH_LLM_API_KEY or provider API key.",
    ) -> None:
        super().__init__(message, 503)


class LLMRateLimitError(AnalysisError):
    default_code = "llm_rate_limited"
    def __init__(self, message: str = "LLM provider rate limit exceeded.") -> None:
        super().__init__(message, 429)


class LLMTimeoutError(AnalysisError):
    default_code = "llm_timeout"
    def __init__(self, message: str = "LLM provider request timed out.") -> None:
        super().__init__(message, 504)


class LLMProviderError(AnalysisError):
    default_code = "llm_provider_error"
    def __init__(self, message: str = "LLM provider request failed.", status_code: int = 502) -> None:
        super().__init__(message, status_code)


class PatchError(ProjectError):
    default_code = "patch_error"
    """Automated patch generation failed or persisted patches could not be read."""


class PatchNotFoundError(ProjectError):
    default_code = "patches_not_found"
    def __init__(self, message: str = "No generated patches found for this project.") -> None:
        super().__init__(message, 404)
        if message != "No generated patches found for this project.":
            self.code = "patch_not_found"


class PatchValidationError(PatchError):
    default_code = "patch_invalid"
    def __init__(
        self,
        message: str = "Generated patch failed safety or unified diff validation.",
    ) -> None:
        super().__init__(message, 422)


class PatchConflictError(PatchError):
    default_code = "patch_conflict"
    def __init__(
        self,
        message: str = "Patch cannot transition from its current state.",
    ) -> None:
        super().__init__(message, 409)


class PatchApplicationError(PatchError):
    default_code = "patch_apply_failed"
    def __init__(
        self,
        message: str = "Failed to apply patch safely; original source file was preserved.",
    ) -> None:
        super().__init__(message, 500)


class TestValidationError(ProjectError):
    default_code = "validation_error"
    """Patch test validation failed or received an invalid validation configuration."""

    __test__ = False

    def __init__(
        self,
        message: str = "Patch test validation could not be completed.",
        status_code: int = 422,
    ) -> None:
        super().__init__(message, status_code)


class ValidationNotFoundError(ProjectError):
    default_code = "validation_not_found"
    def __init__(self, message: str = "Validation report not found.") -> None:
        super().__init__(message, 404)


class ValidationConflictError(TestValidationError):
    default_code = "validation_conflict"
    def __init__(
        self,
        message: str = "Only applied patches can be validated.",
    ) -> None:
        super().__init__(message, 409)


class ValidationIsolationError(TestValidationError):
    default_code = "validation_isolation_unavailable"
    def __init__(
        self,
        message: str = "Isolated container execution environment is unavailable; host execution is disabled.",
    ) -> None:
        super().__init__(message, 503)
