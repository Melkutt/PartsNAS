"""Quote/invoice customers (master list).

`GET/POST /api/customers`          list / add a customer
`PATCH/DELETE /api/customers/{id}` edit / remove (blocked while referenced by a quote)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
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


def _row(c: Customer) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "address": c.address,
        "org_number": c.org_number,
        "phone": c.phone,
        "email": c.email,
    }


@router.get("")
def list_customers(db: Session = Depends(get_db)):
    rows = db.scalars(select(Customer).order_by(Customer.name)).all()
    used = {
        cid for (cid,) in db.execute(
            select(Quote.customer_id).where(Quote.customer_id.is_not(None)).distinct()
        ).all()
    }
    return [{**_row(c), "in_use": c.id in used} for c in rows]


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
    n = db.scalar(select(func.count()).select_from(Quote).where(Quote.customer_id == cid))
    if n:
        raise HTTPException(409, f"customer is linked to {n} quote(s); unlink first")
    db.delete(c)
    db.commit()
    return {"ok": True}
