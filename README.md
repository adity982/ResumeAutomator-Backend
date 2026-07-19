# Resume Automator API

FastAPI service for secure resume parsing, evidence-backed job matching,
versioned documents, applications, interview coaching, outreach, discovery,
and career analytics.

## Local setup

1. Create a virtual environment and install `requirements-dev.txt`.
2. Copy `.env.example` to `.env` and keep `AUTH_MODE=development` only locally.
3. Run `alembic upgrade head`.
4. Start with `uvicorn main:app --reload`.

Local clients authenticate with `Authorization: Bearer dev:<uid>:<email>`. In
production set `APP_ENV=production`, `AUTH_MODE=firebase`, and
`FIREBASE_PROJECT_ID`; the server verifies Firebase ID tokens and derives the
user ID rather than trusting request data.

## Privacy and security

Uploaded PDFs are validated and parsed in memory; they are not retained. The
service limits file size/page count, blocks private and metadata destinations
in the URL scraper, enforces resource ownership, bounds cache/rate usage, and
redacts request logs. `DELETE /api/v1/account` removes a user and associated
records through database cascades.

## Database and deployment

`DATABASE_URL` defaults to SQLite for development and supports PostgreSQL in
production. Schema changes are managed by Alembic. Back up the production
database before migrations and test restore procedures regularly. Deployments
should run `alembic upgrade head` before starting the API.

API documentation is available at `/docs` unless `DOCS_ENABLED=false`.

## Market-informed workflow APIs

- `GET|POST|PATCH|DELETE /api/v1/evidence` manages the verified career-evidence vault.
- `GET|POST|PATCH|DELETE /api/v1/tasks` manages application-linked follow-up reminders.
- `GET /api/v1/applications/{id}/package` returns server-calculated package readiness.
- `GET /api/v1/analysis/history` returns reproducible score provenance and scan history.
- `POST /api/v1/interviews` persists a role-specific preparation brief with each session.
