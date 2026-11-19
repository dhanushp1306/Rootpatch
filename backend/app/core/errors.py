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
