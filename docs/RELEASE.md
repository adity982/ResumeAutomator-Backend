# Production release and recovery

## Current topology and remaining provider actions

The existing frontend is Vercel project `resume-automator-frontend`; its production bundle points at `https://resume-automator-api.onrender.com/api/v1`. The connected Vercel account does not manage that Render API, its worker or database. Do not promote the dependent frontend until the backend contract is deployed and verified.

`render.yaml` is a reviewable blueprint, not evidence of provisioning. It references a shared environment group `resume-automator-production` and paid starter API/worker plans. Reconcile it with the existing service before importing; do not create a second API accidentally. The PostgreSQL database is supplied separately and must support pgvector. No paid resources are purchased by committing this file.

## Provider configuration

In Render's encrypted environment group set `APP_ENV=production`, `AUTH_MODE=firebase`, `DATABASE_URL`, `FIREBASE_PROJECT_ID`, `CORS_ORIGINS=https://resume-automator-frontend.vercel.app`, `EMBEDDING_PROVIDER=fastembed`, `EMBEDDING_MODEL=BAAI/bge-small-en-v1.5`, `MODEL_CACHE_DIR=/models`, and `DOCS_ENABLED=false`. Use a PostgreSQL TLS connection supported by the database provider and its certificate policy. Do not use development authentication or copy local test fixtures into production.

API and worker use the same database/model settings. Each container warms its own model at startup. The Docker image creates a writable `/models` directory; ephemeral containers download weights again after replacement. A persistent model disk is optional and must be configured per service rather than assumed shared across hosts. Record the Render commit and image/deployment ID for both processes.

Vercel needs the backend base URL and the existing Firebase client configuration in production. Preview has a separate configuration: use a staging API and Firebase authorized domain before claiming a signed-in preview passes. A successful static preview build alone does not validate authentication.

## Exact release sequence

1. Freeze the release commits and retain the current frontend/backend deployment IDs.
2. Take a provider snapshot and a custom-format `pg_dump` backup of the actual database. Store it in encrypted restricted storage, never as a GitHub artifact. Record timestamp, database identity, schema revision and SHA-256 checksum.
3. Restore that backup into a separate staging database with the same PostgreSQL major version and pgvector extension. Compare owned document/source counts and representative document content. Apply the release migrations there, verify data and complete a staging task. CI's synthetic restore drill is useful evidence, but is not this production restore.
4. Register/configure the GitHub App if private access is required; follow `GITHUB-APP.md`.
5. Deploy the backend from the reviewed commit. Render's pre-deploy command migrates and runs `scripts/release_preflight.py`; inspect the sanitized result. Start the worker from the same commit. Check actual queued → completed import processing, not merely that the worker process exists.
6. Run `python scripts/check_deployment.py --api https://resume-automator-api.onrender.com --frontend https://resume-automator-frontend.vercel.app --revision BACKEND_COMMIT`. Record the result with the exact commits.
7. With a verified Firebase test identity, complete save job → import → review contribution → choose projects → inspect citation → preview PDF → approve → save/recover → attach → change stage. Verify a second identity cannot read the first identity's records. Delete the test data afterwards.
8. Build the frontend in the production environment without assigning the public domain. Verify its commit/API configuration, then promote it. Repeat the real signed-in journey and mobile check against the public domain.

## Recovery

For a frontend regression, restore the previous Vercel deployment. For a backend regression, restore the previous compatible image/commit and stop the new worker before it writes. Prefer forward schema repair; a downgrade can delete new tables and data. Restore a database backup only into a separate database first, validate it, and deliberately switch the connection during a maintenance window. Record the data-loss window and reconcile any writes after the backup before reopening traffic. Never overwrite the sole database while testing recovery.

## Monitoring and operator ownership

Configure an uptime monitor for `/health/live` and `/health/ready` every minute with an alert after three consecutive failures. Route alerts to the actual operator's chosen channel. In Render configure alerts for service failures/restarts, memory pressure and worker failures; inspect failed/queued imports and request-error rates. Target a five-minute queue-age alert and alert on a 5xx rate over 5% for five minutes when traffic is meaningful. `/metrics` is per-process and is not a durable cross-instance monitoring system.

Set provider-level spending alerts and a maximum monthly budget before inviting users. Application request quotas do not enforce infrastructure spend. Assign an operator and record the monitor destinations and budgets in the private release record; do not claim they exist before they are configured.

## Retention policy proposed for the pilot

Saved account content is retained until the user deletes it. Imported excerpts also remain until source/account deletion; disconnecting GitHub removes credentials only. Proposed operational policy: seven daily encrypted backups, fourteen days of redacted operational logs, no document bodies/tokens in logs, and access restricted to the operator. Enable these settings in the actual providers and confirm them before publishing them as enforced policy. Deletion from active storage is immediate at the application layer; backups age out according to the configured policy. Firebase identity deletion is a separate account operation. Store pilot consent and research notes separately; remove identifying notes within thirty days after the study unless the participant consents to longer retention.
