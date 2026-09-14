"""Exercise data-preserving upgrade from the audited main schema, not just fresh DDL."""

import os
import subprocess
import sys
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError


def test_upgrade_preserves_legacy_facts_and_resolves_overlapping_plans(
    database_url: str,
) -> None:
    env = {**os.environ, "DATABASE_URL": database_url}
    subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "20260912_reconciliation"],
        env=env,
        check=True,
    )
    engine = create_engine(database_url)
    try:
        with engine.begin() as conn:
            conn.execute(
                text("""
                INSERT INTO planning_runs (id,status,trigger,as_of,input_revision,snapshot,created_at)
                VALUES ('legacy-run','SUCCEEDED','MANUAL_REASSESSMENT_REQUESTED',now(),0,'{}',now())
            """)
            )
            for number, status in ((1, "APPROVED"), (2, "PENDING_APPROVAL")):
                conn.execute(
                    text(
                        "INSERT INTO purchase_plans (id,created_at) VALUES (:id,now())"
                    ),
                    {"id": f"plan-{number}"},
                )
                conn.execute(
                    text("""
                    INSERT INTO plan_versions (id,plan_id,version,run_id,status,snapshot,costs,created_at)
                    VALUES (:id,:plan_id,1,'legacy-run',:status,'{}','{}',:created_at)
                """),
                    {
                        "id": f"version-{number}",
                        "plan_id": f"plan-{number}",
                        "status": status,
                        "created_at": datetime(2026, 9, 12, number, tzinfo=UTC),
                    },
                )
            conn.execute(
                text("""
                INSERT INTO purchase_plan_lines (id,plan_version_id,ingredient_id,supplier_id,quantity,unit_price,arrival_at)
                VALUES ('legacy-line','version-1','chicken','fresh',10,4.5,now())
            """)
            )
            conn.execute(
                text("""
                INSERT INTO deliveries (id,source_plan_line_id,supplier_id,ingredient_id,kind,expected_quantity,expected_at,ordered_at)
                VALUES ('legacy-delivery','legacy-line','fresh','chicken','NORMAL',2,now(),now())
            """)
            )
            conn.execute(
                text(
                    "UPDATE supplier_offers SET unit_price=123 WHERE id='fresh-chicken'"
                )
            )
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"], env=env, check=True
        )
        # Re-seeding cannot silently replace the pre-existing offer or its baseline history.
        subprocess.run([sys.executable, "-m", "src.seed"], env=env, check=True)
        with engine.connect() as conn:
            assert (
                conn.execute(
                    text("SELECT status FROM plan_versions WHERE id='version-1'")
                ).scalar_one()
                == "SUPERSEDED"
            )
            assert (
                conn.execute(
                    text("SELECT status FROM plan_versions WHERE id='version-2'")
                ).scalar_one()
                == "PENDING_APPROVAL"
            )
            event = conn.execute(
                text("SELECT payload FROM events WHERE type='PLAN_SUPERSEDED'")
            ).scalar_one()
            assert event["previous_status"] == "APPROVED"
            assert event["replacement_version_id"] == "version-2"
            assert (
                conn.execute(
                    text(
                        "SELECT count(*) FROM audit_entries WHERE action='PLAN_SUPERSEDED'"
                    )
                ).scalar_one()
                == 1
            )
            assert (
                conn.execute(
                    text(
                        "SELECT source_validation FROM deliveries WHERE id='legacy-delivery'"
                    )
                ).scalar_one()
                == "LEGACY_REFERENCE"
            )
            assert (
                conn.execute(
                    text(
                        "SELECT expected_quantity FROM deliveries WHERE id='legacy-delivery'"
                    )
                ).scalar_one()
                == 2
            )
            offer = conn.execute(
                text(
                    "SELECT payload FROM supplier_offer_versions WHERE offer_id='fresh-chicken'"
                )
            ).scalar_one()
            assert float(offer["unit_price"]) == 123
            assert (
                conn.execute(
                    text(
                        "SELECT count(*) FROM stock_counts WHERE recorded_at IS NOT NULL"
                    )
                ).scalar_one()
                == 9
            )
        with pytest.raises(IntegrityError), engine.begin() as conn:
            conn.execute(
                text("UPDATE plan_versions SET status='APPROVED' WHERE id='version-1'")
            )
        with pytest.raises(IntegrityError), engine.begin() as conn:
            conn.execute(text("UPDATE ingredients SET interval_days=0 WHERE id='rice'"))
    finally:
        engine.dispose()
