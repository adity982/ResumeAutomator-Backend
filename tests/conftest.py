import os

os.environ["APP_ENV"] = "test"
os.environ["AUTH_MODE"] = "development"
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["RATE_LIMIT_PER_MINUTE"] = "1000"

import pytest
from fastapi.testclient import TestClient

from app.database import Base, engine
from main import app


@pytest.fixture(autouse=True)
def clean_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer dev:user-1:user@example.com"}
