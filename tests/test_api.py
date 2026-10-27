RESUME = """Alex Candidate
SUMMARY
Python developer delivering reliable web applications.
EXPERIENCE
Built FastAPI services and improved latency by 25%.
EDUCATION
Bachelor of Technology
SKILLS
Python, FastAPI, SQL, Git, Docker
PROJECTS
Created a resume automation platform.
"""

JOB = """We are hiring a Python developer to build FastAPI services. The role requires SQL, Docker,
cloud deployment, communication, testing, and production monitoring experience."""


def test_health_and_authentication(client, monkeypatch):
    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
    monkeypatch.setenv("RELEASE_SHA", "test-release")
    assert client.get("/health/live").json() == {"status": "ok", "revision": "test-release"}
    response = client.get("/api/v1/jobs")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "http_401"


def test_job_application_analysis_and_analytics(client, auth_headers):
    job = client.post(
        "/api/v1/jobs",
        headers=auth_headers,
        json={"title": "Backend Engineer", "company": "Example", "source_url": "https://example.com/jobs/1", "description": JOB},
    )
    assert job.status_code == 201
    job_id = job.json()["id"]

    analysis = client.post(
        "/api/v1/analysis",
        headers=auth_headers,
        json={"resume_text": RESUME, "jd_text": JOB, "job_id": job_id},
    )
    assert analysis.status_code == 200
    body = analysis.json()
    assert len(body["dimensions"]) == 5
    assert all("confidence" in item and "definition" in item for item in body["dimensions"])
    assert body["methodology_version"] == "heuristic-v3"
    assert len(body["input_fingerprint"]) == 64
    assert body["methodology"]["repeatable"] is True
    gap_keywords = {item["keyword"] for item in body["gap_plan"]}
    assert gap_keywords.isdisjoint({"hire", "hiring", "build", "require", "requires", "experience", "need", "engineer", "clear"})

    application = client.post(
        "/api/v1/applications",
        headers=auth_headers,
        json={"job_id": job_id, "company": "Example", "role": "Backend Engineer", "stage": "applied"},
    )
    assert application.status_code == 201
    app_id = application.json()["id"]
    moved = client.patch(f"/api/v1/applications/{app_id}", headers=auth_headers, json={"stage": "interview"})
    assert moved.json()["stage"] == "interview"
    assert len(client.get(f"/api/v1/applications/{app_id}/events", headers=auth_headers).json()) == 2

    summary = client.get("/api/v1/analytics/summary", headers=auth_headers).json()
    assert summary["applications_by_stage"]["interview"] == 1
    assert summary["sample_size"] == 1


def test_resource_ownership_is_enforced(client, auth_headers):
    job = client.post(
        "/api/v1/jobs",
        headers=auth_headers,
        json={"title": "Analyst", "description": JOB},
    ).json()
    other = {"Authorization": "Bearer dev:user-2:other@example.com"}
    assert client.patch(f"/api/v1/jobs/{job['id']}", headers=other, json={"archived": True}).status_code == 404


def test_interview_outreach_and_search_workflows(client, auth_headers):
    interview = client.post(
        "/api/v1/interviews",
        headers=auth_headers,
        json={"resume_text": RESUME, "jd_text": JOB, "interview_type": "mixed"},
    )
    assert interview.status_code == 201
    session = interview.json()
    assert session["prep_brief"]["estimated_minutes"] == 25
    assert len(session["prep_brief"]["questions_to_ask"]) == 3
    answer = client.post(
        f"/api/v1/interviews/{session['id']}/answers",
        headers=auth_headers,
        json={"question_index": 0, "answer": "Situation: latency was high. Action: I profiled SQL and added indexes. Result: latency fell 25%."},
    )
    assert answer.status_code == 200
    assert answer.json()["answers"][0]["feedback"]["score"] > 0

    outreach = client.post(
        "/api/v1/outreach",
        headers=auth_headers,
        json={"resume_text": RESUME, "jd_text": JOB, "company": "Example", "recipient_role": "Recruiter"},
    )
    assert outreach.status_code == 201
    assert len(outreach.json()["variants"]["follow_ups"]) == 2

    search = client.post(
        "/api/v1/searches",
        headers=auth_headers,
        json={"name": "Remote Python", "resume_text": RESUME, "preferences": {"desired_titles": ["Python Developer"], "work_modes": ["remote"]}},
    )
    assert search.status_code == 201
    assert search.json()["results"][0]["links"]["LinkedIn"].startswith("https://")


def test_market_features_are_owned_and_actionable(client, auth_headers):
    job = client.post(
        "/api/v1/jobs",
        headers=auth_headers,
        json={"title": "Backend Engineer", "company": "Example", "source_url": "https://example.com/jobs/2", "description": JOB},
    ).json()
    resume = client.post(
        "/api/v1/documents",
        headers=auth_headers,
        json={"job_id": job["id"], "kind": "resume", "title": "Tailored resume", "content": RESUME, "approved": True},
    ).json()
    cover = client.post(
        "/api/v1/documents",
        headers=auth_headers,
        json={"job_id": job["id"], "kind": "cover_letter", "title": "Cover letter", "content": "A truthful and targeted cover letter for this backend engineering role.", "approved": True},
    ).json()
    application = client.post(
        "/api/v1/applications",
        headers=auth_headers,
        json={
            "job_id": job["id"],
            "company": "Example",
            "role": "Backend Engineer",
            "source_url": job["source_url"],
            "stage": "applied",
            "deadline": "2030-01-02T09:00:00Z",
            "resume_document_id": resume["id"],
            "cover_letter_document_id": cover["id"],
        },
    ).json()

    package = client.get(f"/api/v1/applications/{application['id']}/package", headers=auth_headers)
    assert package.status_code == 200
    assert package.json()["readiness_score"] == 100

    task = client.post(
        "/api/v1/tasks",
        headers=auth_headers,
        json={"application_id": application["id"], "task_type": "follow_up", "title": "Follow up with recruiter", "due_at": "2030-01-03T09:00:00Z"},
    )
    assert task.status_code == 201
    completed = client.patch(f"/api/v1/tasks/{task.json()['id']}", headers=auth_headers, json={"completed": True})
    assert completed.json()["completed_at"] is not None

    evidence = client.post(
        "/api/v1/evidence",
        headers=auth_headers,
        json={"category": "achievement", "title": "Latency improvement", "statement": "Reduced API latency by 25% after profiling SQL queries.", "source": "Performance report", "verified": True, "tags": ["Python", "SQL", "python"]},
    )
    assert evidence.status_code == 201
    assert evidence.json()["tags"] == ["python", "sql"]
    assert len(client.get("/api/v1/evidence?verified=true", headers=auth_headers).json()) == 1

    scan = client.post("/api/v1/analysis", headers=auth_headers, json={"resume_text": RESUME, "jd_text": JOB, "job_id": job["id"]}).json()
    history = client.get("/api/v1/analysis/history", headers=auth_headers).json()
    assert history[0]["input_fingerprint"] == scan["input_fingerprint"]

    other = {"Authorization": "Bearer dev:user-2:other@example.com"}
    assert client.get(f"/api/v1/applications/{application['id']}/package", headers=other).status_code == 404
    assert client.patch(f"/api/v1/tasks/{task.json()['id']}", headers=other, json={"completed": False}).status_code == 404


def test_upload_validation_and_exports(client, auth_headers):
    invalid = client.post(
        "/api/v1/resumes/parse",
        headers=auth_headers,
        files={"file": ("resume.pdf", b"not a pdf", "application/pdf")},
    )
    assert invalid.status_code == 400

    pdf = client.post(
        "/api/v1/documents/export",
        headers=auth_headers,
        json={"text": RESUME, "format": "pdf", "filename_hint": "Alex Resume"},
    )
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF-")
    assert "Alex_Resume.pdf" in pdf.headers["content-disposition"]

    docx = client.post(
        "/api/v1/documents/export",
        headers=auth_headers,
        json={"text": RESUME, "format": "docx", "filename_hint": "Alex Resume"},
    )
    assert docx.status_code == 200
    assert docx.content.startswith(b"PK")
