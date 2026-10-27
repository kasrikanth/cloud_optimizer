import os
from contextlib import contextmanager
from pathlib import Path
import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Keep tests isolated: never consume DATABASE_URL from the real .env.
test_url = os.environ.get('TEST_DATABASE_URL', 'sqlite+pysqlite:///:memory:')
if make_url(test_url).get_backend_name() == 'postgresql' and not (make_url(test_url).database or '').endswith('_test'):
    raise RuntimeError('TEST_DATABASE_URL must point to a dedicated database ending in _test')
os.environ['DATABASE_URL'] = test_url
os.environ['LLM_API_KEY'] = ''
os.environ['LLM_MODEL'] = ''
os.environ['SYNC_ENABLED'] = 'false'
from cryptography.fernet import Fernet
os.environ['SECRETS_KEY'] = Fernet.generate_key().decode()

from fastapi.testclient import TestClient
from app import auth
from app.db import Base, get_db
from app.main import app
from app.tenant import bind

options = {'connect_args': {'check_same_thread': False}, 'poolclass': StaticPool} if test_url.startswith('sqlite') else {}
test_engine = create_engine(test_url, **options)
TestSession = sessionmaker(bind=test_engine, expire_on_commit=False)

PASSWORD = 'correct-horse-1'


@pytest.fixture
def client():
    # Tables belong only to the explicitly isolated test database.
    Base.metadata.drop_all(test_engine)
    Base.metadata.create_all(test_engine)
    auth._failures.clear()
    def override_db():
        with TestSession() as db:
            yield db
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
    auth._failures.clear()


def signup(client, organization='Test Org', email='admin@test.example', password=PASSWORD):
    """Register an organization and its admin. Returns the JSON body (token, user, organization)."""
    response = client.post('/api/auth/signup', json={'organization': organization, 'email': email, 'password': password})
    assert response.status_code == 200, response.text
    return response.json()


def bearer(session):
    return {'Authorization': 'Bearer ' + session['token']}


@pytest.fixture
def session(client):
    return signup(client)


@pytest.fixture
def headers(session):
    return bearer(session)


@pytest.fixture
def org_id(session):
    return session['organization']['id']


@pytest.fixture
def other_headers(client, session):
    """A second, unrelated organization."""
    return bearer(signup(client, 'Other Org', 'admin@other.example'))


@pytest.fixture
def sample():
    import json
    return json.loads((Path(__file__).parents[1] / 'app/sample_inventory.json').read_text())


class OrgSessions:
    """Database sessions bound to the default test organization, for tests that write rows directly."""
    def __init__(self, org_id):
        self.org_id = org_id

    def __call__(self):
        return bind(TestSession(), self.org_id)

    @contextmanager
    def begin(self):
        with TestSession.begin() as db:
            yield bind(db, self.org_id)


@pytest.fixture
def session_factory(org_id):
    return OrgSessions(org_id)
