"""Status endpoint across the full scan -> analysis -> patches -> approve -> apply flow."""

import json

from test_patch import (  # noqa: F401  (fixture import)
    _make_unified_diff,
    _run_step4_analysis,
    _setup_analyzed_project,
    _StubProvider,
    make_patch_client,
)


def test_status_tracks_full_workflow_and_other_projects_are_unaffected(
    make_patch_client, make_zip, workspace
):
    old_code = "def run(cmd):\n    return eval(cmd)\n"
    new_code = "import ast\n\n\ndef run(cmd):\n    return ast.literal_eval(cmd)\n"
    rel_path = "runner.py"
    holder = {}

    def handler(_s, _u, _st):
        finding = holder["scan"]["findings"][0]
        return json.dumps(
            {
                "patches": [
                    {
                        "finding_id": finding["id"],
                        "target_file": rel_path,
                        "unified_diff": _make_unified_diff(rel_path, old_code, new_code),
                        "summary": "Replace eval with literal_eval.",
                        "explanation": "Avoids arbitrary code execution.",
                        "confidence": "HIGH",
                        "assumptions_or_uncertainties": [],
                    }
                ],
                "limitations": [],
            }
        )

    client = make_patch_client(provider=_StubProvider(handler))
    pid, scan_body, analysis_json = _setup_analyzed_project(
        client, make_zip, {f"proj/{rel_path}": old_code}
    )
    holder["scan"] = scan_body

    # A second, untouched project must keep reporting "nothing generated".
    other = client.post(
        "/api/projects/upload",
        files={"file": ("o.zip", make_zip({"o/x.py": "X = 1\n"}), "application/zip")},
    ).json()["project_id"]

    st = client.get(f"/api/projects/{pid}/status").json()
    assert st["scan"]["available"] and not st["analysis"]["available"]

    _run_step4_analysis(client, pid, analysis_json, workspace)
    st = client.get(f"/api/projects/{pid}/status").json()
    assert st["analysis"]["available"] and st["can_generate_patches"]
    assert st["patches"]["state"] == "missing"

    gen = client.post(f"/api/projects/{pid}/patches/generate")
    assert gen.status_code == 200
    patch_id = gen.json()["patches"][0]["patch_id"]
    st = client.get(f"/api/projects/{pid}/status").json()
    assert st["patches"]["available"] and st["patches"]["count"] == 1
    assert st["patch_counts"]["total"] == 1
    assert st["patch_counts"]["by_status"] == {"generated": 1}

    assert client.post(f"/api/projects/{pid}/patches/{patch_id}/approve").status_code == 200
    assert client.post(f"/api/projects/{pid}/patches/{patch_id}/apply").status_code == 200
    st = client.get(f"/api/projects/{pid}/status").json()
    assert st["patch_counts"]["by_status"] == {"applied": 1}
    assert st["validations"]["state"] == "missing"  # nothing fabricated

    hist = client.get(f"/api/projects/{pid}/patches/history")
    assert hist.status_code == 200 and hist.json()["applied_count"] == 1

    # Unknown patch -> distinct code from "no patches generated"
    miss = client.get(f"/api/projects/{pid}/patches/patch-doesnotexist")
    assert miss.status_code == 404 and miss.json()["code"] == "patch_not_found"

    other_status = client.get(f"/api/projects/{other}/status").json()
    for key in ("scan", "analysis", "patches", "validations"):
        assert other_status[key]["state"] == "missing"
