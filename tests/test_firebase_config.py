"""/api/firebase-config: enabled only with all six FIREBASE_* variables; read from the
environment, never from a .env file."""

import pytest
from fastapi.testclient import TestClient

from app import firebase_config
from app.main import app

VALUES = {"FIREBASE_API_KEY": "public-web-id", "FIREBASE_AUTH_DOMAIN": "x.firebaseapp.com", "FIREBASE_PROJECT_ID": "unbluffable",
          "FIREBASE_STORAGE_BUCKET": "unbluffable.appspot.com", "FIREBASE_MESSAGING_SENDER_ID": "123", "FIREBASE_APP_ID": "1:123:web:abc"}


def test_enabled_with_all_six(monkeypatch):
    for k, v in VALUES.items():
        monkeypatch.setenv(k, v)
    data = TestClient(app).get("/api/firebase-config").json()
    assert data == {"enabled": True, "config": {"apiKey": "public-web-id", "authDomain": "x.firebaseapp.com",
                                                "projectId": "unbluffable", "storageBucket": "unbluffable.appspot.com",
                                                "messagingSenderId": "123", "appId": "1:123:web:abc"}}
    assert "MODEL_API_KEY" not in str(data) and "BASETEN" not in str(data)


@pytest.mark.parametrize("missing", list(VALUES))
def test_disabled_if_any_is_missing(monkeypatch, missing):
    for k, v in VALUES.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv(missing, "  ")
    assert TestClient(app).get("/api/firebase-config").json() == {"enabled": False}


def test_no_env_file_is_read():
    source = open(firebase_config.__file__, encoding="utf-8").read()
    assert "dotenv" not in source and "open(" not in source
