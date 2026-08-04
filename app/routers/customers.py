from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, Request

from app.audit import record_audit
from app.crud import customer_files as files_crud
from app.crud import customers as crud
from app.storage import delete_file as remove_from_disk
from app.db import get_cursor
from app.schemas import Customer, CustomerCreate, CustomerUpdate, User
from app.security import require_permission

router = APIRouter(prefix="/customers", tags=["customers"])


def _snapshot(customer: Customer) -> dict:
    return customer.model_dump(mode="json")


@router.post("", response_model=Customer, status_code=201)
def create_customer(
    payload: CustomerCreate,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("customers:create")),
):
    customer = crud.create_customer(cursor, payload)
    background.add_task(
        record_audit,
        action="CREATE",
        entity_type="customer",
        entity_id=customer.id,
        old_values=None,
        new_values=_snapshot(customer),
        request_id=request.headers.get("X-Request-ID"),
    )
    return customer


@router.get("", response_model=List[Customer])
def list_customers(
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("customers:read")),
):
    return crud.list_customers(cursor)


@router.get("/{customer_id}", response_model=Customer)
def get_customer(
    customer_id: str,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("customers:read")),
):
    return crud.get_customer_or_404(cursor, customer_id)


@router.put("/{customer_id}", response_model=Customer)
def update_customer(
    customer_id: str,
    payload: CustomerUpdate,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("customers:update")),
):
    before = crud.get_customer_or_404(cursor, customer_id)
    after = crud.update_customer(cursor, customer_id, payload)
    background.add_task(
        record_audit,
        action="UPDATE",
        entity_type="customer",
        entity_id=customer_id,
        old_values=_snapshot(before),
        new_values=_snapshot(after),
        request_id=request.headers.get("X-Request-ID"),
    )
    return after


@router.delete("/{customer_id}", status_code=204)
def delete_customer(
    customer_id: str,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("customers:delete")),
):
    # Remove the customer's documents first, so deleting a customer never
    # leaves rows pointing at a customer that no longer exists.
    orphaned = files_crud.delete_files_for_customer(cursor, customer_id)

    deleted = crud.delete_customer(cursor, customer_id)

    for record in orphaned:
        remove_from_disk(record.file_path)
        if record.deidentified_file_path:
            remove_from_disk(record.deidentified_file_path)

    background.add_task(
        record_audit,
        action="DELETE",
        entity_type="customer",
        entity_id=customer_id,
        old_values=_snapshot(deleted),
        new_values=None,
        request_id=request.headers.get("X-Request-ID"),
    )
