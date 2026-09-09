"""Provider contract + the normalized result shape the UI consumes."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from sqlalchemy.orm import Session


class ProviderError(RuntimeError):
    """Any provider-side failure the UI should show verbatim."""


class ProviderBlocked(ProviderError):
    """The circuit breaker is open (rate-limit / block / quota). Carries when it lifts."""

    def __init__(self, message: str, retry_after_s: int | None = None):
        super().__init__(message)
        self.retry_after_s = retry_after_s


@dataclass
class PriceBreak:
    qty: int
    ex_vat: float
    currency: str


@dataclass
class ProviderResult:
    provider: str
    mpn: str
    manufacturer: str | None = None
    description: str | None = None
    datasheet_url: str | None = None
    image_url: str | None = None
    product_url: str | None = None
    sku: str | None = None  # the provider's own article number
    category_hint: str | None = None
    lifecycle: str | None = None
    in_stock: int | None = None
    # attribute label -> value, as the provider names them
    attributes: dict[str, str] = field(default_factory=dict)
    price_breaks: list[PriceBreak] = field(default_factory=list)

    def unit_price(self) -> PriceBreak | None:
        return min(self.price_breaks, key=lambda b: b.qty) if self.price_breaks else None

    def to_dict(self) -> dict:
        up = self.unit_price()
        return {
            "provider": self.provider,
            "mpn": self.mpn,
            "manufacturer": self.manufacturer,
            "description": self.description,
            "datasheet_url": self.datasheet_url,
            "image_url": self.image_url,
            "product_url": self.product_url,
            "sku": self.sku,
            "category_hint": self.category_hint,
            "lifecycle": self.lifecycle,
            "in_stock": self.in_stock,
            "attributes": self.attributes,
            "price_breaks": [b.__dict__ for b in self.price_breaks],
            "unit_price": up.__dict__ if up else None,
        }


class Provider(ABC):
    name: str
    label: str
    website: str
    cred_fields: list[str] = ["api_key"]  # e.g. ["client_id", "client_secret"]

    @abstractmethod
    def configured(self, db: Session) -> bool:
        """True when all credentials are available (env vars or Setting)."""

    @abstractmethod
    def search(self, db: Session, mpn: str) -> list[ProviderResult]:
        """Look up one manufacturer part number. Uses the disk cache first."""
