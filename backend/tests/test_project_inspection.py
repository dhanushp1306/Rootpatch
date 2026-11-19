from pathlib import Path

from app.services.inspection_service import build_structure, find_project_root, inspect_project

PID = "a" * 32


def make_tree(root: Path, files):
    for rel in files:
        path = root / rel
        if rel.endswith("/"):
            path.mkdir(parents=True, exist_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# placeholder\n")
    return root


def inspect(tmp_path, files, name="proj"):
    source = make_tree(tmp_path / "source", files)
    root = find_project_root(source)
    return inspect_project(PID, name, root, source)


def test_python_language_detection_with_evidence(tmp_path):
    report = inspect(tmp_path, ["app/main.py", "app/util.py", "scripts/run.py"])

    assert [lang.name for lang in report.languages] == ["Python"]
    python = report.languages[0]
    assert python.file_count == 3
    assert python.extensions == [".py"]
    assert python.example_files == ["app/main.py", "app/util.py", "scripts/run.py"]
    assert report.python_detected is True


def test_no_language_claimed_without_evidence(tmp_path):
    report = inspect(tmp_path, ["README.md", "package.json", "notes.txt"])

    assert report.languages == []
    assert report.python_detected is False
    assert any("No recognised source files" in w for w in report.warnings)


def test_multiple_languages_and_non_python_warning(tmp_path):
    report = inspect(tmp_path, ["a.py", "web/app.ts", "web/util.js", "main.go"])

    names = [lang.name for lang in report.languages]
    assert set(names) == {"Python", "TypeScript", "JavaScript", "Go"}
    assert any("non-Python" in w and "Go" in w for w in report.warnings)


def test_dependency_manifests_detected(tmp_path):
    files = [
        "requirements.txt", "requirements-dev.txt", "pyproject.toml", "setup.py",
        "package.json", "package-lock.json", "pom.xml", "build.gradle",
        "Cargo.toml", "go.mod",
    ]
    report = inspect(tmp_path, files)

    found = {m.name: m.ecosystem for m in report.dependency_manifests}
    assert found == {
        "requirements.txt": "Python", "requirements-dev.txt": "Python",
        "pyproject.toml": "Python", "setup.py": "Python",
        "package.json": "Node.js", "package-lock.json": "Node.js",
        "pom.xml": "Java (Maven)", "build.gradle": "JVM (Gradle)",
        "Cargo.toml": "Rust", "go.mod": "Go",
    }


def test_configuration_and_documentation_files_detected(tmp_path):
    report = inspect(
        tmp_path,
        ["tsconfig.json", "Dockerfile", ".gitignore", "README.md", "docs/guide.md", "LICENSE"],
    )

    assert {c.name for c in report.configuration_files} == {
        "tsconfig.json", "Dockerfile", ".gitignore",
    }
    assert set(report.documentation_files) == {"README.md", "docs/guide.md", "LICENSE"}


def test_test_files_and_directories_detected(tmp_path):
    report = inspect(
        tmp_path,
        [
            "src/app.py",
            "tests/test_app.py",
            "tests/helpers.py",
            "src/test_inline.py",
            "web/button.test.ts",
            "pkg/thing_test.go",
        ],
    )

    assert report.test_directories == ["tests"]
    assert set(report.test_files) == {
        "tests/test_app.py", "tests/helpers.py", "src/test_inline.py",
        "web/button.test.ts", "pkg/thing_test.go",
    }
    assert report.test_file_count == 5
    # Test files are not counted as main source directories.
    assert [(d.path, d.source_file_count) for d in report.source_directories] == [("src", 1)]


def test_no_tests_produces_warning(tmp_path):
    report = inspect(tmp_path, ["app.py"])
    assert any("No test files" in w for w in report.warnings)


def test_counts_extensions_and_single_root(tmp_path):
    report = inspect(
        tmp_path,
        ["proj/a.py", "proj/b.py", "proj/pkg/c.py", "proj/data.json", "proj/LICENSE"],
    )

    assert report.root_directory == "proj"
    assert report.total_files == 5
    assert report.total_directories == 1  # proj/pkg (the root itself is not counted)
    assert report.file_extensions == {".py": 3, ".json": 1, "(none)": 1}
    assert report.total_size_bytes > 0
    assert [e.name for e in report.top_level_entries] == ["pkg", "a.py", "b.py", "data.json", "LICENSE"]


def test_multiple_top_level_entries_use_archive_root(tmp_path):
    report = inspect(tmp_path, ["a.py", "pkg/b.py"])

    assert report.root_directory == "."
    assert any("no single top-level directory" in w for w in report.warnings)


def test_vendor_directories_excluded_from_detection(tmp_path):
    report = inspect(
        tmp_path,
        ["app.py", "node_modules/lib/index.js", "node_modules/lib/package.json", "tests/test_a.py"],
    )

    assert [lang.name for lang in report.languages] == ["Python"]
    assert report.dependency_manifests == []
    assert report.total_files == 4  # still counted in totals
    assert any("node_modules" in w for w in report.warnings)


def test_sensitive_files_flagged_by_name_only(tmp_path):
    report = inspect(tmp_path, ["app.py", ".env", "keys/server.pem", ".env.example"])

    warning = next(w for w in report.warnings if "sensitive" in w)
    assert ".env" in warning and "keys/server.pem" in warning
    assert ".env.example" not in warning


def test_structure_generation_orders_directories_first(tmp_path):
    source = make_tree(tmp_path / "source", ["proj/b.py", "proj/a_dir/x.py", "proj/Z.txt"])
    root = find_project_root(source)

    tree, count, truncated = build_structure(root, max_nodes=100)

    assert tree.name == "proj" and tree.type == "directory" and tree.path == "."
    assert [c.name for c in tree.children] == ["a_dir", "b.py", "Z.txt"]
    assert tree.children[0].type == "directory"
    assert tree.children[0].children[0].path == "a_dir/x.py"
    assert tree.children[1].size_bytes is not None
    assert count == 4 and truncated is False  # a_dir, x.py, b.py, Z.txt


def test_structure_truncates_at_node_limit(tmp_path):
    root = make_tree(tmp_path / "source", [f"f{i}.py" for i in range(10)])

    tree, count, truncated = build_structure(root, max_nodes=4)

    assert count == 4 and truncated is True
    assert len(tree.children) == 4
