# Run and verify

## Local development

Use Python 3.12. Install `requirements-dev.txt` for the API/tests. To run learned embeddings, also install `requirements-rag.txt` and set `EMBEDDING_PROVIDER=fastembed`. The default `lexical` mode works without a model download and is labeled as such in results.

Copy `.env.example` to `.env`, keep development authentication local, and run:

```text
python -m pip install -r requirements-dev.txt
python -m pip install -r requirements-rag.txt
python -m alembic upgrade head
python -m uvicorn main:app --reload
```

In another terminal, using the same environment/database:

```text
python -m app.worker
```

The first model load downloads model weights to `MODEL_CACHE_DIR`. Warm the model before accepting production traffic. API and worker must share the same model configuration and database. A missing worker leaves imports queued; this is visible in the UI. A failed model load retries with backoff and eventually reports failure rather than silently returning fake embeddings.

## PostgreSQL and deployment

`compose.yaml` provides PostgreSQL/pgvector, a migration job, API and worker. Set a strong URL-safe `POSTGRES_PASSWORD` in `.env` before `docker compose up --build`. For production set `APP_ENV=production`, `AUTH_MODE=firebase`, the actual `FIREBASE_PROJECT_ID`, an explicit `CORS_ORIGINS` allowlist and `DOCS_ENABLED=false` if appropriate. Serve HTTPS through your deployment ingress. Do not expose development authentication publicly.

Migrations enable the vector extension; the managed database must support it and the migration identity must be allowed to install it. The initial migration is frozen, independent of future model imports. Migration tests upgrade data from the prior release, downgrade and re-upgrade. CI also runs the API suite against PostgreSQL/pgvector.

Before a production rollout:

1. Back up the existing database and prove a restore in a separate environment.
2. Run the migration on a staging copy. Preserve the current release and database checkpoint for recovery.
3. Configure Firebase, database, CORS and embedding settings. Keep provider tokens server-side.
4. Start the worker and API, pre-warm embeddings, and verify liveness/readiness, sign-in, import, review, selection, PDF export and deletion with test accounts.
5. Deploy the backend contract before the frontend that consumes it. Keep both release commits in deployment records.
6. Observe errors and latency. A GitHub check passing does not prove production credentials, backup restoration or the real deployment revision.

The application uses shared database-backed limits by authenticated user, plus a coarse pre-authentication IP limit. Expensive operations are limited to ten per minute and 200 per day per user. These are request budgets, not currency accounting. Infrastructure concurrency/ingress limits, external provider account spending limits, log retention, encrypted storage and backup retention remain deployment responsibilities.

## Privacy and retention

PDF bytes are not retained by the parsing route. Saved document text, workspace drafts, source excerpts, contribution statements, interview answers, contacts and feedback are persisted until the user deletes them. Local browser storage is not used for resume drafts; account-scoped Save progress and explicit recovery replace it. Old unscoped browser drafts are cleared when entering the authenticated workspace.

Users can export account records, forget workspace progress, remove sources/contacts, or delete all application records. Deletion does not remove the Google/Firebase sign-in identity. Shared hashed usage windows expire within 24 hours. Operators must document backup/log retention before a public launch; application deletion does not erase old backups automatically.

Repository files and job descriptions are untrusted data. The extractive pipeline never treats their instructions as executable tool requests. Outbound job scraping checks public destinations on every redirect, pins the validated IP for the actual connection, preserves the original Host/TLS name and streams with a size limit. Keep ingress request-body and network egress controls as defense in depth.

## Verification commands

```text
python -m compileall -q app main.py
pytest --cov=app --cov-report=term-missing
python -m evaluations.run --output evaluation-results/retrieval.json
```

Set `EMBEDDING_PROVIDER=fastembed` for the learned-vector benchmark. Model/version and limitations are included in the result. Never present the small synthetic fixture as a production load test or a user study.

The frontend's `Application journey` workflow checks out the matching backend feature branch when available, falling back to main. Its dedicated `scripts/e2e_server.py` always uses a named local test database and synthetic evidence; do not use this server for production.

## Release artifacts

See RELEASE.md for the Render API/worker blueprint, actual-backup restore procedure, release probes, rollback, monitoring and retention configuration. See GITHUB-APP.md for selected private repository authorization. Private access remains unavailable until the operator supplies a registered App and encryption settings. Run scripts/release_preflight.py inside the intended production environment before traffic promotion.
