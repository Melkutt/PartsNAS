"""Quote/invoice customers (master list).

`GET  /api/customers?archived=false|true|all`  list (default: active only)
`POST /api/customers`                           add
`PATCH /api/customers/{id}`                     edit, incl. {archived: true|false}
`DELETE /api/customers/{id}`                    erase — refused only while a LOCKED invoice
                                                still points at the customer (that is kept
                                                history); anything else is detached first

Archiving hides a customer from the list and the quote picker without touching
any document; it's the "keep it, but out of the way" option.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..models import Customer, Quote

router = APIRouter(prefix="/api/customers", tags=["customers"])


class CustomerIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    address: str | None = None
    org_number: str | None = None
    phone: str | None = None
    email: str | None = None


class CustomerPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    address: str | None = None
    org_number: str | None = None
    phone: str | None = None
    email: str | None = None
    archived: bool | None = None


def _row(c: Customer) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "address": c.address,
        "org_number": c.org_number,
        "phone": c.phone,
        "email": c.email,
        "archived": c.archived,
    }


def _kept_history(cid: int):
    """Locked, invoiced, not-trashed = finished invoices that must stay intact."""
    return (Quote.customer_id == cid, Quote.status == "invoiced",
            Quote.locked.is_(True), Quote.deleted_at.is_(None))


@router.get("")
def list_customers(archived: str = "false", db: Session = Depends(get_db)):
    stmt = select(Customer).order_by(Customer.name)
    if archived == "true":
        stmt = stmt.where(Customer.archived.is_(True))
    elif archived != "all":
        stmt = stmt.where(Customer.archived.is_(False))
    rows = db.scalars(stmt).all()
    linked = dict(db.execute(
        select(Quote.customer_id, func.count()).where(
            Quote.customer_id.is_not(None), Quote.deleted_at.is_(None)).group_by(Quote.customer_id)).all())
    kept = dict(db.execute(
        select(Quote.customer_id, func.count()).where(
            Quote.customer_id.is_not(None), Quote.status == "invoiced",
            Quote.locked.is_(True), Quote.deleted_at.is_(None)).group_by(Quote.customer_id)).all())
    return [{**_row(c), "quotes": linked.get(c.id, 0), "locked_invoices": kept.get(c.id, 0)} for c in rows]


@router.post("", status_code=201)
def add_customer(body: CustomerIn, db: Session = Depends(get_db)):
    c = Customer(name=body.name, address=body.address, org_number=body.org_number,
                 phone=body.phone, email=body.email)
    db.add(c)
    db.commit()
    return _row(c)


@router.patch("/{cid}")
def patch_customer(cid: int, body: CustomerPatch, db: Session = Depends(get_db)):
    c = db.get(Customer, cid)
    if c is None:
        raise HTTPException(404, "customer not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(c, k, v)
    db.commit()
    return {"ok": True}


@router.delete("/{cid}")
def delete_customer(cid: int, db: Session = Depends(get_db)):
    c = db.get(Customer, cid)
    if c is None:
        raise HTTPException(404, "customer not found")
    n = db.scalar(select(func.count()).select_from(Quote).where(*_kept_history(cid)))
    if n:
        raise HTTPException(409, f"{n} locked invoice(s) still belong to this customer — "
                                 "they're kept history. Archive the customer instead.")
    # everything else (open quotes, unlocked invoices, trashed ones) is detached:
    # the address/phone/email stop appearing on them; the name typed on the
    # document stays, since that's the document's own text
    db.execute(update(Quote).where(Quote.customer_id == cid).values(customer_id=None))
    db.delete(c)
    db.commit()
    return {"ok": True}
