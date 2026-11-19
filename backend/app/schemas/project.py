"""Schemas for project upload, inspection and structure endpoints."""

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class LanguageInfo(BaseModel):
    """A language reported only when source files with its extensions exist."""

    name: str
    file_count: int
    extensions: List[str]
    example_files: List[str]


class SourceDirectory(BaseModel):
    path: str
    source_file_count: int


class ProjectFile(BaseModel):
    path: str
    name: str
    ecosystem: Optional[str] = None


class TopLevelEntry(BaseModel):
    name: str
    type: Literal["file", "directory"]


class InspectionReport(BaseModel):
    project_id: str
    project_name: str
    root_directory: str
    total_files: int
    total_directories: int
    total_size_bytes: int
    file_extensions: Dict[str, int]
    languages: List[LanguageInfo]
    python_detected: bool
    source_directories: List[SourceDirectory]
    configuration_files: List[ProjectFile]
    dependency_manifests: List[ProjectFile]
    documentation_files: List[str]
    test_directories: List[str]
    test_files: List[str]
    test_file_count: int
    top_level_entries: List[TopLevelEntry]
    warnings: List[str] = Field(default_factory=list)


class ArchiveInfo(BaseModel):
    files_extracted: int
    extracted_bytes: int
    skipped_entries: int


class ProjectMetadata(BaseModel):
    project_id: str
    project_name: str
    original_filename: str
    created_at: str
    status: str
    archive: ArchiveInfo
    inspection: InspectionReport


class UploadResponse(BaseModel):
    project_id: str
    project_name: str
    status: str
    message: str


class StructureNode(BaseModel):
    name: str
    path: str
    type: Literal["file", "directory"]
    size_bytes: Optional[int] = None
    children: Optional[List["StructureNode"]] = None


StructureNode.model_rebuild()


class StructureResponse(BaseModel):
    project_id: str
    root_directory: str
    total_nodes: int
    truncated: bool
    tree: StructureNode
