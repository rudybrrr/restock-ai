from collections.abc import Iterator

from fastapi import Request
from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Session

metadata = MetaData()

supplier_offer_versions = Table(
    "supplier_offer_versions",
    metadata,
    Column("id", String, primary_key=True),
    Column("offer_id", ForeignKey("supplier_offers.id"), nullable=False),
    Column("effective_at", DateTime(timezone=True), nullable=False),
    Column("recorded_at", DateTime(timezone=True), nullable=False),
    Column("payload", JSON, nullable=False),
)

procurement_policy_versions = Table(
    "procurement_policy_versions",
    metadata,
    Column("id", String, primary_key=True),
    Column("policy_id", String, nullable=False),
    Column("version", Integer, nullable=False),
    Column("effective_at", DateTime(timezone=True), nullable=False),
    Column("recorded_at", DateTime(timezone=True), nullable=False),
    Column("payload", JSON, nullable=False),
    UniqueConstraint("policy_id", "version"),
)

procurement_policy_domains = Table(
    "procurement_policy_domains",
    metadata,
    Column("id", String, primary_key=True),
    Column(
        "policy_version_id",
        ForeignKey("procurement_policy_versions.id"),
        nullable=False,
    ),
    Column("domain_id", String, nullable=False),
    Column("version", Integer, nullable=False),
    Column("source_revision", String, nullable=False),
    Column("recorded_at", DateTime(timezone=True), nullable=False),
    Column("payload", JSON, nullable=False),
    UniqueConstraint("domain_id", "version"),
)

procurement_domain_offer_revisions = Table(
    "procurement_domain_offer_revisions",
    metadata,
    Column("id", String, primary_key=True),
    Column(
        "domain_version_id", ForeignKey("procurement_policy_domains.id"), nullable=False
    ),
    Column("offer_id", String, nullable=False),
    Column("supplier_id", String, nullable=False),
    Column("ingredient_id", String, nullable=False),
    Column("source_revision", String, nullable=False),
    Column("payload", JSON, nullable=False),
    UniqueConstraint("domain_version_id", "offer_id"),
    UniqueConstraint("domain_version_id", "source_revision"),
)

procurement_domain_opportunities = Table(
    "procurement_domain_opportunities",
    metadata,
    Column("id", String, primary_key=True),
    Column(
        "domain_version_id", ForeignKey("procurement_policy_domains.id"), nullable=False
    ),
    Column("opportunity_id", String, nullable=False),
    Column("offer_id", String, nullable=False),
    Column("ordered_at", DateTime(timezone=True), nullable=False),
    Column("arrival_at", DateTime(timezone=True), nullable=False),
    Column("kind", String, nullable=False),
    Column("expiry_date", Date, nullable=False),
    Column("source_revision", String, nullable=False),
    UniqueConstraint("domain_version_id", "opportunity_id"),
    CheckConstraint("kind IN ('NORMAL', 'EMERGENCY')"),
)

promotions = Table(
    "promotions",
    metadata,
    Column("id", String, primary_key=True),
    Column("revision", Integer, nullable=False),
    Column("payload", JSON, nullable=False),
    CheckConstraint("revision > 0"),
)

order_cycles = Table(
    "order_cycles",
    metadata,
    Column("ingredient_id", ForeignKey("ingredients.id"), primary_key=True),
    Column("scheduled_date", Date, primary_key=True),
    Column("status", String, nullable=False),
    Column("decided_at", DateTime(timezone=True), nullable=False),
    Column("effective_at", DateTime(timezone=True), nullable=False),
    Column("actor", String, nullable=False),
    Column("note", String),
    CheckConstraint("status IN ('ORDERED', 'SKIPPED')"),
)

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
    Column("interval_days", Integer, nullable=False, server_default="1"),
    Column("starting_date", Date, nullable=False, server_default="2026-02-15"),
    CheckConstraint("interval_days > 0", name="ingredients_positive_interval"),
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
    Column("status", String, nullable=False, server_default="ACTIVE"),
    CheckConstraint("initial_quantity >= 0"),
)
stock_counts = Table(
    "stock_counts",
    metadata,
    Column("id", String, primary_key=True),
    Column("lot_id", ForeignKey("inventory_lots.id"), nullable=False),
    Column("quantity", Numeric(12, 3), nullable=False),
    Column("counted_at", DateTime(timezone=True), nullable=False),
    Column(
        "recorded_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.clock_timestamp(),
    ),
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
    Column("reconciliation", JSON),
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
sales_batches = Table(
    "sales_batches",
    metadata,
    Column("id", String, primary_key=True),
    Column("source", String, nullable=False),
    Column("batch_id", String, nullable=False),
    Column("revision", Integer, nullable=False),
    Column(
        "recorded_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.clock_timestamp(),
    ),
    Column("period_start", DateTime(timezone=True), nullable=False),
    Column("period_end", DateTime(timezone=True), nullable=False),
    Column("sales", JSON, nullable=False),
    Column("replaces_id", ForeignKey("sales_batches.id")),
    Column("active", Integer, nullable=False, server_default="1"),
    UniqueConstraint("source", "batch_id", "revision"),
    CheckConstraint("period_end > period_start"),
)
planning_runs = Table(
    "planning_runs",
    metadata,
    Column("id", String, primary_key=True),
    Column("status", String, nullable=False),
    Column("trigger", String, nullable=False),
    Column("trigger_event_id", ForeignKey("events.id")),
    Column("as_of", DateTime(timezone=True), nullable=False),
    Column("input_revision", Integer, nullable=False),
    Column("snapshot", JSON, nullable=False),
    Column("outcome", String),
    Column("escalation_reason", String),
    Column("failure_reason", String),
    Column("plan_version_id", String),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("claimed_at", DateTime(timezone=True)),
    Column("deadline_at", DateTime(timezone=True)),
    Column("completed_at", DateTime(timezone=True)),
    Index(
        "one_active_planning_run",
        "status",
        unique=True,
        postgresql_where=text("status IN ('QUEUED', 'RUNNING')"),
    ),
)
assessment_requests = Table(
    "assessment_requests",
    metadata,
    Column("event_id", ForeignKey("events.id"), primary_key=True),
    Column("run_id", ForeignKey("planning_runs.id"), nullable=False),
    Column("effective_at", DateTime(timezone=True), nullable=False),
)

purchase_plans = Table(
    "purchase_plans",
    metadata,
    Column("id", String, primary_key=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
plan_versions = Table(
    "plan_versions",
    metadata,
    Column("id", String, primary_key=True),
    Column("plan_id", ForeignKey("purchase_plans.id"), nullable=False),
    Column("version", Integer, nullable=False),
    Column("run_id", ForeignKey("planning_runs.id"), nullable=False),
    Column("status", String, nullable=False),
    Column("snapshot", JSON, nullable=False),
    Column("costs", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("plan_id", "version"),
)
Index(
    "one_actionable_plan",
    text("(status IN ('PENDING_APPROVAL', 'APPROVED'))"),
    unique=True,
    postgresql_where=text("status IN ('PENDING_APPROVAL', 'APPROVED')"),
)

purchase_plan_lines = Table(
    "purchase_plan_lines",
    metadata,
    Column("id", String, primary_key=True),
    Column("plan_version_id", ForeignKey("plan_versions.id"), nullable=False),
    Column("ingredient_id", ForeignKey("ingredients.id"), nullable=False),
    Column("supplier_id", ForeignKey("suppliers.id"), nullable=False),
    Column("quantity", Numeric(12, 3), nullable=False),
    Column("unit_price", Numeric(12, 2), nullable=False),
    Column("arrival_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("quantity > 0 AND unit_price >= 0"),
)
audit_entries = Table(
    "audit_entries",
    metadata,
    Column("id", String, primary_key=True),
    Column("event_id", ForeignKey("events.id"), nullable=False),
    Column("actor", String, nullable=False),
    Column("action", String, nullable=False),
    Column("timestamp", DateTime(timezone=True), nullable=False),
    Column("payload", JSON),
)


deliveries = Table(
    "deliveries",
    metadata,
    Column("id", String, primary_key=True),
    Column("source_plan_line_id", ForeignKey("purchase_plan_lines.id")),
    Column("source_validation", String, nullable=False, server_default="MANUAL"),
    Column("cycle_date", Date),
    Column("supplier_id", ForeignKey("suppliers.id"), nullable=False),
    Column("ingredient_id", ForeignKey("ingredients.id"), nullable=False),
    Column("kind", String, nullable=False),
    Column("expected_quantity", Numeric(12, 3), nullable=False),
    Column("cancelled_quantity", Numeric(12, 3), nullable=False, server_default="0"),
    Column("expected_at", DateTime(timezone=True), nullable=False),
    Column("ordered_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "source_validation IN ('MANUAL', 'APPROVED_ALLOCATION', 'LEGACY_REFERENCE')",
        name="delivery_source_validation",
    ),
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
    Column(
        "recorded_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.clock_timestamp(),
    ),
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
