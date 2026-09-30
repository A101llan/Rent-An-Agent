"""
Vault credential endpoints.

All access_token / refresh_token values are stored **encrypted** (Fernet AES).
The API *never* returns raw token values — only provider metadata is returned,
matching `CredentialResponse` which deliberately omits secret fields.

Endpoints
---------
GET    /vault/              — list connected providers (no token values)
POST   /vault/connect       — store a new credential (encrypted)
DELETE /vault/{provider}    — revoke / delete a credential
POST   /vault/rotate-key    — admin: re-encrypt every row with the current key
                              (call after rotating VAULT_ENCRYPTION_KEY in env)
"""
from __future__ import annotations

from typing import Annotated, List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser, RequireAdmin
from app.core.vault_crypto import decrypt_token, encrypt_token, is_encrypted, rotate_token
from app.db.session import get_db
from app.models import VaultCredential
from app.schemas.vault import CredentialCreate, CredentialResponse

router = APIRouter()
DbSession = Annotated[AsyncSession, Depends(get_db)]


# ---------------------------------------------------------------------------
# List credentials (metadata only — no secret values)
# ---------------------------------------------------------------------------

@router.get("/", response_model=List[CredentialResponse])
async def list_credentials(db: DbSession, current_user: CurrentUser):
    """Return all connected providers for the current user (no token values)."""
    result = await db.execute(
        select(VaultCredential).where(VaultCredential.user_id == current_user.id)
    )
    return result.scalars().all()


# ---------------------------------------------------------------------------
# Connect / store a credential
# ---------------------------------------------------------------------------

@router.post("/connect", response_model=CredentialResponse, status_code=status.HTTP_201_CREATED)
async def connect_credential(cred: CredentialCreate, db: DbSession, current_user: CurrentUser):
    """
    Store OAuth / API credentials for *provider*, encrypted with Fernet.

    If a credential for this provider already exists it is **replaced**
    (upsert behaviour) so callers can re-connect after a token refresh.
    """
    # Check for existing record — upsert
    result = await db.execute(
        select(VaultCredential).where(
            VaultCredential.user_id == current_user.id,
            VaultCredential.provider == cred.provider,
        )
    )
    db_cred = result.scalar_one_or_none()

    encrypted_access = encrypt_token(cred.access_token)
    encrypted_refresh = encrypt_token(cred.refresh_token) if cred.refresh_token else None

    if db_cred:
        db_cred.access_token = encrypted_access
        db_cred.refresh_token = encrypted_refresh
        db_cred.expires_at = cred.expires_at
    else:
        db_cred = VaultCredential(
            user_id=current_user.id,
            provider=cred.provider,
            access_token=encrypted_access,
            refresh_token=encrypted_refresh,
            expires_at=cred.expires_at,
        )
        db.add(db_cred)

    await db.commit()
    await db.refresh(db_cred)
    return db_cred


# ---------------------------------------------------------------------------
# Revoke credential
# ---------------------------------------------------------------------------

@router.delete("/{provider}", status_code=status.HTTP_200_OK)
async def revoke_credential(provider: str, db: DbSession, current_user: CurrentUser):
    """Permanently delete stored credentials for *provider*."""
    result = await db.execute(
        select(VaultCredential).where(
            VaultCredential.user_id == current_user.id,
            VaultCredential.provider == provider,
        )
    )
    db_cred = result.scalar_one_or_none()
    if not db_cred:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found")

    await db.delete(db_cred)
    await db.commit()
    return {"message": f"Credential for '{provider}' revoked"}


# ---------------------------------------------------------------------------
# Key rotation (admin only)
# ---------------------------------------------------------------------------

@router.post("/rotate-key", status_code=status.HTTP_200_OK)
async def rotate_vault_key(db: DbSession, _admin: RequireAdmin):
    """
    Re-encrypt every vault credential row with the **current** active Fernet key.

    Run this endpoint after updating `VAULT_ENCRYPTION_KEY` in your environment
    (and setting the old key as `VAULT_ENCRYPTION_KEY_PREVIOUS`). Once complete
    you may remove the old key from the environment and restart the server.

    Returns a summary of how many rows were rotated.
    """
    result = await db.execute(select(VaultCredential))
    creds: list[VaultCredential] = result.scalars().all()

    rotated = 0
    skipped = 0
    errors = 0

    for cred in creds:
        try:
            # Rotate access_token
            if is_encrypted(cred.access_token):
                cred.access_token = rotate_token(cred.access_token)
            else:
                # Legacy plaintext row — encrypt it now
                cred.access_token = encrypt_token(cred.access_token)

            # Rotate refresh_token if present
            if cred.refresh_token:
                if is_encrypted(cred.refresh_token):
                    cred.refresh_token = rotate_token(cred.refresh_token)
                else:
                    cred.refresh_token = encrypt_token(cred.refresh_token)

            rotated += 1
        except Exception:
            errors += 1

    await db.commit()

    return {
        "rotated": rotated,
        "skipped": skipped,
        "errors": errors,
        "total": len(creds),
    }
