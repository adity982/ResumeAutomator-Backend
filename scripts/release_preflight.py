"""Read-only deployment gate. Run inside the intended API/worker environment."""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from app.config import settings
from app.database import SessionLocal
from app.services import embeddings, github_connection


def check():
    settings.validate()
    if settings.app_env != "production" or settings.auth_mode != "firebase":
        raise ValueError("Production and Firebase authentication must be configured.")
    if not settings.database_url.startswith(("postgres://", "postgresql://", "postgresql+psycopg://")):
        raise ValueError("Production requires PostgreSQL, not the local SQLite database.")
    if not settings.cors_origins or any(not value.startswith("https://") or "localhost" in value or "*" in value for value in settings.cors_origins):
        raise ValueError("Configure exact HTTPS frontend origins.")
    if settings.embedding_provider != "fastembed":
        raise ValueError("The vector release requires FastEmbed to be enabled.")
    root = Path(__file__).resolve().parents[1]
    head = ScriptDirectory.from_config(Config(str(root / "alembic.ini"))).get_current_head()
    with SessionLocal() as db:
        if db.execute(text("SELECT version_num FROM alembic_version")).scalar_one() != head:
            raise ValueError("Database migrations do not match this release.")
        db.execute(text("SELECT '[1,2,3]'::vector <=> '[1,2,3]'::vector"))
    vector = embeddings.embed(["Deployment model warm-up probe"])[0]
    if vector is None or len(vector) != 384:
        raise ValueError("Embedding model warm-up did not produce the expected dimensions.")
    if github_connection.configured():
        github_connection.cipher()
    revision = os.getenv("RENDER_GIT_COMMIT") or os.getenv("RELEASE_SHA")
    if not revision:
        raise ValueError("Release commit is not recorded by the environment.")
    return {"status": "passed", "revision": revision, "schema": head, "embedding_version": embeddings.version(), "private_github_configured": github_connection.configured(), "limits": "Does not prove Firebase login, backups, worker processing, or user task completion."}


if __name__ == "__main__":
    try:
        print(json.dumps(check(), indent=2))
    except Exception as exc:
        # Connection exceptions can contain database credentials; never print them.
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__, "action": "Inspect configuration, migration state and model availability in the operator console."}))
        sys.exit(1)
