import hashlib
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend import app as api
from backend import auth

PASSWORD = 'test-admin-password-not-real'


def sign_in(client):
    response = client.post('/api/auth/login', json={'username': 'admin', 'password': PASSWORD})
    assert response.status_code == 200
    return response


def test_guest_cannot_use_private_api_even_without_valid_body():
    with TestClient(api.app) as client:
        assert client.get('/api/auth/me').json() == {'is_admin': False, 'username': None}
        assert client.get('/api/health').json()['is_admin'] is False
        assert client.post('/api/analyses', content=b'not-a-form').status_code == 401
        assert client.get('/api/analyses/guessed-id').status_code == 401
        assert client.get('/api/analyses').status_code == 401


def test_wrong_credentials_are_generic_and_no_cookie():
    with TestClient(api.app) as client:
        first = client.post('/api/auth/login', json={'username': 'admin', 'password': 'wrong'})
        second = client.post('/api/auth/login', json={'username': 'someone', 'password': PASSWORD})
        assert first.status_code == second.status_code == 401
        assert first.json() == second.json()
        assert auth.COOKIE_NAME not in client.cookies


def test_login_cookie_me_logout_and_token_revocation():
    with TestClient(api.app) as client:
        response = sign_in(client)
        header = response.headers['set-cookie'].lower()
        assert 'httponly' in header and 'samesite=strict' in header and 'max-age=28800' in header
        assert 'password' not in response.text
        token = client.cookies[auth.COOKIE_NAME]
        assert token not in auth.sessions
        assert hashlib.sha256(token.encode()).hexdigest() in auth.sessions
        assert client.get('/api/auth/me').json() == {'is_admin': True, 'username': 'admin'}
        assert client.get('/api/health').json()['is_admin'] is True
        assert client.get('/api/analyses/unknown').status_code == 404
        assert client.post('/api/auth/logout').status_code == 200
        assert client.get('/api/auth/me').json()['is_admin'] is False
        client.cookies.set(auth.COOKIE_NAME, token)
        assert client.get('/api/analyses/unknown').status_code == 401


def test_tampered_expired_and_rotated_password_session(monkeypatch):
    with TestClient(api.app) as client:
        sign_in(client)
        token = client.cookies[auth.COOKIE_NAME]
        digest = hashlib.sha256(token.encode()).hexdigest()
        original = auth.sessions[digest].copy()
        client.cookies.clear()
        client.cookies.set(auth.COOKIE_NAME, token + 'tamper')
        assert client.get('/api/analyses/unknown').status_code == 401
        client.cookies.clear()
        client.cookies.set(auth.COOKIE_NAME, token)
        auth.sessions[digest]['expires'] = auth._now() - 1
        assert client.get('/api/analyses/unknown').status_code == 401
        auth.sessions[digest] = original
        monkeypatch.setenv('ADMIN_PASSWORD_HASH', auth.hash_password('new-password'))
        assert client.get('/api/auth/me').json()['is_admin'] is False


def test_failed_login_rate_limit_and_reset(monkeypatch):
    with TestClient(api.app) as client:
        for _ in range(5):
            assert client.post('/api/auth/login', json={'username': 'admin', 'password': 'wrong'}).status_code == 401
        blocked = client.post('/api/auth/login', json={'username': 'admin', 'password': PASSWORD})
        assert blocked.status_code == 429
        assert blocked.headers['retry-after'] == '600'
        now = auth._now()
        monkeypatch.setattr(auth, '_now', lambda: now + 601)
        sign_in(client)


def test_foreign_origin_rejected_before_login_or_mutation():
    with TestClient(api.app) as client:
        res = client.post('/api/auth/login', headers={'Origin': 'https://attacker.example'},
                          json={'username': 'admin', 'password': PASSWORD})
        assert res.status_code == 403
        sign_in(client)
        assert client.post('/api/auth/logout', headers={'Origin': 'https://attacker.example'}).status_code == 403
        assert client.post('/api/analyses', headers={'Origin': 'null'}).status_code == 403
        assert client.get('/api/auth/me').json()['is_admin'] is True
        assert client.post('/api/auth/logout', headers={'Origin': 'http://localhost:5173'}).status_code == 200


def test_hash_and_unconfigured_admin(monkeypatch):
    encoded = auth.hash_password('password')
    assert auth.verify_password('password', encoded)
    assert not auth.verify_password('wrong', encoded)
    assert not auth.verify_password('password', 'plaintext-password')
    monkeypatch.delenv('ADMIN_PASSWORD_HASH')
    with TestClient(api.app) as client:
        assert client.post('/api/auth/login', json={'username': 'admin', 'password': PASSWORD}).status_code == 401
