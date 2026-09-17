from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import Field, StringConstraints

from hub.technicians.schemas import InputModel


class Login(InputModel):
    username: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    password: Annotated[str, Field(min_length=1, max_length=128)]
    # Preserve password whitespace; it is part of the credential.
    model_config = {"extra": "forbid", "str_strip_whitespace": False}


class ManagerRead(InputModel):
    id: UUID
    username: str
    csrf_token: str
    expires_at: datetime
