import hashlib

import fitz
import pytest
from sqlalchemy import select

from app import models
from app.database import SessionLocal
from app.services import github_import, ai
from app.worker import run_once

OTHER = {"Authorization": "Bearer dev:user-2:other@example.com"}
CONTENT = "# API service\nBuilt a Python FastAPI service using PostgreSQL and SQL.\nTests validate order persistence and request handling."
STATEMENT = "Implemented FastAPI request validation and PostgreSQL persistence tests in my API service."


def seed_source(client, headers, monkeypatch, repository="owner/api", content=CONTENT):
    monkeypatch.setattr(github_import, "public_preview", lambda url: {"repository": repository, "commit_sha": "a" * 40, "source_url": f"https://github.com/{repository}", "description": "API service", "is_fork": False, "files": [{"path": "README.md", "bytes": len(content), "hash": hashlib.sha256(content.encode()).hexdigest(), "content": content}]})
    preview = client.post("/api/v1/sources/preview", headers=headers, json={"url": f"https://github.com/{repository}"})
    assert preview.status_code == 201, preview.text
    source_id = preview.json()["id"]
    queued = client.post(f"/api/v1/sources/{source_id}/import", headers=headers, json={"paths": ["README.md"], "relationship": "personal", "contribution": "I implemented the API and its persistence tests."})
    assert queued.status_code == 202, queued.text
    assert run_once()
    evidence = client.get(f"/api/v1/sources/{source_id}/evidence", headers=headers).json()
    assert evidence and "embedding" not in evidence[0]
    return source_id, evidence[0]["id"]


def job(client, headers, description="Build a Python FastAPI service using PostgreSQL and SQL."):
    response = client.post("/api/v1/jobs", headers=headers, json={"title": "API developer", "company": "Test company", "description": description})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_ingestion_review_selection_and_cited_draft(client, auth_headers, monkeypatch):
    source_id, evidence_id = seed_source(client, auth_headers, monkeypatch)
    target = job(client, auth_headers)
    observed = client.post(f"/api/v1/jobs/{target}/projects", headers=auth_headers, json={}).json()
    assert observed["projects"] == [] and observed["bullets"] == []
    assert client.patch(f"/api/v1/project-evidence/{evidence_id}", headers=auth_headers, json={"status": "approved", "statement": STATEMENT}).status_code == 200
    result = client.post(f"/api/v1/jobs/{target}/projects", headers=auth_headers, json={}).json()
    assert result["projects"][0]["source_id"] == source_id
    assert result["requirements"][0]["status"] == "supported"
    assert result["bullets"][0]["text"] == STATEMENT
    assert "/blob/" + "a" * 40 in result["bullets"][0]["citation"]["url"]
    draft = client.post("/api/v1/ai/tailor", headers=auth_headers, json={"resume_text": "SUMMARY\nI build reliable web applications and test them.", "jd_text": CONTENT, "evidence_ids": [evidence_id]})
    assert draft.status_code == 200 and draft.json()["citations"][0]["evidence_id"] == evidence_id
    assert STATEMENT in draft.json()["tailored"]


def test_isolation_across_import_retrieval_review_and_contacts(client, auth_headers, monkeypatch):
    source_id, evidence_id = seed_source(client, auth_headers, monkeypatch)
    target = job(client, OTHER)
    assert client.get(f"/api/v1/sources/{source_id}/evidence", headers=OTHER).status_code == 404
    assert client.patch(f"/api/v1/project-evidence/{evidence_id}", headers=OTHER, json={"status": "approved", "statement": STATEMENT}).status_code == 404
    response = client.post(f"/api/v1/jobs/{target}/projects", headers=OTHER, json={})
    assert response.json()["projects"] == []
    assert all(not r["citations"] for r in response.json()["requirements"])
    assert client.delete(f"/api/v1/sources/{source_id}", headers=OTHER).status_code == 404


def test_source_deletion_invalidates_runs_and_document_evidence(client, auth_headers, monkeypatch):
    source_id, evidence_id = seed_source(client, auth_headers, monkeypatch)
    target = job(client, auth_headers)
    client.patch(f"/api/v1/project-evidence/{evidence_id}", headers=auth_headers, json={"status": "approved", "statement": STATEMENT})
    client.post(f"/api/v1/jobs/{target}/projects", headers=auth_headers, json={})
    document = client.post("/api/v1/documents", headers=auth_headers, json={"title": "Resume", "content": STATEMENT, "job_id": target, "approved": True, "evidence_snapshot": [evidence_id]}).json()
    assert client.delete(f"/api/v1/sources/{source_id}", headers=auth_headers).status_code == 204
    history = client.get(f"/api/v1/jobs/{target}/projects", headers=auth_headers).json()
    assert history[0]["result"]["invalidated"] is True
    assert STATEMENT not in str(history)
    attach = client.post("/api/v1/applications", headers=auth_headers, json={"company": "Test", "role": "Developer", "job_id": target, "resume_document_id": document["id"]})
    assert attach.status_code == 409
    with SessionLocal() as db:
        assert db.query(models.EvidenceChunk).count() == 0
        assert db.query(models.IngestionJob).count() == 0


def test_missing_explicit_skill_is_not_invented(client, auth_headers, monkeypatch):
    _, evidence_id = seed_source(client, auth_headers, monkeypatch)
    client.patch(f"/api/v1/project-evidence/{evidence_id}", headers=auth_headers, json={"status": "approved", "statement": STATEMENT})
    target = job(client, auth_headers, "Must deploy Kubernetes clusters and Terraform infrastructure.")
    result = client.post(f"/api/v1/jobs/{target}/projects", headers=auth_headers, json={}).json()
    assert result["projects"] == [] and result["bullets"] == []


def test_document_families_are_immutable_and_kind_checked(client, auth_headers):
    target = job(client, auth_headers)
    first = client.post("/api/v1/documents", headers=auth_headers, json={"title": "Resume", "job_id": target, "content": "Original resume content", "approved": True}).json()
    second = client.post("/api/v1/documents", headers=auth_headers, json={"logical_id": first["logical_id"], "title": "Resume", "job_id": target, "content": "Edited resume content", "approved": False}).json()
    assert first["version"] == 1 and second["version"] == 2
    assert first["content_hash"] != second["content_hash"]
    assert second["approved"] is False
    mismatch = client.post("/api/v1/applications", headers=auth_headers, json={"company": "Test", "role": "Developer", "job_id": target, "cover_letter_document_id": first["id"]})
    assert mismatch.status_code == 422


def test_workspace_revision_conflicts_and_isolation(client, auth_headers):
    payload = {"revision": 0, "data": {"resume_text": "My private resume text", "target_title": "Developer"}}
    assert client.put("/api/v1/workspace", headers=auth_headers, json=payload).json()["revision"] == 1
    assert client.put("/api/v1/workspace", headers=auth_headers, json=payload).status_code == 409
    assert client.get("/api/v1/workspace", headers=OTHER).json()["data"]["resume_text"] == ""
    assert client.get("/api/v1/workspace", headers=auth_headers).json()["data"]["resume_text"] == "My private resume text"
    assert client.delete("/api/v1/workspace", headers=auth_headers).status_code == 204


def test_closed_before_interview_does_not_inflate_conversion(client, auth_headers):
    application = client.post("/api/v1/applications", headers=auth_headers, json={"company": "Test", "role": "Developer", "stage": "applied"}).json()
    client.patch(f"/api/v1/applications/{application['id']}", headers=auth_headers, json={"stage": "closed", "outcome": "rejected"})
    assert client.get("/api/v1/analytics/summary", headers=auth_headers).json()["interview_conversion_rate"] == 0
    client.patch(f"/api/v1/applications/{application['id']}", headers=auth_headers, json={"stage": "interview"})
    client.patch(f"/api/v1/applications/{application['id']}", headers=auth_headers, json={"stage": "closed"})
    assert client.get("/api/v1/analytics/summary", headers=auth_headers).json()["interview_conversion_rate"] == 100


def test_interview_repetition_and_short_skills_regression():
    assert ai.score_answer('situation task action result 1 2 ' + 'banana ' * 134)["score"] == 0
    assert set(ai.tokens('C C++ C# Go R')) == {'c', 'c++', 'c#', 'go', 'r'}


def test_unicode_pdf_and_unsupported_characters_are_explicit(client, auth_headers):
    result = client.post("/api/v1/documents/export", headers=auth_headers, json={"text": "José Müller\nEXPERIENCE\n• Built APIs — résumé evidence", "format": "pdf"})
    assert result.status_code == 200
    with fitz.open(stream=result.content, filetype="pdf") as pdf:
        text = ''.join(page.get_text() for page in pdf)
    assert 'José' in text and 'Müller' in text and 'résumé' in text
    unsupported = client.post("/api/v1/documents/export", headers=auth_headers, json={"text": "Unsupported name 字", "format": "pdf"})
    assert unsupported.status_code == 400
    assert "no characters were silently removed" in unsupported.text


def test_contacts_outreach_revision_and_feedback(client, auth_headers):
    target = job(client, auth_headers)
    contact = client.post("/api/v1/contacts", headers=auth_headers, json={"job_id": target, "name": "Recruiter", "linkedin_url": "https://www.linkedin.com/in/example"}).json()
    assert client.patch(f"/api/v1/contacts/{contact['id']}", headers=auth_headers, json={"stop_follow_up": True}).json()["stop_follow_up"] is True
    assert client.patch(f"/api/v1/contacts/{contact['id']}", headers=OTHER, json={"status": "replied"}).status_code == 404
    kit = client.post("/api/v1/outreach", headers=auth_headers, json={"job_id": target, "contact_id": contact["id"], "resume_text": CONTENT, "jd_text": CONTENT, "tone": "warm", "recipient_role": "Engineering manager"}).json()
    assert 'week' in kit['variants']['hiring_manager_note'] and 'Engineering manager' in kit['variants']['hiring_manager_note']
    saved = client.patch(f"/api/v1/outreach/{kit['id']}", headers=auth_headers, json={"revision": 1, "status": "sent", "variants": {"linkedin_message": "My reviewed draft"}})
    assert saved.json()["revision"] == 2 and saved.json()["status"] == "sent"
    assert client.patch(f"/api/v1/outreach/{kit['id']}", headers=auth_headers, json={"revision": 1, "status": "replied"}).status_code == 409
    assert client.post("/api/v1/pilot/feedback", headers=auth_headers, json={"job_id": target, "task": "prepare_application", "rating": 4, "completed_without_help": True}).status_code == 201
    export = client.get("/api/v1/account/export", headers=auth_headers).json()
    assert export['contacts'][0]['id'] == contact['id'] and len(export['pilot_feedback']) == 1
    assert client.delete("/api/v1/account", headers=auth_headers).status_code == 204
    with SessionLocal() as db:
        assert db.query(models.Contact).count() == db.query(models.PilotFeedback).count() == 0


@pytest.mark.parametrize('url', ['http://github.com/a/b', 'https://github.com/a/b/tree/main', 'https://github.com.evil.test/a/b', 'https://user@github.com/a/b'])
def test_import_url_is_strict(url):
    with pytest.raises(github_import.ImportFailure):
        github_import.repository_name(url)


def test_import_exclusions_and_chunk_lines():
    for path in ['.env', 'node_modules/package/index.ts', 'credentials.py', 'package-lock.json', 'dist/main.js', 'key.secret.py']:
        assert not github_import.allowed(path)
    chunks = github_import.chunk_file('api.py', '\n'.join(f'line {i}' for i in range(80)))
    assert chunks[0]['start_line'] == 1 and chunks[0]['end_line'] == 35
    assert chunks[-1]['end_line'] == 80


def test_review_rejects_unsupported_technology_and_metrics(client, auth_headers, monkeypatch):
    _, evidence_id = seed_source(client, auth_headers, monkeypatch)
    for statement in ['Implemented Kubernetes production infrastructure for this service.', 'Improved FastAPI throughput by 99%.']:
        result = client.patch(f'/api/v1/project-evidence/{evidence_id}', headers=auth_headers, json={'status': 'approved', 'statement': statement})
        assert result.status_code == 422


def test_import_cancellation_prevents_worker_writes(client, auth_headers, monkeypatch):
    seed_source(client, auth_headers, monkeypatch)
    source = client.get('/api/v1/sources', headers=auth_headers).json()[0]
    queued = client.post(f"/api/v1/sources/{source['id']}/import", headers=auth_headers, json={'paths': ['README.md'], 'relationship': 'personal', 'contribution': 'I implemented the API and its persistence tests.'}).json()
    assert client.post(f"/api/v1/imports/{queued['id']}/cancel", headers=auth_headers).json()['status'] == 'cancelled'
    assert not run_once()


def test_shared_limits_follow_verified_identity_not_token_rotation(monkeypatch):
    from app.services import usage
    from fastapi import HTTPException
    from types import SimpleNamespace
    monkeypatch.setattr(usage, 'settings', SimpleNamespace(rate_limit_per_minute=1))
    usage.consume('user-1', '/api/v1/jobs', 'GET')
    with pytest.raises(HTTPException) as error:
        usage.consume('user-1', '/api/v1/analysis/history', 'GET')
    assert error.value.status_code == 429
    usage.consume('user-2', '/api/v1/jobs', 'GET')
