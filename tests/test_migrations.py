import os
from pathlib import Path
import subprocess
import sys

from sqlalchemy import create_engine, inspect, text


def test_upgrade_preserves_previous_release_documents(tmp_path):
    root = Path(__file__).resolve().parents[1]
    url = 'sqlite:///' + (tmp_path / 'upgrade.db').as_posix()
    env = dict(os.environ, APP_ENV='test', AUTH_MODE='development', DATABASE_URL=url)
    def migrate(target, command='upgrade'):
        subprocess.run([sys.executable, '-m', 'alembic', command, target], cwd=root, env=env, capture_output=True, text=True, check=True)
    migrate('0002_market_features')
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO users(uid,email,created_at) VALUES ('legacy','legacy@example.com',CURRENT_TIMESTAMP)"))
        connection.execute(text("INSERT INTO document_versions(logical_id,user_uid,kind,title,original_text,content,template,version,approved,created_at) VALUES ('legacy-document','legacy','resume','Legacy resume','Original','Keep this content','standard',1,1,CURRENT_TIMESTAMP)"))
    migrate('head')
    with engine.connect() as connection:
        row = connection.execute(text("SELECT content,content_hash,evidence_snapshot FROM document_versions")).one()
        assert row[0] == 'Keep this content' and row[1] == '' and row[2] == '[]'
        assert 'evidence_chunks' in inspect(connection).get_table_names()
        assert 'usage_windows' in inspect(connection).get_table_names()
    migrate('0002_market_features', 'downgrade')
    migrate('head')
    with engine.connect() as connection:
        assert connection.execute(text("SELECT content FROM document_versions")).scalar() == 'Keep this content'


def test_frozen_initial_migration_does_not_import_current_models():
    source = (Path(__file__).resolve().parents[1] / 'alembic/versions/0001_initial_schema.py').read_text()
    assert 'from app' not in source and 'create_all' not in source
