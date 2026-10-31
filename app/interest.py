"""/api/interest (decision log 23): which roles a candidate is preparing for, sent only when
they tick "Share this so we know what to build next". Writes one structured log line with
the roles and the optional note: no IP address, no id, nothing stored."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field, field_validator

ROLES = ("quant", "quant_dev", "ib", "consulting", "software", "other")
log = logging.getLogger("unbluffable.interest")
router = APIRouter(prefix="/api")


class Interest(BaseModel):
    model_config = {"extra": "forbid"}
    roles: list[str] = Field(max_length=len(ROLES))
    other_text: str = Field(default="", max_length=200)

    @field_validator("roles")
    @classmethod
    def known(cls, roles):
        if any(r not in ROLES for r in roles) or len(set(roles)) != len(roles):
            raise ValueError("unknown or repeated role")
        return roles


@router.post("/interest", status_code=204)
def interest(body: Interest) -> Response:
    log.info(json.dumps({"event": "interest", "roles": body.roles, "other_text": " ".join(body.other_text.split())}))
    return Response(status_code=204)
