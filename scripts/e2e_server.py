"""Dedicated local test server. Always uses a named SQLite test database."""
import hashlib
import os
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
os.chdir(root)
sys.path.insert(0, str(root))
os.environ.update(APP_ENV="test", AUTH_MODE="development", DATABASE_URL="sqlite:///./e2e.db", EMBEDDING_PROVIDER="lexical", RATE_LIMIT_PER_MINUTE="1000", CORS_ORIGINS="http://127.0.0.1:5174,http://localhost:5174")

from alembic import command
from alembic.config import Config
command.upgrade(Config(str(root / "alembic.ini")), "head")
from app import models
from app.database import SessionLocal
with SessionLocal() as db:
    if not db.get(models.User, 'local-user'):
        db.add(models.User(uid='local-user', email='local@example.com'))
        db.commit()
    if not db.query(models.PortfolioSource).filter_by(user_uid='local-user', repository='sample/api-service').first():
        source = models.PortfolioSource(user_uid='local-user', repository='sample/api-service', commit_sha='1' * 40, source_url='https://github.com/sample/api-service', description='Synthetic end-to-end test evidence, not a real repository.', is_fork=False, status='ready', relationship='personal', contribution='Synthetic fixture: implemented the test API service.', files=[])
        db.add(source)
        db.flush()
        content = 'Implemented Python FastAPI APIs with PostgreSQL persistence and request validation tests.'
        db.add(models.EvidenceChunk(user_uid='local-user', source_id=source.id, path='api.py', start_line=1, end_line=1, content=content, content_hash=hashlib.sha256(content.encode()).hexdigest(), source_url='https://github.com/sample/api-service/blob/' + '1' * 40 + '/api.py#L1', kind='implementation', review_status='approved', approved_statement=content, embedding_version='none'))
        db.commit()
import uvicorn
uvicorn.run('main:app', host='127.0.0.1', port=8011)
