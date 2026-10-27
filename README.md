# Resume Automator API

FastAPI backend for a developer career workspace: select relevant projects, trace claims to source evidence, prepare reviewed application documents, and track the next step.

[Frontend](https://github.com/adity982/ResumeAutomator-Frontend) · [Architecture](docs/ARCHITECTURE.md) · [Operations](docs/OPERATIONS.md)

## Core workflow

1. Save a job snapshot and resume context.
2. Preview selected public GitHub files, or connect a configured GitHub App for selected private repositories, at an immutable commit.
3. Queue a durable import and review your personal contribution separately from repository observations.
4. Retrieve supporting evidence using a lexical baseline or learned 384-dimensional FastEmbed vectors with pgvector and hybrid fusion.
5. Select complementary projects and create cited, extractive resume bullets from reviewed statements.
6. Preview the actual generated PDF, approve an exact document version, and attach it to an application.
7. Save progress, track contacts and follow-ups manually, practice interviews and record pilot feedback.

Private GitHub authorization is optional and requires operator registration; see [GitHub App activation](docs/GITHUB-APP.md). This release does not provide LinkedIn people-search APIs, profile scraping, automatic messaging or autonomous applying. Discovery produces search links, not verified vacancies. Resume coverage and interview feedback are transparent heuristics, not hiring predictions.

## Stack and setup

Python 3.12, FastAPI, SQLAlchemy/Alembic, Firebase identity, PostgreSQL/pgvector in production, SQLite for local compatibility, and optional FastEmbed/ONNX inference. PDF export bundles Unicode fonts; unsupported glyphs produce an explicit error rather than silent deletion. DOCX applies the selected document theme.

```text
python -m venv .venv
python -m pip install -r requirements-dev.txt
python -m pip install -r requirements-rag.txt
```

Activate the environment, copy `.env.example` to `.env`, then:

```text
python -m alembic upgrade head
python -m uvicorn main:app --reload
```

Run `python -m app.worker` in a second terminal with the same environment and database. Set `EMBEDDING_PROVIDER=fastembed` for learned vectors; the default `lexical` baseline needs no model download and is explicitly labeled. Production must use Firebase authentication and an explicit CORS allowlist. See the operations guide for PostgreSQL, model warm-up, worker deployment, budgets, restore testing and rollout order.

## API areas

| Area | Endpoints |
| --- | --- |
| Portfolio | `/api/v1/sources/preview`, `/sources`, `/imports`, `/project-evidence/{id}` |
| Selection | `/api/v1/jobs/{id}/projects` |
| Workspace | `/api/v1/workspace` with revision-checked save/recovery |
| Applications | `/api/v1/applications`, `/applications/{id}/events`, `/applications/{id}/package` |
| Documents | `/api/v1/resumes/parse`, `/documents`, `/documents/export` |
| Contacts/outreach | `/api/v1/contacts`, `/outreach` with editable drafts and manual delivery status |
| Practice/feedback | `/api/v1/interviews`, `/pilot/feedback`, `/pilot/summary` |
| Privacy | `/api/v1/account/export`, `DELETE /api/v1/account` |
| Operations | `/health/live`, `/health/ready`, `/metrics`, `/api/v1/capabilities` |

Interactive API schemas are available at `/docs` unless disabled. All private resources are scoped to the verified user. Source citations are re-resolved server-side, and changed or removed evidence invalidates dependent retrieval histories and application-package checks. Repository content is untrusted data, never executable instructions.

## Validation

```text
python -m compileall -q app main.py
pytest --cov=app --cov-report=term-missing
python -m evaluations.run --output evaluation-results/retrieval.json
```

The versioned evaluation fixture contains 60 synthetic relevance queries, including paraphrases, hard negatives and missing-evidence cases. With FastEmbed enabled it compares lexical, dense and hybrid retrieval. It is a regression benchmark, not a user study or production load test. CI exercises API behavior on SQLite and PostgreSQL/pgvector and checks migration upgrades. The frontend repository owns the cross-repository browser journey.

## Privacy and retention

Uploaded PDF bytes are not retained by the parsing route. Saved text, workspace drafts, public source excerpts, reviewed claims, contacts, answers and feedback are persisted until deleted. Resume drafts are not written to browser local storage. Users can export account data, forget progress and remove sources. Deleting application data does not delete the Google/Firebase sign-in identity. Hashed usage windows expire within 24 hours; operators must separately document log and backup retention.

Optional Groq cover-letter polishing sends its supplied draft to Groq when configured. The flagship project-selection/drafting path uses local retrieval and exact reviewed statements, without an external generation API charge. User review remains necessary; retrieval and keyword checks cannot independently prove personal authorship or semantic truth.
