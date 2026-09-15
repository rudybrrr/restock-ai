"""Local synthetic dataset format and observation-only readers (not API schemas).

The reader has no dependency on the generator or evaluator. Daily revisions are
replacement vectors; incremental batches are validated but never added to them.
"""

import csv
import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from fractions import Fraction
from itertools import pairwise
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, model_validator

from src.forecasting import SINGAPORE, DailySalesObservation
from src.requirements import calculate_requirements
from src.schemas import Ingredient, MenuItem, RecipeItem

SCHEMA_VERSION = "restock-synthetic-history/1"
PUBLIC_FILES = (
    "catalogue.json",
    "daily_sales.csv",
    "sales_batches.csv",
    "promotions.csv",
)
PartitionName = Literal["warmup", "train", "validation", "test"]


class DatasetModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    @model_validator(mode="before")
    @classmethod
    def no_binary_floats(cls, value: object) -> object:
        def check(item: object) -> None:
            if isinstance(item, float):
                raise ValueError(  # noqa: TRY004 - Pydantic wraps ValueError as validation failure.
                    "Use decimal strings, not binary floating-point inputs"
                )
            if isinstance(item, dict):
                for child in item.values():
                    check(child)
            elif isinstance(item, (list, tuple)):
                for child in item:
                    check(child)

        check(value)
        return value


class Partition(DatasetModel):
    name: PartitionName
    start: date
    end: date


def validate_partitions(
    start: date, end: date, partitions: tuple[Partition, ...]
) -> None:
    if start > end or tuple(p.name for p in partitions) != (
        "warmup",
        "train",
        "validation",
        "test",
    ):
        raise ValueError("Require ordered warmup/train/validation/test target windows")
    cursor = start
    for part in partitions:
        if part.start != cursor or part.end < part.start:
            raise ValueError(
                "Partitions must cover history exactly without gaps/overlap"
            )
        cursor = part.end + timedelta(days=1)
    if cursor != end + timedelta(days=1):
        raise ValueError("Partition end differs from history end")


def partition_for(target: date, partitions: tuple[Partition, ...]) -> PartitionName:
    for part in partitions:
        if part.start <= target <= part.end:
            return part.name
    raise ValueError("Target outside declared history")


def canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    ).encode()


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class Catalogue(DatasetModel):
    menu_items: tuple[MenuItem, ...]
    ingredients: tuple[Ingredient, ...]
    recipes: tuple[RecipeItem, ...]

    @model_validator(mode="after")
    def valid_recipes(self) -> "Catalogue":
        calculate_requirements(
            {dish.id: Decimal(0) for dish in self.menu_items},
            self.menu_items,
            self.ingredients,
            self.recipes,
        )
        return self

    def content(self) -> dict[str, object]:
        return {
            "menu_items": [
                x.model_dump(mode="json")
                for x in sorted(self.menu_items, key=lambda x: x.id)
            ],
            "ingredients": [
                x.model_dump(mode="json")
                for x in sorted(self.ingredients, key=lambda x: x.id)
            ],
            "recipes": [
                x.model_dump(mode="json")
                for x in sorted(
                    self.recipes, key=lambda x: (x.menu_item_id, x.ingredient_id)
                )
            ],
        }

    @property
    def catalogue_hash(self) -> str:
        content = self.content()
        return sha256(
            canonical_json({k: content[k] for k in ("menu_items", "ingredients")})
        )

    @property
    def recipe_hash(self) -> str:
        return sha256(canonical_json(self.content()["recipes"]))


def read_catalogue(path: Path) -> Catalogue:
    raw = json.loads(path.read_text(encoding="utf-8"))
    # Existing backend models ignore extra fields; dataset boundaries must not.
    if set(raw) != {"menu_items", "ingredients", "recipes"}:
        raise ValueError("Catalogue must contain only existing catalogue models")
    for key, model in (
        ("menu_items", MenuItem),
        ("ingredients", Ingredient),
        ("recipes", RecipeItem),
    ):
        for row in raw[key]:
            if set(row) != set(model.model_fields):
                raise ValueError("Unknown/missing catalogue field")
    return Catalogue.model_validate(raw)


class ObservationManifest(DatasetModel):
    schema_version: Literal["restock-synthetic-history/1"]
    generator_version: str
    dataset_id: str
    purpose: Literal["DEVELOPMENT_FIXTURE"]
    timezone: Literal["Asia/Singapore"]
    history_start: date
    history_end: date
    simulation_start: AwareDatetime
    partitions: tuple[Partition, ...]
    catalogue_reference: str
    recipe_reference: str
    catalogue_sha256: str
    recipe_sha256: str
    # Public coverage, without hidden demand parameters or service weights.
    service_intervals: tuple[tuple[time, time], ...]
    files: dict[str, str]

    @model_validator(mode="after")
    def valid(self) -> "ObservationManifest":
        validate_partitions(self.history_start, self.history_end, self.partitions)
        if self.simulation_start.astimezone(SINGAPORE).date() <= self.history_end:
            raise ValueError("Simulation must start after history")
        if set(self.files) != set(PUBLIC_FILES):
            raise ValueError("Unexpected public file set")
        if not all((self.dataset_id, self.catalogue_reference, self.recipe_reference)):
            raise ValueError("Dataset and catalogue references are required")
        previous = time(0)
        if not self.service_intervals:
            raise ValueError("Service coverage required")
        for start, end in self.service_intervals:
            if start.tzinfo or end.tzinfo or not previous <= start < end:
                raise ValueError("Invalid service coverage")
            if (
                end > time(22)
                or any(t.minute % 30 or t.second or t.microsecond for t in (start, end))
                or datetime.combine(date.min, end) - datetime.combine(date.min, start)
                != timedelta(minutes=30)
            ):
                raise ValueError(
                    "Require half-hour service coverage before final cutoff"
                )
            previous = end
        return self


SALES_FIELDS = (
    "id",
    "service_date",
    "dish_id",
    "revision",
    "period_start",
    "effective_at",
    "available_at",
    "observed",
    "served",
    "paid",
    "free",
    "transactions",
    "revenue_sgd",
    "unit_price_sgd",
    "promotion",
    "censored",
)
PROMOTION_FIELDS = ("id", "dish_id", "service_date", "available_at", "kind")
NUMBERS = ("served", "paid", "free", "transactions", "revenue_sgd", "unit_price_sgd")


def read_csv(path: Path, fields: tuple[str, ...]) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != list(fields):
            raise ValueError(f"Unexpected columns in {path.name}")
        result = []
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError("Malformed CSV row")
            result.append(row)
        return result


def aware(value: str | datetime) -> datetime:
    timestamp = datetime.fromisoformat(value) if isinstance(value, str) else value
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("Timezone-aware timestamp required")
    return timestamp.astimezone(SINGAPORE)


def integer(value: str) -> int:
    if not value.isascii() or not value.isdecimal():
        raise ValueError("Nonnegative integer required")
    return int(value)


def flag(value: str) -> bool:
    if value not in ("true", "false"):
        raise ValueError("Explicit boolean required")
    return value == "true"


def money(value: str) -> Decimal:
    amount = Decimal(value)
    if not amount.is_finite() or amount < 0:
        raise ValueError("Finite nonnegative money required")
    return amount


def validate_sales_row(row: dict[str, str], dishes: set[str]) -> None:
    day = date.fromisoformat(row["service_date"])
    start, end, available = (
        aware(row[k]) for k in ("period_start", "effective_at", "available_at")
    )
    if row["dish_id"] not in dishes or not row["id"] or integer(row["revision"]) < 1:
        raise ValueError("Unknown dish or invalid sales identity/revision")
    if start.date() != day or end.date() != day or not start < end <= available:
        raise ValueError("Invalid effective/availability interval")
    promotional = flag(row["promotion"])
    flag(row["censored"])
    if not flag(row["observed"]):
        if any(row[k] != "" for k in NUMBERS):
            raise ValueError("Missing observations must have blank numerical fields")
        return
    served, paid, free, transactions = (integer(row[k]) for k in NUMBERS[:4])
    revenue, price = (money(row[k]) for k in NUMBERS[4:])
    if served != paid + free or paid != transactions:
        raise ValueError("Invalid portion/transaction accounting")
    if free != (paid if promotional else 0):
        raise ValueError("BOGO pairs must be atomic, with one paid and one free")
    if Fraction(revenue) != paid * Fraction(price):
        raise ValueError("Revenue differs from paid portions times declared price")


@dataclass(frozen=True)
class PublishedPromotion:
    id: str
    dish_id: str
    service_date: date
    available_at: datetime
    kind: Literal["BOGO"] = "BOGO"


@dataclass(frozen=True)
class ForecastInputs:
    history: tuple[DailySalesObservation, ...]
    promotions: tuple[PublishedPromotion, ...]
    catalogue_sha256: str
    recipe_sha256: str


def validate_observations(directory: Path) -> dict[str, int]:
    """Validate integrity AND semantic coverage/accounting; never read truth."""
    manifest = ObservationManifest.model_validate_json(
        (directory / "manifest.json").read_bytes()
    )
    if {p.name for p in directory.iterdir()} != set(PUBLIC_FILES) | {"manifest.json"}:
        raise ValueError("Observation directory contains undeclared files")
    for name, digest in manifest.files.items():
        if sha256((directory / name).read_bytes()) != digest:
            raise ValueError(f"Hash mismatch: {name}")
    catalogue = read_catalogue(directory / "catalogue.json")
    if (catalogue.catalogue_hash, catalogue.recipe_hash) != (
        manifest.catalogue_sha256,
        manifest.recipe_sha256,
    ):
        raise ValueError("Catalogue/recipe provenance mismatch")
    dishes = {x.id for x in catalogue.menu_items}
    groups: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    daily = read_csv(directory / "daily_sales.csv", SALES_FIELDS)
    batches = read_csv(directory / "sales_batches.csv", SALES_FIELDS)
    for rows in (daily, batches):
        ids: set[str] = set()
        for row in rows:
            validate_sales_row(row, dishes)
            partition_for(date.fromisoformat(row["service_date"]), manifest.partitions)
            if row["id"] in ids:
                raise ValueError("Duplicate row ID")
            ids.add(row["id"])
    for row in daily:
        groups[row["service_date"], row["revision"]].append(row)
    expected_days = {
        (manifest.history_start + timedelta(days=i)).isoformat()
        for i in range((manifest.history_end - manifest.history_start).days + 1)
    }
    if {day for day, _ in groups} != expected_days:
        raise ValueError("Missing daily manifest coverage")
    revisions: dict[str, list[tuple[int, datetime]]] = defaultdict(list)
    for (day, revision), rows in groups.items():
        if len(rows) != len(dishes) or {r["dish_id"] for r in rows} != dishes:
            raise ValueError(
                "Every daily revision requires every dish; missing is explicit"
            )
        clocks = {
            (r["period_start"], r["effective_at"], r["available_at"]) for r in rows
        }
        if len(clocks) != 1:
            raise ValueError("A daily revision is an atomic replacement vector")
        start, end, available = next(iter(clocks))
        if aware(start).time() != time(0) or aware(end).time() != time(22):
            raise ValueError("This dataset format declares daily final cutoff at 22:00")
        revisions[day].append((int(revision), aware(available)))
    for versions in revisions.values():
        versions.sort()
        if [r for r, _ in versions] != list(range(1, len(versions) + 1)) or any(
            b[1] <= a[1] for a, b in pairwise(versions)
        ):
            raise ValueError(
                "Revisions must be contiguous with increasing availability"
            )
    # Complete, incremental service intervals only; no implied coverage in closures.
    batch_keys = set()
    for row in batches:
        key = (
            row["service_date"],
            row["dish_id"],
            aware(row["period_start"]).time(),
            aware(row["effective_at"]).time(),
        )
        if key in batch_keys or row["revision"] != "1":
            raise ValueError("Duplicate/corrected batch unsupported in format v1")
        batch_keys.add(key)
    expected_keys = {
        (day, dish, start, end)
        for day in expected_days
        for dish in dishes
        for start, end in manifest.service_intervals
    }
    if batch_keys != expected_keys:
        raise ValueError("Missing/overlapping/extra service batch coverage")
    events = read_csv(directory / "promotions.csv", PROMOTION_FIELDS)
    event_keys = set()
    event_ids = set()
    for row in events:
        key = (row["service_date"], row["dish_id"])
        if (
            key in event_keys
            or row["dish_id"] not in dishes
            or row["kind"] != "BOGO"
            or not row["id"]
            or row["id"] in event_ids
        ):
            raise ValueError("Invalid/duplicate promotional context")
        event_keys.add(key)
        event_ids.add(row["id"])
        partition_for(date.fromisoformat(row["service_date"]), manifest.partitions)
        if aware(row["available_at"]).date() >= date.fromisoformat(row["service_date"]):
            raise ValueError(
                "This fixture declares promotions published before service day"
            )
    for row in daily + batches:
        if flag(row["promotion"]) != (
            (row["service_date"], row["dish_id"]) in event_keys
        ):
            raise ValueError("Promotion flags disagree with published context")
    return {
        "daily_rows": len(daily),
        "batch_rows": len(batches),
        "promotion_rows": len(events),
        "target_days": len(expected_days),
    }


def load_forecast_inputs(directory: Path, *, issue_time: datetime) -> ForecastInputs:
    """Return only available sales labels and published context at an aware origin.

    Batches never substitute for a missing final total. The existing baseline
    selects visible revisions and applies its eligibility/sparse-history rules.
    """
    issue_time = aware(issue_time)
    validate_observations(directory)
    manifest = ObservationManifest.model_validate_json(
        (directory / "manifest.json").read_bytes()
    )
    groups: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in read_csv(directory / "daily_sales.csv", SALES_FIELDS):
        if (
            aware(row["available_at"]) <= issue_time
            and aware(row["effective_at"]) <= issue_time
        ):
            groups[row["service_date"], row["revision"]].append(row)
    history = tuple(
        DailySalesObservation(
            service_date=date.fromisoformat(day),
            available_at=aware(rows[0]["available_at"]),
            revision=int(revision),
            portions={
                r["dish_id"]: int(r["served"]) for r in rows if flag(r["observed"])
            },
            promotion=any(flag(r["promotion"]) for r in rows),
            censored=any(flag(r["censored"]) for r in rows),
        )
        for (day, revision), rows in sorted(
            groups.items(), key=lambda x: (x[0][0], int(x[0][1]))
        )
    )
    promotions = tuple(
        PublishedPromotion(
            r["id"],
            r["dish_id"],
            date.fromisoformat(r["service_date"]),
            aware(r["available_at"]),
        )
        for r in read_csv(directory / "promotions.csv", PROMOTION_FIELDS)
        if aware(r["available_at"]) <= issue_time
    )
    return ForecastInputs(
        history, promotions, manifest.catalogue_sha256, manifest.recipe_sha256
    )


def load_partition_targets(
    directory: Path, *, partition: PartitionName, known_at: datetime
) -> tuple[DailySalesObservation, ...]:
    """Latest visible daily labels in ONE target partition, preserving missingness.

    No feature rows or multi-horizon origin/label joins are generated here. Callers
    must not concatenate held-out targets into fitting/tuning data.
    """
    if partition not in ("warmup", "train", "validation", "test"):
        raise ValueError("Unknown target partition")
    manifest = ObservationManifest.model_validate_json(
        (directory / "manifest.json").read_bytes()
    )
    latest: dict[date, DailySalesObservation] = {}
    for observation in load_forecast_inputs(directory, issue_time=known_at).history:
        if partition_for(observation.service_date, manifest.partitions) == partition:
            latest[observation.service_date] = observation
    return tuple(latest.values())
