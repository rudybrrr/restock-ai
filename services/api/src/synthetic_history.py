"""Reproducible, fully supplied DEVELOPMENT history; never a database seed.

Run ``python -m src.synthetic_history --help`` from services/api. Parameters and
latent attempted demand are written only to the separately supplied evaluator
directory. No inventory simulation, forecasting model or API adapter is implied.
"""

import argparse
import csv
import json
from datetime import date, datetime, time, timedelta
from decimal import Context, Decimal, localcontext
from fractions import Fraction
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from src.forecasting import SINGAPORE
from src.history_dataset import (
    NUMBERS,
    PROMOTION_FIELDS,
    PUBLIC_FILES,
    SALES_FIELDS,
    SCHEMA_VERSION,
    Catalogue,
    DatasetModel,
    ObservationManifest,
    Partition,
    aware,
    canonical_json,
    flag,
    integer,
    money,
    partition_for,
    read_csv,
    sha256,
    validate_observations,
    validate_partitions,
)
from src.requirements import calculate_requirements
from src.service_buckets import ServicePeriod, allocate_service_buckets

GENERATOR_VERSION = "fully-supplied-history/1"
TRUTH_FIELDS = (
    "id",
    "service_date",
    "dish_id",
    "attempted_transactions",
    "attempted_portions",
    "served",
    "unmet",
    "partition",
)
USAGE_FIELDS = ("service_date", "ingredient_id", "unit", "quantity")
PRIVATE_FILES = ("configuration.json", "attempted_demand.csv", "ingredient_usage.csv")


class Seeds(DatasetModel):
    demand: int = Field(strict=True, ge=0)
    event_timing: int = Field(strict=True, ge=0)
    observation_error: int = Field(strict=True, ge=0)


class DishAssumption(DatasetModel):
    dish_id: str
    base_transactions: Decimal = Field(
        ge=0, le=10000, allow_inf_nan=False, max_digits=12, decimal_places=4
    )
    unit_price_sgd: Decimal = Field(
        ge=0, le=10000, allow_inf_nan=False, max_digits=12, decimal_places=2
    )


class ProfileAssumption(DatasetModel):
    start: time
    end: time
    weight: Decimal = Field(ge=0, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def local_clock(self) -> "ProfileAssumption":
        if self.start.tzinfo is not None or self.end.tzinfo is not None:
            raise ValueError(
                "Profile clocks must use the explicitly declared Singapore timezone"
            )
        return self


class PromotionAssumption(DatasetModel):
    service_date: date
    dish_id: str
    publication_date: date
    transaction_multiplier: Decimal = Field(
        ge=0, le=10, allow_inf_nan=False, max_digits=8, decimal_places=4
    )
    kind: Literal["BOGO"]


class HistoryConfig(DatasetModel):
    schema_version: Literal["restock-synthetic-history/1"]
    purpose: Literal["DEVELOPMENT_FIXTURE"]
    dataset_id: str = Field(min_length=1)
    configuration_source: str = Field(min_length=1)
    assumptions: str = Field(min_length=1)
    timezone: Literal["Asia/Singapore"]
    history_start: date
    history_end: date
    simulation_start: AwareDatetime
    partitions: tuple[Partition, ...]
    history_namespace: str = Field(min_length=1)
    development_scenario_namespace: str = Field(min_length=1)
    heldout_scenario_namespace: str = Field(min_length=1)
    seeds: Seeds
    catalogue_reference: str = Field(min_length=1)
    recipe_reference: str = Field(min_length=1)
    catalogue_sha256: str
    recipe_sha256: str
    dishes: tuple[DishAssumption, ...]
    weekday_factors: tuple[Decimal, ...]
    daily_trend: Decimal = Field(ge=0, le="0.01", allow_inf_nan=False)
    variation_transactions: int = Field(strict=True, ge=0, le=100)
    profile: tuple[ProfileAssumption, ...]
    promotions: tuple[PromotionAssumption, ...]
    missing_basis_points: int = Field(strict=True, ge=0, le=10000)
    reporting_error_transactions: int = Field(strict=True, ge=0, le=100)
    correction_delay_days: int = Field(strict=True, ge=1, le=7)

    @model_validator(mode="after")
    def valid(self) -> "HistoryConfig":
        validate_partitions(self.history_start, self.history_end, self.partitions)
        if not 4 <= (self.history_end - self.history_start).days + 1 <= 3660:
            raise ValueError("Development history must contain 4..3660 days")
        if aware(self.simulation_start).date() <= self.history_end:
            raise ValueError("Simulation must follow history")
        if (
            len(
                {
                    self.history_namespace,
                    self.development_scenario_namespace,
                    self.heldout_scenario_namespace,
                }
            )
            != 3
        ):
            raise ValueError("History/development/held-out namespaces must be distinct")
        if len(self.weekday_factors) != 7 or any(
            not x.is_finite() or not 0 <= x <= 3 for x in self.weekday_factors
        ):
            raise ValueError(
                "Seven finite nonnegative Monday-first weekday factors required"
            )
        ids = {d.dish_id for d in self.dishes}
        if not ids or len(ids) != len(self.dishes):
            raise ValueError("Duplicate/missing dish assumptions")
        keys = set()
        for promo in self.promotions:
            key = (promo.service_date, promo.dish_id)
            if (
                key in keys
                or promo.dish_id not in ids
                or not self.history_start <= promo.service_date <= self.history_end
                or promo.publication_date >= promo.service_date
            ):
                raise ValueError("Invalid promotion date/dish/publication or duplicate")
            keys.add(key)
        for digest in (self.catalogue_sha256, self.recipe_sha256):
            if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ValueError("Explicit SHA-256 catalogue/recipe pins required")
        return self

    def dated_profile(self, day: date) -> tuple[ServicePeriod, ...]:
        return tuple(
            ServicePeriod(
                datetime.combine(day, p.start, SINGAPORE),
                datetime.combine(day, p.end, SINGAPORE),
                p.weight,
            )
            for p in self.profile
        )

    def check_catalogue(self, catalogue: Catalogue) -> None:
        if {d.dish_id for d in self.dishes} != {d.id for d in catalogue.menu_items}:
            raise ValueError("Assumptions must cover exactly the current catalogue")
        if (self.catalogue_sha256, self.recipe_sha256) != (
            catalogue.catalogue_hash,
            catalogue.recipe_hash,
        ):
            raise ValueError("Pinned catalogue/recipes differ from supplied models")
        allocate_service_buckets(
            {d.id: Decimal(1) for d in catalogue.menu_items},
            catalogue.menu_items,
            target_date=self.history_start,
            profile=self.dated_profile(self.history_start),
        )
        if any(p.end > time(22) for p in self.profile):
            raise ValueError("Service must finish by the declared 22:00 final cutoff")


def draw(
    config: HistoryConfig,
    stream: Literal["demand", "event_timing", "observation_error"],
    *identity: object,
    modulus: int,
) -> int:
    """Versioned SHA-256 counter stream, no global RNG or row-order dependence.

    Modulo sampling has negligible deterministic bias (at most 1 / 2**256);
    it is a documented fixture assumption, not a statistical restaurant model.
    """
    key = [
        config.history_namespace,
        getattr(config.seeds, stream),
        stream,
        *map(str, identity),
    ]
    return int(sha256(canonical_json(key)), 16) % modulus


def stable_id(config: HistoryConfig, kind: str, *identity: object) -> str:
    return (
        kind
        + ":"
        + sha256(canonical_json([config.dataset_id, kind, *map(str, identity)]))[:24]
    )


def write_csv(path: Path, fields: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def sale_row(
    config: HistoryConfig,
    *,
    day: date,
    dish: DishAssumption,
    revision: int,
    start: datetime,
    end: datetime,
    available: datetime,
    transactions: int,
    promotional: bool,
    missing: bool,
    kind: str,
) -> dict[str, str]:
    with localcontext(Context(prec=40)):
        row = {
            "id": stable_id(
                config, kind, day, dish.dish_id, start.isoformat(), revision
            ),
            "service_date": day.isoformat(),
            "dish_id": dish.dish_id,
            "revision": str(revision),
            "period_start": start.isoformat(),
            "effective_at": end.isoformat(),
            "available_at": available.isoformat(),
            "observed": str(not missing).lower(),
            "served": str(transactions * (2 if promotional else 1)),
            "paid": str(transactions),
            "free": str(transactions if promotional else 0),
            "transactions": str(transactions),
            "revenue_sgd": format(transactions * dish.unit_price_sgd, "f"),
            "unit_price_sgd": format(dish.unit_price_sgd, "f"),
            "promotion": str(promotional).lower(),
            "censored": "false",
        }
    if missing:
        row.update({key: "" for key in NUMBERS})
    return row


def _safe_outputs(observations: Path, evaluator: Path) -> None:
    paths = (observations.resolve(), evaluator.resolve())
    if (
        paths[0] == paths[1]
        or paths[0] in paths[1].parents
        or paths[1] in paths[0].parents
    ):
        raise ValueError(
            "Observation and evaluator directories must be separate, non-nested paths"
        )
    repository = Path(__file__).resolve().parents[3]
    for path in paths:
        if repository == path or repository in path.parents:
            raise ValueError(
                "Write generated datasets outside the application repository"
            )
        if path.exists():
            raise ValueError(
                "Output directories must not exist; no overwriting existing data"
            )


def generate_history(
    config: HistoryConfig, catalogue: Catalogue, *, observations: Path, evaluator: Path
) -> dict[str, int]:
    """Generate complete service batches and two daily reporting revisions/day.

    All attempted transactions are fulfilled. BOGO transactions always consume
    two portions. Report errors/missingness affect only revision 1; revision 2 is
    a late full replacement. No stock counts, receipts or physical losses exist.
    """
    config.check_catalogue(catalogue)
    _safe_outputs(observations, evaluator)
    daily: list[dict[str, str]] = []
    batches: list[dict[str, str]] = []
    truth: list[dict[str, str]] = []
    usage: list[dict[str, str]] = []
    events: list[dict[str, str]] = []
    promos = {(p.service_date, p.dish_id): p for p in config.promotions}
    for promo in sorted(config.promotions, key=lambda p: (p.service_date, p.dish_id)):
        published = datetime.combine(
            promo.publication_date, time(9), SINGAPORE
        ) + timedelta(
            minutes=draw(
                config,
                "event_timing",
                "publication",
                promo.service_date,
                promo.dish_id,
                modulus=60,
            )
        )
        events.append(
            {
                "id": stable_id(config, "promotion", promo.service_date, promo.dish_id),
                "dish_id": promo.dish_id,
                "service_date": promo.service_date.isoformat(),
                "available_at": published.isoformat(),
                "kind": "BOGO",
            }
        )
    intervals: tuple[tuple[time, time], ...] = ()
    for offset in range((config.history_end - config.history_start).days + 1):
        day = config.history_start + timedelta(days=offset)
        start = datetime.combine(day, time(0), SINGAPORE)
        final = datetime.combine(day, time(22), SINGAPORE)
        # Existing allocator validates and produces exact rationally rounded weights.
        weights = allocate_service_buckets(
            {d.id: Decimal(1) for d in catalogue.menu_items},
            catalogue.menu_items,
            target_date=day,
            profile=config.dated_profile(day),
        )
        intervals = tuple(
            (b.start.time().replace(tzinfo=None), b.end.time().replace(tzinfo=None))
            for b in weights
        )
        daily_portions: dict[str, Decimal] = {}
        for dish in sorted(config.dishes, key=lambda d: d.dish_id):
            promo = promos.get((day, dish.dish_id))
            expected = (
                Fraction(dish.base_transactions)
                * Fraction(config.weekday_factors[day.weekday()])
                * (1 + offset * Fraction(config.daily_trend))
            )
            if promo:
                expected *= Fraction(promo.transaction_multiplier)
            jitter = (
                draw(
                    config,
                    "demand",
                    day,
                    dish.dish_id,
                    modulus=2 * config.variation_transactions + 1,
                )
                - config.variation_transactions
            )
            transactions = max(0, round(expected) + jitter)
            portions = transactions * (2 if promo else 1)
            daily_portions[dish.dish_id] = Decimal(portions)
            truth.append(
                {
                    "id": stable_id(config, "attempted", day, dish.dish_id),
                    "service_date": day.isoformat(),
                    "dish_id": dish.dish_id,
                    "attempted_transactions": str(transactions),
                    "attempted_portions": str(portions),
                    "served": str(portions),
                    "unmet": "0",
                    "partition": partition_for(day, config.partitions),
                }
            )
            counts = [0] * len(weights)
            cumulative = []
            total = 0
            for bucket in weights:
                total += int(
                    Fraction(bucket.expected_portions[dish.dish_id]) * 1_000_000
                )
                cumulative.append(total)
            for transaction in range(transactions):
                ticket = draw(
                    config,
                    "event_timing",
                    "service",
                    day,
                    dish.dish_id,
                    transaction,
                    modulus=1_000_000,
                )
                index = next(i for i, bound in enumerate(cumulative) if ticket < bound)
                counts[index] += 1
            for bucket, count in zip(weights, counts, strict=True):
                batches.append(
                    sale_row(
                        config,
                        day=day,
                        dish=dish,
                        revision=1,
                        start=bucket.start,
                        end=bucket.end,
                        available=bucket.end
                        + timedelta(
                            minutes=draw(
                                config,
                                "event_timing",
                                "batch_delay",
                                day,
                                bucket.start,
                                modulus=11,
                            )
                        ),
                        transactions=count,
                        promotional=promo is not None,
                        missing=False,
                        kind="batch",
                    )
                )
            error = (
                draw(
                    config,
                    "observation_error",
                    "report",
                    day,
                    dish.dish_id,
                    modulus=2 * config.reporting_error_transactions + 1,
                )
                - config.reporting_error_transactions
            )
            missing = (
                draw(
                    config,
                    "observation_error",
                    "missing",
                    day,
                    dish.dish_id,
                    modulus=10000,
                )
                < config.missing_basis_points
            )
            for revision in (1, 2):
                daily.append(
                    sale_row(
                        config,
                        day=day,
                        dish=dish,
                        revision=revision,
                        start=start,
                        end=final,
                        available=final
                        + timedelta(
                            days=(config.correction_delay_days if revision == 2 else 0)
                        ),
                        transactions=max(0, transactions + error)
                        if revision == 1
                        else transactions,
                        promotional=promo is not None,
                        missing=missing and revision == 1,
                        kind="daily",
                    )
                )
        requirements = calculate_requirements(
            daily_portions,
            catalogue.menu_items,
            catalogue.ingredients,
            catalogue.recipes,
        )
        for ingredient in sorted(catalogue.ingredients, key=lambda x: x.id):
            usage.append(
                {
                    "service_date": day.isoformat(),
                    "ingredient_id": ingredient.id,
                    "unit": ingredient.unit,
                    "quantity": format(requirements[ingredient.id], "f"),
                }
            )
    observations.mkdir(parents=True)
    evaluator.mkdir(parents=True)
    (observations / "catalogue.json").write_bytes(canonical_json(catalogue.content()))
    write_csv(observations / "daily_sales.csv", SALES_FIELDS, daily)
    write_csv(observations / "sales_batches.csv", SALES_FIELDS, batches)
    write_csv(observations / "promotions.csv", PROMOTION_FIELDS, events)
    manifest = ObservationManifest(
        schema_version=SCHEMA_VERSION,
        generator_version=GENERATOR_VERSION,
        dataset_id=config.dataset_id,
        purpose=config.purpose,
        timezone=config.timezone,
        history_start=config.history_start,
        history_end=config.history_end,
        simulation_start=config.simulation_start,
        partitions=config.partitions,
        catalogue_reference=config.catalogue_reference,
        recipe_reference=config.recipe_reference,
        catalogue_sha256=catalogue.catalogue_hash,
        recipe_sha256=catalogue.recipe_hash,
        service_intervals=intervals,
        files={
            name: sha256((observations / name).read_bytes()) for name in PUBLIC_FILES
        },
    )
    (observations / "manifest.json").write_bytes(
        canonical_json(manifest.model_dump(mode="json"))
    )
    # Canonical ordering makes input catalogue/config row order irrelevant.
    configuration = config.model_dump(mode="json")
    configuration["dishes"] = [
        d.model_dump(mode="json")
        for d in sorted(config.dishes, key=lambda x: x.dish_id)
    ]
    configuration["profile"] = [
        p.model_dump(mode="json") for p in sorted(config.profile, key=lambda x: x.start)
    ]
    configuration["promotions"] = [
        p.model_dump(mode="json")
        for p in sorted(config.promotions, key=lambda x: (x.service_date, x.dish_id))
    ]
    (evaluator / "configuration.json").write_bytes(canonical_json(configuration))
    write_csv(evaluator / "attempted_demand.csv", TRUTH_FIELDS, truth)
    write_csv(evaluator / "ingredient_usage.csv", USAGE_FIELDS, usage)
    private_manifest = {
        **manifest.model_dump(mode="json"),
        "seeds": config.seeds.model_dump(),
        "history_namespace": config.history_namespace,
        "development_scenario_namespace": config.development_scenario_namespace,
        "heldout_scenario_namespace": config.heldout_scenario_namespace,
        "observation_manifest_sha256": sha256(
            (observations / "manifest.json").read_bytes()
        ),
        "files": {
            name: sha256((evaluator / name).read_bytes()) for name in PRIVATE_FILES
        },
    }
    (evaluator / "manifest.json").write_bytes(canonical_json(private_manifest))
    return validate_dataset(observations=observations, evaluator=evaluator)


def validate_dataset(*, observations: Path, evaluator: Path) -> dict[str, int]:
    """Offline evaluator check. Never called by the forecaster-facing reader."""
    from src.history_dataset import read_catalogue

    counts = validate_observations(observations)
    private = json.loads((evaluator / "manifest.json").read_bytes())
    public = json.loads((observations / "manifest.json").read_bytes())
    config = HistoryConfig.model_validate_json(
        (evaluator / "configuration.json").read_bytes()
    )
    catalogue = read_catalogue(observations / "catalogue.json")
    config.check_catalogue(catalogue)
    if set(private["files"]) != set(PRIVATE_FILES) or {
        p.name for p in evaluator.iterdir()
    } != set(PRIVATE_FILES) | {"manifest.json"}:
        raise ValueError("Unexpected evaluator file set")
    if private["observation_manifest_sha256"] != sha256(
        (observations / "manifest.json").read_bytes()
    ):
        raise ValueError("Observation/evaluator manifest link mismatch")
    for name, digest in private["files"].items():
        if sha256((evaluator / name).read_bytes()) != digest:
            raise ValueError("Evaluator content hash mismatch")
    for key, value in public.items():
        if key != "files" and private.get(key) != value:
            raise ValueError("Manifest metadata mismatch")
    for key in (
        "seeds",
        "history_namespace",
        "development_scenario_namespace",
        "heldout_scenario_namespace",
    ):
        if private.get(key) != config.model_dump(mode="json")[key]:
            raise ValueError("Manifest seed/namespace mismatch")
    for key in (
        "history_start",
        "history_end",
        "partitions",
        "simulation_start",
        "catalogue_reference",
        "recipe_reference",
        "dataset_id",
        "purpose",
    ):
        if public[key] != config.model_dump(mode="json")[key]:
            raise ValueError("Configuration/manifest mismatch")
    # The configuration repeats this local profile each day. Expand through the
    # same dated allocator as generation; input period ordering is not semantic.
    configured_buckets = allocate_service_buckets(
        {dish.id: Decimal(0) for dish in catalogue.menu_items},
        catalogue.menu_items,
        target_date=config.history_start,
        profile=config.dated_profile(config.history_start),
    )
    configured_intervals = tuple(
        (
            bucket.start.time().replace(tzinfo=None),
            bucket.end.time().replace(tzinfo=None),
        )
        for bucket in configured_buckets
    )
    if (
        configured_intervals
        != ObservationManifest.model_validate(public).service_intervals
    ):
        raise ValueError(
            "Configured service intervals differ from observation manifest"
        )
    daily = read_csv(observations / "daily_sales.csv", SALES_FIELDS)
    batches = read_csv(observations / "sales_batches.csv", SALES_FIELDS)
    prices = {d.dish_id: d.unit_price_sgd for d in config.dishes}
    if len(daily) != counts["target_days"] * len(prices) * 2:
        raise ValueError("Generator v1 requires exactly two daily revisions")
    for row in daily + batches:
        if flag(row["censored"]):
            raise ValueError(
                "Fully supplied generator cannot certify stockout censoring"
            )
        if (
            flag(row["observed"])
            and money(row["unit_price_sgd"]) != prices[row["dish_id"]]
        ):
            raise ValueError("Declared fixture price mismatch")
    for row in daily:
        revision = int(row["revision"])
        if revision not in (1, 2) or (
            aware(row["available_at"])
            != aware(row["effective_at"])
            + timedelta(days=config.correction_delay_days if revision == 2 else 0)
        ):
            raise ValueError(
                "Daily revision recording clock differs from declared config"
            )
        if revision == 2 and not flag(row["observed"]):
            raise ValueError("Final correction must cover every dish explicitly")
    if any(not flag(row["observed"]) for row in batches):
        raise ValueError("Fully supplied fixture declares complete service batches")
    configured_promos = {
        (p.service_date.isoformat(), p.dish_id) for p in config.promotions
    }
    actual_promos = {
        (r["service_date"], r["dish_id"])
        for r in read_csv(observations / "promotions.csv", PROMOTION_FIELDS)
    }
    if actual_promos != configured_promos:
        raise ValueError("Promotion configuration differs from published events")
    publication_dates = {
        (p.service_date.isoformat(), p.dish_id): p.publication_date
        for p in config.promotions
    }
    for row in read_csv(observations / "promotions.csv", PROMOTION_FIELDS):
        if (
            aware(row["available_at"]).date()
            != publication_dates[row["service_date"], row["dish_id"]]
        ):
            raise ValueError("Promotion recording date differs from declared config")
    truth = read_csv(evaluator / "attempted_demand.csv", TRUTH_FIELDS)
    usage = read_csv(evaluator / "ingredient_usage.csv", USAGE_FIELDS)
    final = {
        (r["service_date"], r["dish_id"]): r for r in daily if r["revision"] == "2"
    }
    for row in daily:
        if row["revision"] == "1":
            if flag(row["observed"]):
                corrected = final[row["service_date"], row["dish_id"]]
                if (
                    config.missing_basis_points == 10000
                    or abs(
                        integer(row["transactions"])
                        - integer(corrected["transactions"])
                    )
                    > config.reporting_error_transactions
                ):
                    raise ValueError(
                        "Initial report exceeds declared observation-error bounds"
                    )
            elif config.missing_basis_points == 0:
                raise ValueError("Undeclared missing observation")
    batch_totals: dict[tuple[str, str], int] = {}
    for row in batches:
        key = (row["service_date"], row["dish_id"])
        batch_totals[key] = batch_totals.get(key, 0) + integer(row["served"])
    seen = set()
    for row in truth:
        key = (row["service_date"], row["dish_id"])
        if key in seen or key not in final or not row["id"]:
            raise ValueError("Invalid/duplicate truth coverage")
        seen.add(key)
        observed = final[key]
        attempted, served, unmet = (
            integer(row[k]) for k in ("attempted_portions", "served", "unmet")
        )
        if (
            attempted != served + unmet
            or unmet != 0
            or served != integer(observed["served"])
            or served != batch_totals[key]
        ):
            raise ValueError(
                "Fully supplied truth, final labels and batch totals disagree"
            )
        if (
            integer(row["attempted_transactions"])
            * (2 if flag(observed["promotion"]) else 1)
            != attempted
        ):
            raise ValueError("Attempted BOGO transaction/portion accounting mismatch")
        if row["partition"] != partition_for(
            date.fromisoformat(row["service_date"]), config.partitions
        ):
            raise ValueError("Target partition leakage")
    if seen != set(final) or len(final) != counts["target_days"] * len(
        catalogue.menu_items
    ):
        raise ValueError("Incomplete truth/final coverage")
    expected_usage = {}
    for day in sorted({r["service_date"] for r in truth}):
        requirements = calculate_requirements(
            {
                r["dish_id"]: Decimal(r["served"])
                for r in truth
                if r["service_date"] == day
            },
            catalogue.menu_items,
            catalogue.ingredients,
            catalogue.recipes,
        )
        expected_usage.update(
            {(day, i.id): (i.unit, requirements[i.id]) for i in catalogue.ingredients}
        )
    seen_usage = set()
    for row in usage:
        key = (row["service_date"], row["ingredient_id"])
        if (
            key in seen_usage
            or key not in expected_usage
            or (row["unit"], money(row["quantity"])) != expected_usage[key]
        ):
            raise ValueError("Ingredient accounting/unit/coverage mismatch")
        seen_usage.add(key)
    if seen_usage != set(expected_usage):
        raise ValueError("Missing explicit ingredient usage")
    return {**counts, "truth_rows": len(truth), "ingredient_rows": len(usage)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--catalogue-fixture", type=Path)
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--evaluator", type=Path, required=True)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    if args.validate_only:
        result = validate_dataset(
            observations=args.observations, evaluator=args.evaluator
        )
    else:
        if args.config is None or args.catalogue_fixture is None:
            parser.error("Generation requires --config and --catalogue-fixture")
        config = HistoryConfig.model_validate_json(args.config.read_bytes())
        raw = json.loads(args.catalogue_fixture.read_bytes())
        catalogue = Catalogue.model_validate(
            {k: raw[k] for k in ("menu_items", "ingredients", "recipes")}
        )
        result = generate_history(
            config, catalogue, observations=args.observations, evaluator=args.evaluator
        )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
