from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import (
    PlatformFee,
    Transaction,
    TransactionStatus,
    TransactionType,
)


@dataclass
class ChargeResult:
    transaction: Transaction
    success: bool


class BillingProvider:
    async def charge(
        self,
        db: AsyncSession,
        *,
        customer_id: UUID,
        gross_amount_minor: int,
        currency: str,
        rental_id: UUID | None = None,
        session_id: UUID | None = None,
        idempotency_key: str | None = None,
        transaction_type: TransactionType = TransactionType.CHARGE,
    ) -> ChargeResult:
        raise NotImplementedError


class MockBillingProvider(BillingProvider):
    async def charge(
        self,
        db: AsyncSession,
        *,
        customer_id: UUID,
        gross_amount_minor: int,
        currency: str,
        rental_id: UUID | None = None,
        session_id: UUID | None = None,
        idempotency_key: str | None = None,
        transaction_type: TransactionType = TransactionType.CHARGE,
    ) -> ChargeResult:
        if idempotency_key:
            from sqlalchemy import select
            existing = await db.execute(
                select(Transaction).where(Transaction.idempotency_key == idempotency_key)
            )
            tx = existing.scalar_one_or_none()
            if tx:
                return ChargeResult(transaction=tx, success=tx.status == TransactionStatus.COMPLETED)

        platform_fee = (gross_amount_minor * settings.platform_fee_bps) // 10000
        developer_amount = gross_amount_minor - platform_fee

        tx = Transaction(
            customer_id=customer_id,
            rental_id=rental_id,
            session_id=session_id,
            type=transaction_type,
            gross_amount_minor=gross_amount_minor,
            developer_amount_minor=developer_amount,
            platform_fee_minor=platform_fee,
            currency=currency,
            status=TransactionStatus.COMPLETED,
            idempotency_key=idempotency_key,
            external_ref=f"mock_{idempotency_key or 'auto'}",
        )
        db.add(tx)
        await db.flush()

        db.add(PlatformFee(
            transaction_id=tx.id,
            fee_rate_bps=settings.platform_fee_bps,
            platform_amount_minor=platform_fee,
            developer_amount_minor=developer_amount,
        ))

        return ChargeResult(transaction=tx, success=True)


billing_provider = MockBillingProvider()
