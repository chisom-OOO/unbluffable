"""/api/firebase-config: the Firebase web config from the six FIREBASE_* environment
variables (set on Render), or {"enabled": false} if any is missing, in which case the
pages show no sign-in at all.

Firebase's web apiKey is a public project identifier, not a secret: access is decided by
firestore.rules. No server secret (model or Baseten keys) is ever sent to the browser,
and no .env file is read here."""

from __future__ import annotations

import json
import os

from fastapi import APIRouter, Response

router = APIRouter(prefix="/api")

FIELDS = {
    "apiKey": "FIREBASE_API_KEY",
    "authDomain": "FIREBASE_AUTH_DOMAIN",
    "projectId": "FIREBASE_PROJECT_ID",
    "storageBucket": "FIREBASE_STORAGE_BUCKET",
    "messagingSenderId": "FIREBASE_MESSAGING_SENDER_ID",
    "appId": "FIREBASE_APP_ID",
}


def web_config() -> dict:
    values = {field: os.environ.get(name, "").strip() for field, name in FIELDS.items()}
    if not all(values.values()):
        return {"enabled": False}
    return {"enabled": True, "config": values}


@router.get("/firebase-config")
def firebase_config() -> Response:
    return Response(json.dumps(web_config()), media_type="application/json", headers={"Cache-Control": "no-cache"})
