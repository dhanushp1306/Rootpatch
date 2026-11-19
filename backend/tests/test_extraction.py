import os
import stat
import zipfile

import pytest

from app.core.errors import ExtractionError
from app.services.extraction_service import ExtractionLimits, extract_zip

LIMITS = ExtractionLimits(max_files=20, max_total_bytes=10_000, max_file_bytes=5_000)


@pytest.fixture
def write_archive(tmp_path, make_zip):
    def _write(entries):
        path = tmp_path / "archive.zip"
        path.write_bytes(make_zip(entries))
        return path

    return _write


@pytest.fixture
def dest(tmp_path):
    return tmp_path / "out"


def test_successful_extraction(write_archive, dest):
    archive = write_archive(
        {"proj/a.py": "print(1)", "proj/pkg/b.py": "x = 1", "proj/empty/": ""}
    )

    result = extract_zip(archive, dest, LIMITS)

    assert result.files_extracted == 2
    assert result.total_bytes == len("print(1)") + len("x = 1")
    assert (dest / "proj" / "a.py").read_text() == "print(1)"
    assert (dest / "proj" / "pkg" / "b.py").read_text() == "x = 1"
    assert (dest / "proj" / "empty").is_dir()


def test_path_traversal_rejected(write_archive, dest, tmp_path):
    archive = write_archive([("good.py", "x"), ("../evil.txt", "pwned")])

    with pytest.raises(ExtractionError, match="traversal"):
        extract_zip(archive, dest, LIMITS)

    assert not (tmp_path / "evil.txt").exists()
    assert not dest.exists()  # atomic: nothing partially extracted


def test_absolute_path_rejected(write_archive, dest):
    archive = write_archive([("/etc/evil.txt", "pwned")])

    with pytest.raises(ExtractionError, match="Absolute"):
        extract_zip(archive, dest, LIMITS)
    assert not dest.exists()


@pytest.mark.parametrize(
    "name",
    [
        "a/../../evil.txt",
        "..\\evil.txt",
        "a\\..\\..\\evil.txt",
        "C:/Windows/evil.txt",
        "\\\\server\\share\\evil.txt",
        "a/.../evil.txt",
        "a/b:stream.txt",
        "a/NUL.txt",
        "bad\x01name.txt",
    ],
)
def test_other_unsafe_names_rejected(write_archive, dest, tmp_path, name):
    archive = write_archive([(name, "x")])

    with pytest.raises(ExtractionError):
        extract_zip(archive, dest, LIMITS)

    assert not dest.exists()
    assert list(tmp_path.rglob("evil.txt")) == []


def test_symlink_entry_rejected(write_archive, dest):
    link = zipfile.ZipInfo("proj/link")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16

    with pytest.raises(ExtractionError, match="Symbolic links"):
        extract_zip(write_archive([("proj/a.py", "x"), (link, "/etc/passwd")]), dest, LIMITS)
    assert not dest.exists()


def test_special_file_type_rejected(write_archive, dest):
    fifo = zipfile.ZipInfo("proj/pipe")
    fifo.create_system = 3
    fifo.external_attr = (stat.S_IFIFO | 0o644) << 16

    with pytest.raises(ExtractionError, match="Special file"):
        extract_zip(write_archive([(fifo, "")]), dest, LIMITS)


def test_excessive_file_count_rejected(write_archive, dest):
    archive = write_archive({f"f{i}.txt": "x" for i in range(25)})

    with pytest.raises(ExtractionError) as exc_info:
        extract_zip(archive, dest, LIMITS)

    assert exc_info.value.status_code == 413
    assert "limit" in exc_info.value.message
    assert not dest.exists()


def test_excessive_total_size_rejected(write_archive, dest):
    archive = write_archive({f"f{i}.txt": "a" * 4_000 for i in range(3)})  # 12,000 > 10,000

    with pytest.raises(ExtractionError, match="total uncompressed size") as exc_info:
        extract_zip(archive, dest, LIMITS)

    assert exc_info.value.status_code == 413
    assert not dest.exists()


def test_excessive_single_file_size_rejected(write_archive, dest):
    archive = write_archive({"big.txt": "a" * 6_000})  # > 5,000 per-file limit

    with pytest.raises(ExtractionError, match="per-file limit") as exc_info:
        extract_zip(archive, dest, LIMITS)

    assert exc_info.value.status_code == 413


def test_highly_compressible_bomb_rejected_by_declared_size(write_archive, dest):
    archive = write_archive({"zeros.bin": b"\0" * 5_000_000})  # tiny ZIP, huge when expanded

    with pytest.raises(ExtractionError):
        extract_zip(archive, dest, LIMITS)
    assert not dest.exists()


def test_duplicate_paths_rejected(write_archive, dest):
    with pytest.warns(UserWarning):  # zipfile itself warns when WRITING duplicates
        archive = write_archive([("a.txt", "one"), ("a.txt", "two")])
    with pytest.raises(ExtractionError, match="Duplicate"):
        extract_zip(archive, dest, LIMITS)


def test_case_insensitive_collision_rejected(write_archive, dest):
    archive = write_archive([("Readme.md", "one"), ("README.MD", "two")])

    with pytest.raises(ExtractionError, match="Duplicate"):
        extract_zip(archive, dest, LIMITS)


def test_file_directory_conflict_rejected(write_archive, dest):
    archive = write_archive([("a", "file"), ("a/b.txt", "nested")])

    with pytest.raises(ExtractionError, match="Conflicting"):
        extract_zip(archive, dest, LIMITS)


def test_directory_then_file_conflict_rejected(write_archive, dest):
    archive = write_archive([("a/b.txt", "nested"), ("a", "file")])

    with pytest.raises(ExtractionError, match="Conflicting"):
        extract_zip(archive, dest, LIMITS)


def test_macos_metadata_skipped(write_archive, dest):
    archive = write_archive(
        {"proj/x.py": "x = 1", "__MACOSX/proj/._x.py": "meta", "proj/.DS_Store": "meta"}
    )

    result = extract_zip(archive, dest, LIMITS)

    assert result.files_extracted == 1
    assert sorted(result.skipped_entries) == ["__MACOSX/proj/._x.py", "proj/.DS_Store"]
    assert not (dest / "__MACOSX").exists()


def test_not_a_zip_rejected(tmp_path, dest):
    bogus = tmp_path / "bogus.zip"
    bogus.write_bytes(b"not a zip")

    with pytest.raises(ExtractionError, match="not a valid ZIP"):
        extract_zip(bogus, dest, LIMITS)


def test_empty_archive_rejected(write_archive, dest):
    with pytest.raises(ExtractionError, match="no files"):
        extract_zip(write_archive([]), dest, LIMITS)


def test_directories_only_archive_rejected(write_archive, dest):
    with pytest.raises(ExtractionError, match="no files"):
        extract_zip(write_archive([("only/dir/", "")]), dest, LIMITS)


def test_non_empty_destination_rejected(write_archive, dest):
    dest.mkdir()
    (dest / "existing.txt").write_text("keep me")

    with pytest.raises(ExtractionError, match="must be empty"):
        extract_zip(write_archive({"a.py": "x"}), dest, LIMITS)

    assert (dest / "existing.txt").read_text() == "keep me"


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_extracted_files_are_never_executable(write_archive, dest):
    script = zipfile.ZipInfo("run.sh")
    script.create_system = 3
    script.external_attr = (stat.S_IFREG | 0o755) << 16

    extract_zip(write_archive([(script, "#!/bin/sh\necho hi\n")]), dest, LIMITS)

    assert not os.access(dest / "run.sh", os.X_OK)
