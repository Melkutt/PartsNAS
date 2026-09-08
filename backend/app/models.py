"""Database model.

Design notes
------------
* Category and StorageLocation are both self-referential trees of *arbitrary*
  depth (the spec's 3 levels are just the seed data, not a limit). The same UI
  tree widget and the same move/rename/delete endpoints serve both.
* Stock is an append-only ledger (`StockEntry`). Current quantity for a part in a
  location is SUM(delta) over its entries; total on-hand is SUM over all. This
  gives "saldo beräknas från transaktionstabellen" and a full move history for
  free. A bulk move writes one entry per part, all sharing a `move_group` id, so
  the whole operation can be reverted in one click.
* Per-class fields from the spec (resistance, Vds, ...) live in `Part.attributes`
  (JSON), keyed by the schema in seed/part_classes.json. Only the shared fields
  are real columns.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .core.db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _part_id() -> str:
    # 8 lowercase hex chars, PartsBox-ish short id used in URLs and the KiCad lib
    return secrets.token_hex(4)


class Category(Base):
    __tablename__ = "category"

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("category.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(160), index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    # optional link to a part-class schema (seed/part_classes.json id); children
    # inherit the nearest ancestor's value when their own is null
    part_class: Mapped[str | None] = mapped_column(String(40))
    kicad_symbol: Mapped[str | None] = mapped_column(String(120))
    comment: Mapped[str | None] = mapped_column(Text)
    is_unsorted: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    parent: Mapped["Category | None"] = relationship(remote_side=[id], back_populates="children")
    children: Mapped[list["Category"]] = relationship(
        back_populates="parent", order_by="Category.sort_order, Category.name"
    )
    parts: Mapped[list["Part"]] = relationship(back_populates="category")

    __table_args__ = (UniqueConstraint("parent_id", "name", name="uq_category_sibling"),)


class StorageLocation(Base):
    __tablename__ = "storage_location"

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("storage_location.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(120))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str | None] = mapped_column(Text)
    legacy_id: Mapped[str | None] = mapped_column(String(40), index=True)  # PartsBox export id
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    parent: Mapped["StorageLocation | None"] = relationship(
        remote_side=[id], back_populates="children"
    )
    children: Mapped[list["StorageLocation"]] = relationship(
        back_populates="parent", order_by="StorageLocation.sort_order, StorageLocation.name"
    )

    __table_args__ = (UniqueConstraint("parent_id", "name", name="uq_location_sibling"),)


class FootprintAlias(Base):
    __tablename__ = "footprint_alias"

    id: Mapped[int] = mapped_column(primary_key=True)
    canonical: Mapped[str] = mapped_column(String(80), unique=True)
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    group: Mapped[str | None] = mapped_column(String(40))
    kicad_footprint: Mapped[str | None] = mapped_column(String(160))


class Part(Base):
    __tablename__ = "part"

    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=_part_id)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("category.id", ondelete="SET NULL"))

    # identity
    mpn: Mapped[str | None] = mapped_column(String(120), index=True)
    manufacturer: Mapped[str | None] = mapped_column(String(120))
    name: Mapped[str] = mapped_column(String(200))  # display name / Value
    description: Mapped[str | None] = mapped_column(Text)

    # classification
    mount: Mapped[str | None] = mapped_column(String(8))  # smd | tht | other
    footprint_raw: Mapped[str | None] = mapped_column(String(120))
    footprint_id: Mapped[int | None] = mapped_column(
        ForeignKey("footprint_alias.id", ondelete="SET NULL")
    )
    kicad_symbol: Mapped[str | None] = mapped_column(String(120))
    kicad_footprint: Mapped[str | None] = mapped_column(String(160))
    datasheet_url: Mapped[str | None] = mapped_column(String(500))
    image_path: Mapped[str | None] = mapped_column(String(300))

    # stock helpers (ledger is the source of truth; this is just a warning level)
    min_stock: Mapped[int] = mapped_column(Integer, default=0)

    # free-form
    notes: Mapped[str | None] = mapped_column(Text)
    octopart_id: Mapped[str | None] = mapped_column(String(60))

    attributes: Mapped[dict] = mapped_column(JSON, default=dict)  # per-class fields
    price_cache: Mapped[dict] = mapped_column(JSON, default=dict)  # {mouser:{price,ts},...}

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    category: Mapped["Category | None"] = relationship(back_populates="parts")
    footprint: Mapped["FootprintAlias | None"] = relationship()
    stock_entries: Mapped[list["StockEntry"]] = relationship(
        back_populates="part", cascade="all, delete-orphan"
    )
    tags: Mapped[list["Tag"]] = relationship(secondary="part_tag", back_populates="parts")


class Tag(Base):
    __tablename__ = "tag"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60), unique=True)

    parts: Mapped[list["Part"]] = relationship(secondary="part_tag", back_populates="tags")


class PartTag(Base):
    __tablename__ = "part_tag"

    part_id: Mapped[str] = mapped_column(
        ForeignKey("part.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(ForeignKey("tag.id", ondelete="CASCADE"), primary_key=True)


class StockEntry(Base):
    __tablename__ = "stock_entry"

    id: Mapped[int] = mapped_column(primary_key=True)
    part_id: Mapped[str] = mapped_column(ForeignKey("part.id", ondelete="CASCADE"), index=True)
    location_id: Mapped[int | None] = mapped_column(
        ForeignKey("storage_location.id", ondelete="SET NULL"), index=True
    )
    delta: Mapped[int] = mapped_column(Integer)  # +in / -out
    kind: Mapped[str] = mapped_column(String(12))  # add|remove|move|count|correction|build
    unit_price: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(3), default="SEK")
    supplier: Mapped[str | None] = mapped_column(String(80))
    order_ref: Mapped[str | None] = mapped_column(String(120))
    note: Mapped[str | None] = mapped_column(Text)
    move_group: Mapped[str | None] = mapped_column(String(20), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    part: Mapped["Part"] = relationship(back_populates="stock_entries")
    location: Mapped["StorageLocation | None"] = relationship()

    __table_args__ = (
        CheckConstraint(
            "kind in ('add','remove','move','count','correction','build')", name="ck_stock_kind"
        ),
    )


class Project(Base):
    __tablename__ = "project"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    bom_lines: Mapped[list["BomLine"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    builds: Mapped[list["Build"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class BomLine(Base):
    __tablename__ = "bom_line"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"), index=True)
    part_id: Mapped[str | None] = mapped_column(ForeignKey("part.id", ondelete="SET NULL"))
    unresolved_mpn: Mapped[str | None] = mapped_column(String(120))  # set when part_id is null
    qty_per_board: Mapped[float] = mapped_column(Float, default=1)
    refdes: Mapped[str | None] = mapped_column(Text)  # "R1 R2 R7"
    note: Mapped[str | None] = mapped_column(Text)

    project: Mapped["Project"] = relationship(back_populates="bom_lines")
    part: Mapped["Part | None"] = relationship()


class Build(Base):
    __tablename__ = "build"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"), index=True)
    qty_boards: Mapped[int] = mapped_column(Integer, default=1)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    project: Mapped["Project"] = relationship(back_populates="builds")


class BulkOp(Base):
    """Audit + one-click undo for bulk edits (category moves, tag adds, ...).

    `undo` holds whatever the revert endpoint needs, e.g.
    {"field": "category_id", "before": {"<part_id>": 4, ...}}.
    """

    __tablename__ = "bulk_op"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(30))
    summary: Mapped[str] = mapped_column(Text)
    undo: Mapped[dict] = mapped_column(JSON, default=dict)
    undone: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Setting(Base):
    __tablename__ = "setting"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)
