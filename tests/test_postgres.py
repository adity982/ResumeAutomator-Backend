import os

import pytest

from app.database import engine
from app.services import embeddings
from test_portfolio import seed_source, job, STATEMENT, OTHER


@pytest.mark.skipif(engine.dialect.name != 'postgresql', reason='PostgreSQL/pgvector integration runs in its CI service job.')
def test_exact_pgvector_retrieval_keeps_tenant_scope(client, auth_headers, monkeypatch):
    monkeypatch.setattr(embeddings, 'embed', lambda texts, **kwargs: [[1.0] + [0.0] * 383 for _ in texts])
    monkeypatch.setattr(embeddings, 'version', lambda: 'integration-test:384')
    source, evidence = seed_source(client, auth_headers, monkeypatch)
    other_source, other_evidence = seed_source(client, OTHER, monkeypatch, repository='other/private-context')
    for headers, evidence_id in [(auth_headers, evidence), (OTHER, other_evidence)]:
        assert client.patch(f'/api/v1/project-evidence/{evidence_id}', headers=headers, json={'status': 'approved', 'statement': STATEMENT}).status_code == 200
    target = job(client, auth_headers)
    result = client.post(f'/api/v1/jobs/{target}/projects', headers=auth_headers, json={'mode': 'hybrid'}).json()
    assert result['projects'][0]['source_id'] == source
    assert all(c['source_id'] != other_source for requirement in result['requirements'] for c in requirement['citations'])
