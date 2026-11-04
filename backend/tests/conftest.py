import pytest
from backend import auth

TEST_PASSWORD = 'test-admin-password-not-real'
TEST_HASH = auth.hash_password(TEST_PASSWORD)

@pytest.fixture(autouse=True)
def isolated_admin(monkeypatch):
    monkeypatch.setenv('ADMIN_USERNAME', 'admin')
    monkeypatch.setenv('ADMIN_PASSWORD_HASH', TEST_HASH)
    monkeypatch.setenv('COOKIE_SECURE', 'false')
    auth.sessions.clear()
    auth.failures.clear()
    yield
    auth.sessions.clear()
    auth.failures.clear()
