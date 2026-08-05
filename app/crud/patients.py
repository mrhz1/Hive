"""Customer CRUD. Same shape as users minus username, plus
phone_number/address. Customers carry no role: roles govern API callers.
"""
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from app.db import execute
from app.errors import ConflictError, NotFoundError
from app.logging_setup import get_logger
from app.schemas import Customer, CustomerCreate, CustomerUpdate

log = get_logger(__name__)

_COLS = (
    "`id`, `email`, `first_name`, `last_name`, `phone_number`, "
    "`address`, `status`, `is_active`, `created_at`"
)


def _row_to_customer(row) -> Customer:
    return Customer(
        id=row[0],
        email=row[1],
        first_name=row[2],
        last_name=row[3],
        phone_number=row[4],
        address=row[5],
        status=row[6],
        is_active=bool(row[7]),
        created_at=row[8],
    )


def get_customer(cursor, customer_id: str) -> Optional[Customer]:
    execute(cursor, f"SELECT {_COLS} FROM `customers` WHERE `id` = %s", (customer_id,))
    row = cursor.fetchone()
    return _row_to_customer(row) if row else None


def get_customer_or_404(cursor, customer_id: str) -> Customer:
    customer = get_customer(cursor, customer_id)
    if customer is None:
        raise NotFoundError(f"Customer '{customer_id}' not found")
    return customer


def list_customers(cursor) -> List[Customer]:
    execute(cursor, f"SELECT {_COLS} FROM `customers`")
    return [_row_to_customer(r) for r in cursor.fetchall()]


def _find_by_email(cursor, email: str) -> Optional[str]:
    execute(cursor, "SELECT `id` FROM `customers` WHERE `email` = %s", (email,))
    row = cursor.fetchone()
    return row[0] if row else None


def _find_by_phone(cursor, phone_number: str) -> Optional[str]:
    execute(
        cursor,
        "SELECT `id` FROM `customers` WHERE `phone_number` = %s",
        (phone_number,),
    )
    row = cursor.fetchone()
    return row[0] if row else None


def create_customer(cursor, payload: CustomerCreate) -> Customer:
    # No UNIQUE constraints in Hive -- pre-check SELECTs, non-atomic.
    if _find_by_email(cursor, payload.email):
        raise ConflictError(f"Email '{payload.email}' already exists")
    if _find_by_phone(cursor, payload.phone_number):
        raise ConflictError(f"Phone number '{payload.phone_number}' already exists")

    customer_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).replace(tzinfo=None)
    execute(
        cursor,
        f"INSERT INTO `customers` ({_COLS}) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            customer_id,
            payload.email,
            payload.first_name,
            payload.last_name,
            payload.phone_number,
            payload.address,
            payload.status,
            payload.is_active,
            created_at.strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )
    log.info("customer_created", customer_id=customer_id, email=payload.email)
    return get_customer_or_404(cursor, customer_id)


def update_customer(cursor, customer_id: str, payload: CustomerUpdate) -> Customer:
    existing = get_customer_or_404(cursor, customer_id)

    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        return existing

    if "email" in fields and fields["email"] != existing.email:
        clash = _find_by_email(cursor, fields["email"])
        if clash and clash != customer_id:
            raise ConflictError(f"Email '{fields['email']}' already exists")
    if "phone_number" in fields and fields["phone_number"] != existing.phone_number:
        clash = _find_by_phone(cursor, fields["phone_number"])
        if clash and clash != customer_id:
            raise ConflictError(
                f"Phone number '{fields['phone_number']}' already exists"
            )

    set_clause = ", ".join(f"`{col}` = %s" for col in fields)
    params = tuple(fields.values()) + (customer_id,)
    execute(cursor, f"UPDATE `customers` SET {set_clause} WHERE `id` = %s", params)
    log.info("customer_updated", customer_id=customer_id, fields=sorted(fields))
    return get_customer_or_404(cursor, customer_id)


def delete_customer(cursor, customer_id: str) -> Customer:
    existing = get_customer_or_404(cursor, customer_id)
    execute(cursor, "DELETE FROM `customers` WHERE `id` = %s", (customer_id,))
    log.info("customer_deleted", customer_id=customer_id)
    return existing
