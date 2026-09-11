from collections.abc import Iterator

from fastapi import Request
from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy.orm import Session

metadata = MetaData()

menu_items = Table(
    "menu_items",
    metadata,
    Column("id", String, primary_key=True),
    Column("name", String, nullable=False),
)
ingredients = Table(
    "ingredients",
    metadata,
    Column("id", String, primary_key=True),
    Column("name", String, nullable=False),
    Column("unit", String, nullable=False),
    CheckConstraint("unit IN ('kg', 'litres', 'pieces')"),
)
recipes = Table(
    "recipes",
    metadata,
    Column("menu_item_id", ForeignKey("menu_items.id"), primary_key=True),
    Column("ingredient_id", ForeignKey("ingredients.id"), primary_key=True),
    Column("quantity", Numeric(12, 3), nullable=False),
    CheckConstraint("quantity > 0"),
)
suppliers = Table(
    "suppliers",
    metadata,
    Column("id", String, primary_key=True),
    Column("name", String, nullable=False),
)
supplier_offers = Table(
    "supplier_offers",
    metadata,
    Column("id", String, primary_key=True),
    Column("supplier_id", ForeignKey("suppliers.id"), nullable=False),
    Column("ingredient_id", ForeignKey("ingredients.id"), nullable=False),
    Column("unit_price", Numeric(12, 2)),
    Column("available_quantity", Numeric(12, 3)),
    Column("moq", Numeric(12, 3)),
    Column("pack_size", Numeric(12, 3)),
    Column("lead_time_minutes", Integer),
    Column("order_cutoff", JSON, nullable=False),
    Column("feasible_delivery_at", JSON),
    Column("current_status", String, nullable=False),
    Column("recent_on_time_rate", Numeric(5, 4)),
    Column("shelf_life_days_on_arrival", Integer),
    Column("delivery_fee_sgd", Numeric(12, 2)),
    Column("emergency_fee_sgd", Numeric(12, 2)),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("supplier_id", "ingredient_id"),
    CheckConstraint("current_status IN ('AVAILABLE', 'UNAVAILABLE', 'UNKNOWN')"),
    CheckConstraint(
        "unit_price >= 0 AND available_quantity >= 0 AND moq >= 0 AND pack_size > 0"
    ),
    CheckConstraint("lead_time_minutes >= 0 AND shelf_life_days_on_arrival >= 0"),
    CheckConstraint("recent_on_time_rate BETWEEN 0 AND 1"),
    CheckConstraint("delivery_fee_sgd >= 0 AND emergency_fee_sgd >= 0"),
)
holidays = Table(
    "holidays",
    metadata,
    Column("date", Date, primary_key=True),
    Column("name", String, nullable=False),
    Column("source_url", String, nullable=False),
)
inventory_lots = Table(
    "inventory_lots",
    metadata,
    Column("id", String, primary_key=True),
    Column("ingredient_id", ForeignKey("ingredients.id"), nullable=False),
    Column("received_at", DateTime(timezone=True), nullable=False),
    Column("expiry_date", Date, nullable=False),
    Column("initial_quantity", Numeric(12, 3), nullable=False),
    CheckConstraint("initial_quantity >= 0"),
)
stock_counts = Table(
    "stock_counts",
    metadata,
    Column("id", String, primary_key=True),
    Column("lot_id", ForeignKey("inventory_lots.id"), nullable=False),
    Column("quantity", Numeric(12, 3), nullable=False),
    Column("counted_at", DateTime(timezone=True), nullable=False),
    Column("sequence", Integer, nullable=False, server_default="0"),
    UniqueConstraint("lot_id", "counted_at", "sequence"),
    CheckConstraint("quantity >= 0"),
)
manager_sessions = Table(
    "manager_sessions",
    metadata,
    Column("token_hash", String(64), primary_key=True),
    Column("username", String, nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
)

daily_drafts = Table(
    "daily_drafts",
    metadata,
    Column("day", Date, primary_key=True),
    Column("payload", JSON, nullable=False),
)
daily_revisions = Table(
    "daily_revisions",
    metadata,
    Column("id", String, primary_key=True),
    Column("day", Date, nullable=False),
    Column("revision", Integer, nullable=False),
    Column("cutoff", DateTime(timezone=True), nullable=False),
    Column("recorded_at", DateTime(timezone=True), nullable=False),
    Column("actor", String, nullable=False),
    Column("payload", JSON, nullable=False),
    UniqueConstraint("day", "revision"),
)
events = Table(
    "events",
    metadata,
    Column("id", String, primary_key=True),
    Column("type", String, nullable=False),
    Column("timestamp", DateTime(timezone=True), nullable=False),
    Column("source", String, nullable=False),
    Column("payload", JSON, nullable=False),
)
audit_entries = Table(
    "audit_entries",
    metadata,
    Column("id", String, primary_key=True),
    Column("event_id", ForeignKey("events.id"), nullable=False),
    Column("actor", String, nullable=False),
    Column("action", String, nullable=False),
    Column("timestamp", DateTime(timezone=True), nullable=False),
)


deliveries = Table(
    "deliveries",
    metadata,
    Column("id", String, primary_key=True),
    Column("supplier_id", ForeignKey("suppliers.id"), nullable=False),
    Column("ingredient_id", ForeignKey("ingredients.id"), nullable=False),
    Column("kind", String, nullable=False),
    Column("expected_quantity", Numeric(12, 3), nullable=False),
    Column("cancelled_quantity", Numeric(12, 3), nullable=False, server_default="0"),
    Column("expected_at", DateTime(timezone=True), nullable=False),
    Column("ordered_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("expected_quantity > 0 AND cancelled_quantity >= 0"),
    CheckConstraint("kind IN ('NORMAL', 'EMERGENCY')"),
)
delivery_receipts = Table(
    "delivery_receipts",
    metadata,
    Column("id", String, primary_key=True),
    Column("delivery_id", ForeignKey("deliveries.id"), nullable=False),
    Column("lot_id", ForeignKey("inventory_lots.id"), nullable=False, unique=True),
    Column("request_id", String, nullable=False),
    Column("quantity", Numeric(12, 3), nullable=False),
    Column("received_at", DateTime(timezone=True), nullable=False),
    Column("expiry_date", Date, nullable=False),
    Column("remainder", String, nullable=False),
    Column("closing_counts", JSON, nullable=False),
    UniqueConstraint("delivery_id", "request_id"),
    CheckConstraint("quantity > 0"),
    CheckConstraint("remainder IN ('EXPECTED', 'CANCELLED')"),
)


def get_session(request: Request) -> Iterator[Session]:
    with Session(request.app.state.engine) as session:
        yield session
