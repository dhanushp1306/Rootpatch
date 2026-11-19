import re
import stat
import zipfile

from conftest import project_dirs, upload


def test_valid_zip_upload(client, workspace, python_project_zip):
    response = upload(client, python_project_zip, "My Project.zip")

    assert response.status_code == 201
    body = response.json()
    assert re.fullmatch(r"[0-9a-f]{32}", body["project_id"])
    assert body["project_name"] == "demo"
    assert body["status"] == "ready"

    project_dir = workspace / body["project_id"]
    assert (project_dir / "original" / "upload.zip").is_file()
    assert (project_dir / "source" / "demo" / "app" / "main.py").is_file()
    assert (project_dir / "metadata.json").is_file()


def test_each_upload_gets_isolated_workspace(client, workspace, python_project_zip):
    first = upload(client, python_project_zip).json()["project_id"]
    second = upload(client, python_project_zip).json()["project_id"]

    assert first != second
    assert {p.name for p in project_dirs(workspace)} == {first, second}


def test_project_name_falls_back_to_zip_name_without_single_root(client, make_zip):
    data = make_zip({"a.py": "x = 1", "b.py": "y = 2"})
    body = upload(client, data, "flat-project.zip").json()
    assert body["project_name"] == "flat-project"


def test_invalid_zip_content_rejected(client, workspace):
    response = upload(client, b"this is definitely not a zip file")

    assert response.status_code == 400
    assert "not a valid ZIP" in response.json()["detail"]
    assert project_dirs(workspace) == []


def test_zero_byte_upload_rejected(client, workspace):
    response = upload(client, b"")
    assert response.status_code == 400
    assert project_dirs(workspace) == []


def test_unsupported_extension_rejected(client, workspace, python_project_zip):
    response = upload(client, python_project_zip, "project.txt")

    assert response.status_code == 415
    assert "Unsupported file type" in response.json()["detail"]
    assert project_dirs(workspace) == []


def test_empty_zip_rejected(client, workspace, make_zip):
    response = upload(client, make_zip([]))

    assert response.status_code == 400
    assert "no files" in response.json()["detail"]
    assert project_dirs(workspace) == []


def test_oversized_upload_rejected(make_client, workspace, python_project_zip):
    client = make_client(max_upload_bytes=50)
    response = upload(client, python_project_zip)

    assert response.status_code == 413
    assert project_dirs(workspace) == []


def test_missing_file_field_rejected(client):
    response = client.post("/api/projects/upload")
    assert response.status_code == 422


def test_malicious_zip_rejected_and_nothing_written_outside(
    client, tmp_path, workspace, make_zip
):
    data = make_zip([("ok/file.py", "x = 1"), ("../evil.txt", "pwned")])
    response = upload(client, data)

    assert response.status_code == 400
    assert "traversal" in response.json()["detail"].lower()
    assert list(tmp_path.rglob("evil.txt")) == []
    assert project_dirs(workspace) == []


def test_symlink_zip_rejected(client, workspace, make_zip):
    link = zipfile.ZipInfo("proj/link")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    response = upload(client, make_zip([("proj/a.py", "x"), (link, "/etc/passwd")]))

    assert response.status_code == 400
    assert project_dirs(workspace) == []


def test_get_project_returns_metadata_and_inspection(client, python_project_zip):
    project_id = upload(client, python_project_zip).json()["project_id"]

    response = client.get(f"/api/projects/{project_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["project_id"] == project_id
    assert body["project_name"] == "demo"
    assert body["status"] == "ready"
    assert body["inspection"]["total_files"] == 6
    assert body["inspection"]["python_detected"] is True
    assert body["archive"]["files_extracted"] == 6


def test_get_structure(client, python_project_zip):
    project_id = upload(client, python_project_zip).json()["project_id"]

    response = client.get(f"/api/projects/{project_id}/structure")

    assert response.status_code == 200
    body = response.json()
    assert body["project_id"] == project_id
    assert body["root_directory"] == "demo"
    assert body["truncated"] is False
    child_names = [c["name"] for c in body["tree"]["children"]]
    assert child_names == ["app", "tests", "Dockerfile", "README.md", "requirements.txt"]


def test_nonexistent_project_id_returns_404(client):
    for path in ("", "/structure"):
        response = client.get(f"/api/projects/{'0' * 32}{path}")
        assert response.status_code == 404
        assert response.json()["detail"] == "Project not found."


def test_malformed_project_id_returns_404(client):
    for bad_id in ("not-an-id", "..", "%2e%2e", "A" * 32):
        assert client.get(f"/api/projects/{bad_id}").status_code == 404
        assert client.get(f"/api/projects/{bad_id}/structure").status_code == 404


def test_health_endpoint_still_works(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
