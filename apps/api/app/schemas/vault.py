from datetime import datetime
from pydantic import BaseModel, ConfigDict
import uuid
from typing import Optional

class CredentialCreate(BaseModel):
    provider: str
    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[datetime] = None

class CredentialResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    provider: str
    expires_at: Optional[datetime]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
