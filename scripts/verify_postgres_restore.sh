#!/usr/bin/env bash
# CI only: creates two disposable databases in the isolated GitHub service container.
set -euo pipefail
: "${PG_CONTAINER:?GitHub PostgreSQL service container ID is required}"
docker exec "$PG_CONTAINER" createdb -U resume resume_backup_fixture
docker exec "$PG_CONTAINER" createdb -U resume resume_restore_fixture
export DATABASE_URL=postgresql+psycopg://resume:resume@localhost:5432/resume_backup_fixture
python -m alembic upgrade head
docker exec -i "$PG_CONTAINER" psql -v ON_ERROR_STOP=1 -U resume -d resume_backup_fixture <<'SQL'
INSERT INTO users(uid,email,created_at) VALUES ('restore-probe','synthetic@example.com',CURRENT_TIMESTAMP);
INSERT INTO workspace_drafts(user_uid,revision,data,updated_at) VALUES ('restore-probe',7,'{"restored":true}',CURRENT_TIMESTAMP);
SQL
docker exec "$PG_CONTAINER" pg_dump -U resume -Fc -f /tmp/restore-probe.dump resume_backup_fixture
docker exec "$PG_CONTAINER" pg_restore -U resume --exit-on-error --no-owner -d resume_restore_fixture /tmp/restore-probe.dump
export DATABASE_URL=postgresql+psycopg://resume:resume@localhost:5432/resume_restore_fixture
python - <<'PY'
from sqlalchemy import text
from app.database import SessionLocal
with SessionLocal() as db:
    row = db.execute(text("SELECT revision,data FROM workspace_drafts WHERE user_uid='restore-probe'")).one()
    assert row[0] == 7 and row[1] == {"restored": True}
    assert db.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == '0005_github'
    assert db.execute(text("SELECT '[1,2,3]'::vector <=> '[1,2,3]'::vector")).scalar_one() == 0
print('Synthetic PostgreSQL backup and restore verified; not a production backup claim.')
PY
