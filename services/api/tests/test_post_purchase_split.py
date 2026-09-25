"""Reviewable #10 split-supplier input changes with independent exact oracle."""

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from test_contingency import p  # noqa: F401 - canonical numerical input fixture

from src.contingency import search_contingency, validate_contingency


def test_changed_supplier_facts_force_feasible_split(p):  # noqa: F811 - pytest fixture
    fixture = json.loads(
        (Path(__file__).parent / "fixtures/post_purchase_split_v1.json").read_text()
    )
    offers, opportunities, groups = [], [], {}
    for row in fixture["changed_offers"]:
        terms = {
            key: Decimal(row[key])
            for key in (
                "available_quantity",
                "unit_price",
                "moq",
                "pack_size",
                "delivery_fee_sgd",
                "emergency_fee_sgd",
            )
        }
        offers.append(
            p.offers[0].model_copy(
                update={
                    **terms,
                    "id": row["offer_id"],
                    "supplier_id": row["supplier_id"],
                }
            )
        )
        op = replace(
            p.opportunities[0], id=row["opportunity_id"], offer_id=row["offer_id"]
        )
        opportunities.append(op)
        groups[op.id] = row["shipment_group_id"]
    changed = replace(
        p,
        offers=offers,
        opportunities=opportunities,
        approved_offer_manifest=[
            (o.id, o.supplier_id, o.ingredient_id) for o in offers
        ],
        opportunity_manifest=[o.id for o in opportunities],
        shipment_groups=groups,
        max_packs={o.id: 2 for o in opportunities},
        offer_evidence={o.id: p.evidence["domain"] for o in offers},
    )
    result = search_contingency(changed)
    assert result.status == "OPTIMAL_IN_DOMAIN" and result.search_complete
    assert (
        result.domain_size
        == result.evaluated
        == fixture["expected"]["domain_size"]
        == 9
    )
    assert result.candidate is not None
    validation = validate_contingency(changed, result.candidate)
    assert validation.complete and validation.feasible
    assert {x.supplier_id: x.quantity for x in validation.additions} == {
        "fresh": Decimal(2),
        "market": Decimal(2),
    }
    assert validation.cash is not None
    # Hand oracle: 4 kg * 2 + 2 distinct shipments * (3 + 4) = 22.
    assert (
        validation.cash.acquisition,
        validation.cash.delivery,
        validation.cash.emergency,
        validation.cash.total,
    ) == (8, 6, 8, 22)
    assert result.no_purchase and result.no_purchase.fixed_supply_ids == (
        p.inventory["supplies"][0].delivery.id,
    )
    assert fixture["expected"]["new_cash_sgd"] == str(validation.cash.total)
