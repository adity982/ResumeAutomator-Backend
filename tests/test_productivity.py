import datetime as dt
import hashlib

from app import models
from app.database import SessionLocal

OTHER = {"Authorization": "Bearer dev:other:other@example.com"}


def job(client, headers, title="API developer"):
    response = client.post("/api/v1/jobs", headers=headers, json={"title": title, "company": "Example", "description": "Build Python APIs with database persistence and request validation tests."})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def reviewed_document(client, headers, target):
    statement = "Implemented Python API persistence and request validation tests."
    with SessionLocal() as db:
        source = models.PortfolioSource(user_uid="user-1", repository="owner/api", commit_sha="a" * 40, source_url="https://github.com/owner/api", files=[], status="ready")
        db.add(source)
        db.flush()
        evidence = models.EvidenceChunk(user_uid="user-1", source_id=source.id, path="api.py", start_line=1, end_line=2, content=statement, content_hash=hashlib.sha256(statement.encode()).hexdigest(), source_url="https://github.com/owner/api/blob/" + "a" * 40 + "/api.py#L1", kind="implementation", review_status="approved", approved_statement=statement)
        db.add(evidence)
        db.commit()
        evidence_id, source_id = evidence.id, source.id
    result = client.post("/api/v1/documents", headers=headers, json={"title": "Backend base", "job_id": target, "content": statement, "approved": True, "evidence_snapshot": [evidence_id]})
    assert result.status_code == 201, result.text
    return result.json(), source_id


def test_resume_reuse_keeps_original_and_requires_new_target_review(client, auth_headers):
    first, second = job(client, auth_headers), job(client, auth_headers, "Platform developer")
    document, source_id = reviewed_document(client, auth_headers, first)
    result = client.post(f"/api/v1/jobs/{second}/resume-base/{document['id']}", headers=auth_headers)
    assert result.status_code == 200
    copied = result.json()
    assert copied["job_id"] == second and copied["approved"] is False and copied["logical_id"] is None
    assert copied["content"] == document["content"] and copied["evidence_ids"]
    assert len(client.get("/api/v1/documents", headers=auth_headers).json()) == 1
    foreign = job(client, OTHER)
    assert client.post(f"/api/v1/jobs/{foreign}/resume-base/{document['id']}", headers=OTHER).status_code == 404
    assert client.post(f"/api/v1/jobs/{foreign}/resume-base/{document['id']}", headers=auth_headers).status_code == 404
    with SessionLocal() as db:
        db.get(models.PortfolioSource, source_id).status = "superseded"
        db.commit()
    assert client.post(f"/api/v1/jobs/{second}/resume-base/{document['id']}", headers=auth_headers).status_code == 409


def test_manual_resume_reuse_and_wrong_document_kind(client, auth_headers):
    target = job(client, auth_headers)
    manual = client.post("/api/v1/documents", headers=auth_headers, json={"title": "General resume", "content": "My self-authored resume with experience and skills."}).json()
    assert client.post(f"/api/v1/jobs/{target}/resume-base/{manual['id']}", headers=auth_headers).json()["evidence_ids"] == []
    letter = client.post("/api/v1/documents", headers=auth_headers, json={"title": "Letter", "kind": "cover_letter", "content": "My cover letter draft."}).json()
    assert client.post(f"/api/v1/jobs/{target}/resume-base/{letter['id']}", headers=auth_headers).status_code == 422


def test_queue_orders_real_actions_and_excludes_closed_archived_completed_and_other_users(client, auth_headers):
    target = job(client, auth_headers)
    due = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)).isoformat()
    app = client.post("/api/v1/applications", headers=auth_headers, json={"job_id": target, "company": "Example", "role": "API developer", "deadline": due}).json()
    task = client.post("/api/v1/tasks", headers=auth_headers, json={"application_id": app["id"], "title": "Check application reply", "due_at": due}).json()
    result = client.get("/api/v1/work-queue", headers=auth_headers).json()
    assert [item["kind"] for item in result["items"]] == ["deadline", "follow_up", "resume"]
    assert result["items"][0]["overdue"] is True
    limited = client.get("/api/v1/work-queue?limit=1", headers=auth_headers).json()
    assert len(limited["items"]) == 1 and limited["has_more"] is True
    assert client.get("/api/v1/work-queue", headers=OTHER).json()["items"] == []
    client.patch(f"/api/v1/tasks/{task['id']}", headers=auth_headers, json={"completed": True})
    assert "follow_up" not in [item["kind"] for item in client.get("/api/v1/work-queue", headers=auth_headers).json()["items"]]
    client.patch(f"/api/v1/jobs/{target}", headers=auth_headers, json={"archived": True})
    assert client.get("/api/v1/work-queue", headers=auth_headers).json()["items"] == []
    client.patch(f"/api/v1/jobs/{target}", headers=auth_headers, json={"archived": False})
    client.patch(f"/api/v1/applications/{app['id']}", headers=auth_headers, json={"stage": "closed", "outcome": "rejected"})
    assert client.get("/api/v1/work-queue", headers=auth_headers).json()["items"] == []


def test_queue_surfaces_changed_evidence_and_failed_import_once(client, auth_headers):
    target = job(client, auth_headers)
    document, source_id = reviewed_document(client, auth_headers, target)
    client.post("/api/v1/applications", headers=auth_headers, json={"job_id": target, "company": "Example", "role": "API developer", "resume_document_id": document["id"]})
    with SessionLocal() as db:
        db.get(models.PortfolioSource, source_id).status = "failed"
        for _ in range(2):
            db.add(models.IngestionJob(user_uid="user-1", source_id=source_id, paths=["api.py"], status="failed"))
        db.commit()
    items = client.get("/api/v1/work-queue", headers=auth_headers).json()["items"]
    assert [item["kind"] for item in items] == ["evidence", "import"]
    assert client.get("/api/v1/work-queue").status_code == 401
