"""Independent synthetic accounting, chronology, leakage and corruption checks."""

import ast
import json
from dataclasses import fields
from datetime import date, datetime
from decimal import Decimal, localcontext
from pathlib import Path

import pytest

from src.forecasting import seasonal_baseline
from src.history_dataset import (
    PROMOTION_FIELDS,
    SALES_FIELDS,
    Catalogue,
    canonical_json,
    load_forecast_inputs,
    load_partition_targets,
    partition_for,
    read_csv,
    sha256,
    validate_observations,
)
from src.synthetic_history import (
    TRUTH_FIELDS,
    USAGE_FIELDS,
    HistoryConfig,
    generate_history,
    validate_dataset,
    write_csv,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def catalogue() -> Catalogue:
    raw = json.loads((FIXTURES / "seasonal_baseline_v3.json").read_bytes())
    return Catalogue.model_validate(
        {k: raw[k] for k in ("menu_items", "ingredients", "recipes")}
    )


@pytest.fixture
def configuration() -> dict:
    raw = json.loads((FIXTURES / "history_development_v1.json").read_bytes())
    # Four days, one target day per partition, hand-checkable transactions.
    raw.update(
        history_start="2025-09-01",
        history_end="2025-09-04",
        simulation_start="2025-09-06T08:00:00+08:00",
        partitions=[
            {"name": name, "start": f"2025-09-0{i}", "end": f"2025-09-0{i}"}
            for i, name in enumerate(("warmup", "train", "validation", "test"), 1)
        ],
        weekday_factors=["1"] * 7,
        daily_trend="0",
        variation_transactions=0,
        missing_basis_points=0,
        reporting_error_transactions=0,
        promotions=[
            {
                "service_date": "2025-09-02",
                "dish_id": "chicken-rice",
                "publication_date": "2025-09-01",
                "transaction_multiplier": "1",
                "kind": "BOGO",
            }
        ],
    )
    for dish in raw["dishes"]:
        dish["base_transactions"] = "3" if dish["dish_id"] == "chicken-rice" else "0"
        dish["unit_price_sgd"] = "2.35"
    return raw


def generate(
    tmp_path: Path, configuration: dict, catalogue: Catalogue, name: str = "one"
) -> tuple[Path, Path]:
    observations, evaluator = (
        tmp_path / name / "observations",
        tmp_path / name / "evaluator",
    )
    generate_history(
        HistoryConfig.model_validate(configuration),
        catalogue,
        observations=observations,
        evaluator=evaluator,
    )
    return observations, evaluator


def refresh_public(directory: Path) -> None:
    """Rehash tampered fixtures so semantic tests do not stop at integrity checks."""
    path = directory / "manifest.json"
    manifest = json.loads(path.read_bytes())
    for name in manifest["files"]:
        manifest["files"][name] = sha256((directory / name).read_bytes())
    path.write_bytes(canonical_json(manifest))


def refresh_private(observations: Path, evaluator: Path) -> None:
    path = evaluator / "manifest.json"
    manifest = json.loads(path.read_bytes())
    for name in manifest["files"]:
        manifest["files"][name] = sha256((evaluator / name).read_bytes())
    manifest["observation_manifest_sha256"] = sha256(
        (observations / "manifest.json").read_bytes()
    )
    path.write_bytes(canonical_json(manifest))


def test_independent_portion_money_recipe_oracle(tmp_path, configuration, catalogue):
    observations, evaluator = generate(tmp_path, configuration, catalogue)
    assert validate_dataset(observations=observations, evaluator=evaluator) == {
        "daily_rows": 40,
        "batch_rows": 280,
        "promotion_rows": 1,
        "target_days": 4,
        "truth_rows": 20,
        "ingredient_rows": 32,
    }
    daily = read_csv(observations / "daily_sales.csv", SALES_FIELDS)
    promo = next(
        r
        for r in daily
        if r["service_date"] == "2025-09-02"
        and r["dish_id"] == "chicken-rice"
        and r["revision"] == "2"
    )
    # Three transactions buy three pairs: 6 portions, 3 paid, 3 free, 3 * 2.35.
    assert [
        promo[k] for k in ("served", "paid", "free", "transactions", "revenue_sgd")
    ] == ["6", "3", "3", "3", "7.05"]
    usage = {
        r["ingredient_id"]: Decimal(r["quantity"])
        for r in read_csv(evaluator / "ingredient_usage.csv", USAGE_FIELDS)
        if r["service_date"] == "2025-09-02"
    }
    # Six chicken-rice portions use .15 chicken, .10 rice and .01 soy each.
    assert usage == {
        "chicken": Decimal(".900"),
        "rice": Decimal(".600"),
        "soy-sauce": Decimal(".060"),
        "noodles": Decimal(0),
        "eggs": Decimal(0),
        "tofu": Decimal(0),
        "vegetables": Decimal(0),
        "oil": Decimal(0),
    }
    batches = [
        r
        for r in read_csv(observations / "sales_batches.csv", SALES_FIELDS)
        if r["service_date"] == "2025-09-02" and r["dish_id"] == "chicken-rice"
    ]
    assert sum(int(r["served"]) for r in batches) == 6
    assert all(int(r["served"]) % 2 == 0 for r in batches)  # No half-promotional pair.
    assert sum(int(r["transactions"]) for r in batches) == 3


def test_reproducible_separate_directories_order_and_decimal_context(
    tmp_path, configuration, catalogue
):
    original = json.dumps(configuration, sort_keys=True)
    before = catalogue.model_dump_json()
    one = generate(tmp_path, configuration, catalogue, "one")
    configuration["dishes"].reverse()
    configuration["profile"].reverse()
    reversed_catalogue = Catalogue(
        menu_items=tuple(reversed(catalogue.menu_items)),
        ingredients=tuple(reversed(catalogue.ingredients)),
        recipes=tuple(reversed(catalogue.recipes)),
    )
    with localcontext() as context:
        context.prec = 3
        two = generate(tmp_path, configuration, reversed_catalogue, "two")
    for first, second in zip(one, two, strict=True):
        assert {p.name: p.read_bytes() for p in first.iterdir()} == {
            p.name: p.read_bytes() for p in second.iterdir()
        }
    configuration["dishes"].reverse()
    configuration["profile"].reverse()
    assert json.dumps(configuration, sort_keys=True) == original
    assert catalogue.model_dump_json() == before


@pytest.mark.parametrize("stream", ["demand", "event_timing", "observation_error"])
def test_independent_streams(tmp_path, configuration, catalogue, stream):
    configuration.update(
        variation_transactions=4,
        reporting_error_transactions=2,
        missing_basis_points=1000,
    )
    first, truth_first = generate(tmp_path, configuration, catalogue, "first")
    configuration["seeds"][stream] += 99
    second, truth_second = generate(tmp_path, configuration, catalogue, "second")
    if stream == "demand":
        assert (truth_first / "attempted_demand.csv").read_bytes() != (
            truth_second / "attempted_demand.csv"
        ).read_bytes()
    else:
        for name in ("attempted_demand.csv", "ingredient_usage.csv"):
            assert (truth_first / name).read_bytes() == (
                truth_second / name
            ).read_bytes()
    if stream == "observation_error":
        for name in ("sales_batches.csv", "promotions.csv"):
            assert (first / name).read_bytes() == (second / name).read_bytes()
        assert (first / "daily_sales.csv").read_bytes() != (
            second / "daily_sales.csv"
        ).read_bytes()
    if stream == "event_timing":
        assert (first / "daily_sales.csv").read_bytes() == (
            second / "daily_sales.csv"
        ).read_bytes()
        assert (first / "sales_batches.csv").read_bytes() != (
            second / "sales_batches.csv"
        ).read_bytes()
    ids_one = {r["id"] for r in read_csv(first / "daily_sales.csv", SALES_FIELDS)}
    ids_two = {r["id"] for r in read_csv(second / "daily_sales.csv", SALES_FIELDS)}
    assert ids_one == ids_two


def test_missing_zero_revisions_and_no_batch_double_count(
    tmp_path, configuration, catalogue
):
    configuration["missing_basis_points"] = 10000
    observations, _ = generate(tmp_path, configuration, catalogue)
    early = load_forecast_inputs(
        observations, issue_time=datetime.fromisoformat("2025-09-01T22:00:00+08:00")
    )
    assert len(early.history) == 1 and dict(early.history[0].portions) == {}
    targets = load_partition_targets(
        observations,
        partition="warmup",
        known_at=datetime.fromisoformat("2025-09-02T22:00:00+08:00"),
    )
    assert len(targets) == 1 and targets[0].revision == 2
    assert dict(targets[0].portions) == {
        "chicken-rice": 3,
        "fried-rice": 0,
        "chicken-noodles": 0,
        "tofu-bowl": 0,
        "vegetable-noodles": 0,
    }
    # Batches total three but cannot repair an unavailable/missing final submission.
    before_final = load_forecast_inputs(
        observations, issue_time=datetime.fromisoformat("2025-09-01T21:30:00+08:00")
    )
    assert before_final.history == ()


def test_late_correction_and_future_promotion_visibility(
    tmp_path, configuration, catalogue
):
    observations, _ = generate(tmp_path, configuration, catalogue)
    rows = read_csv(observations / "daily_sales.csv", SALES_FIELDS)
    for row in rows:
        if (
            row["service_date"] == "2025-09-01"
            and row["revision"] == "1"
            and row["dish_id"] == "chicken-rice"
        ):
            row.update(served="2", paid="2", transactions="2", revenue_sgd="4.70")
    write_csv(observations / "daily_sales.csv", SALES_FIELDS, rows)
    refresh_public(observations)
    before = load_forecast_inputs(
        observations, issue_time=datetime.fromisoformat("2025-09-01T08:59:59+08:00")
    )
    assert before.promotions == () and before.history == ()
    early = load_partition_targets(
        observations,
        partition="warmup",
        known_at=datetime.fromisoformat("2025-09-02T21:59:59+08:00"),
    )
    late = load_partition_targets(
        observations,
        partition="warmup",
        known_at=datetime.fromisoformat("2025-09-02T22:00:00+08:00"),
    )
    assert early[0].portions["chicken-rice"] == 2
    assert late[0].portions["chicken-rice"] == 3
    assert load_forecast_inputs(
        observations, issue_time=datetime.fromisoformat("2025-09-01T10:00:00+08:00")
    ).promotions[0].service_date == date(2025, 9, 2)


def test_chronological_target_windows_and_warmup_insufficiency(
    tmp_path, configuration, catalogue
):
    observations, _ = generate(tmp_path, configuration, catalogue)
    known = datetime.fromisoformat("2025-09-06T08:00:00+08:00")
    for i, name in enumerate(("warmup", "train", "validation", "test"), 1):
        targets = load_partition_targets(observations, partition=name, known_at=known)
        assert [o.service_date for o in targets] == [date(2025, 9, i)]
        assert set(targets[0].portions) == {d.id for d in catalogue.menu_items}
    inputs = load_forecast_inputs(observations, issue_time=known)
    forecasts = seasonal_baseline(
        inputs.history,
        catalogue.menu_items,
        issue_time=known,
        target_date=date(2025, 9, 7),
    )
    assert all(x.expected_portions is None for x in forecasts.values())
    assert all(
        x.eligible_days == 3 for x in forecasts.values()
    )  # Day-wide promo exclusion.
    assert (
        load_partition_targets(
            observations,
            partition="test",
            known_at=datetime.fromisoformat("2025-09-03T22:00:00+08:00"),
        )
        == ()
    )
    with pytest.raises(ValueError):
        partition_for(
            date(2025, 8, 31), HistoryConfig.model_validate(configuration).partitions
        )


def test_isolated_censor_fixture_excluded_without_claiming_physical_simulation(
    tmp_path, configuration, catalogue
):
    observations, _ = generate(tmp_path, configuration, catalogue)
    rows = read_csv(observations / "daily_sales.csv", SALES_FIELDS)
    for row in rows:
        if row["service_date"] == "2025-09-03":
            row["censored"] = (
                "true"  # Isolated eligibility fixture, no invented stock cap.
            )
    write_csv(observations / "daily_sales.csv", SALES_FIELDS, rows)
    refresh_public(observations)
    issue = datetime.fromisoformat("2025-09-06T08:00:00+08:00")
    inputs = load_forecast_inputs(observations, issue_time=issue)
    forecasts = seasonal_baseline(
        inputs.history,
        catalogue.menu_items,
        issue_time=issue,
        target_date=date(2025, 9, 7),
    )
    assert all(x.eligible_days == 2 for x in forecasts.values())


def test_truth_is_not_required_or_exposed_by_forecast_loader(
    tmp_path, configuration, catalogue
):
    observations, evaluator = generate(tmp_path, configuration, catalogue)
    # Corrupt evaluator data; the observation loader must never open it.
    (evaluator / "attempted_demand.csv").write_text("INACCESSIBLE EVALUATOR TRUTH")
    snapshot = load_forecast_inputs(
        observations, issue_time=datetime.fromisoformat("2025-09-06T08:00:00+08:00")
    )
    assert {f.name for f in fields(snapshot)} == {
        "history",
        "promotions",
        "catalogue_sha256",
        "recipe_sha256",
    }
    manifest = json.loads((observations / "manifest.json").read_bytes())
    assert (
        not {"seeds", "assumptions", "dishes", "weekday_factors", "daily_trend"}
        & manifest.keys()
    )
    with pytest.raises(ValueError):
        load_forecast_inputs(
            evaluator, issue_time=datetime.fromisoformat("2025-09-06T08:00:00+08:00")
        )


@pytest.mark.parametrize(
    "change",
    [
        "missing_row",
        "negative",
        "nan",
        "unit",
        "unknown_dish",
        "partial_missing",
        "bad_pair",
        "revenue",
        "naive",
        "early",
        "duplicate",
        "revision_clock",
        "batch_overlap",
        "truth_column",
        "flag",
        "promotional_context",
    ],
)
def test_semantic_corruption_even_after_rehash(
    tmp_path, configuration, catalogue, change
):
    observations, _ = generate(tmp_path, configuration, catalogue)
    daily_path = observations / "daily_sales.csv"
    rows = read_csv(daily_path, SALES_FIELDS)
    row = rows[0]
    if change == "missing_row":
        rows.pop()
    elif change == "negative":
        row["served"] = "-1"
    elif change == "nan":
        row["revenue_sgd"] = "NaN"
    elif change == "unknown_dish":
        row["dish_id"] = "D1"
    elif change == "partial_missing":
        row["observed"] = "false"
    elif change == "bad_pair":
        row["free"] = "1"
    elif change == "revenue":
        row["revenue_sgd"] = "0.01"
    elif change == "naive":
        row["available_at"] = "2025-09-01T22:00:00"
    elif change == "early":
        row["available_at"] = "2025-09-01T08:00:00+08:00"
    elif change == "duplicate":
        rows.append(dict(row))
    elif change == "revision_clock":
        for r in rows:
            if r["revision"] == "2":
                r["available_at"] = r["effective_at"]
    elif change == "flag":
        row["censored"] = ""
    elif change == "promotional_context":
        write_csv(observations / "promotions.csv", PROMOTION_FIELDS, [])
    elif change == "unit":
        path = observations / "catalogue.json"
        content = json.loads(path.read_bytes())
        content["ingredients"][0]["unit"] = "grams"
        path.write_bytes(canonical_json(content))
    elif change == "batch_overlap":
        path = observations / "sales_batches.csv"
        content = read_csv(path, SALES_FIELDS)
        content[0]["effective_at"] = content[1]["effective_at"]
        write_csv(path, SALES_FIELDS, content)
    write_csv(daily_path, SALES_FIELDS, rows)
    if change == "truth_column":
        daily_path.write_text(
            daily_path.read_text().replace(
                "id,service_date", "attempted_demand,service_date", 1
            )
        )
    refresh_public(observations)
    with pytest.raises(ValueError):
        validate_observations(observations)


@pytest.mark.parametrize(
    "change", ["truth", "usage", "partition", "hash", "manifest_seed", "manifest_path"]
)
def test_evaluator_integrity_and_accounting(tmp_path, configuration, catalogue, change):
    observations, evaluator = generate(tmp_path, configuration, catalogue)
    if change in ("truth", "partition"):
        path = evaluator / "attempted_demand.csv"
        rows = read_csv(path, TRUTH_FIELDS)
        rows[0]["unmet" if change == "truth" else "partition"] = (
            "1" if change == "truth" else "test"
        )
        write_csv(path, TRUTH_FIELDS, rows)
    elif change == "usage":
        path = evaluator / "ingredient_usage.csv"
        rows = read_csv(path, USAGE_FIELDS)
        rows[0]["quantity"] = "99.99"
        write_csv(path, USAGE_FIELDS, rows)
    elif change == "hash":
        (observations / "daily_sales.csv").write_text("corrupt")
    else:
        path = evaluator / "manifest.json"
        content = json.loads(path.read_bytes())
        if change == "manifest_seed":
            content["seeds"]["demand"] += 1
        else:
            content["files"]["../secret"] = "0" * 64
        path.write_bytes(canonical_json(content))
    if change in ("truth", "usage", "partition"):
        refresh_private(observations, evaluator)
    with pytest.raises(ValueError):
        validate_dataset(observations=observations, evaluator=evaluator)


@pytest.mark.parametrize(
    "key,value",
    [
        ("timezone", "UTC"),
        ("daily_trend", "NaN"),
        ("variation_transactions", -1),
        ("missing_basis_points", 10001),
        ("reporting_error_transactions", True),
        ("history_end", "2025-08-31"),
        ("simulation_start", "2025-09-02T08:00:00+08:00"),
        ("catalogue_sha256", "0" * 64),
        ("recipe_sha256", ""),
        ("weekday_factors", ["1"] * 6),
        ("correction_delay_days", 0),
        ("purpose", "APPROVED_TRAINING_DATA"),
        ("hidden_true_demand", 10),
    ],
)
def test_malformed_configuration(tmp_path, configuration, catalogue, key, value):
    configuration[key] = value
    with pytest.raises(ValueError):
        generate(tmp_path, configuration, catalogue)


@pytest.mark.parametrize(
    "change",
    [
        "gap",
        "overlap",
        "namespace",
        "dish",
        "price",
        "weight",
        "service_overlap",
        "service_timezone",
        "naive_publication",
        "recipe",
    ],
)
def test_config_catalogue_profile_and_partition_validation(
    tmp_path, configuration, catalogue, change
):
    if change == "gap":
        configuration["partitions"][1]["start"] = "2025-09-03"
    elif change == "overlap":
        configuration["partitions"][1]["start"] = "2025-09-01"
    elif change == "namespace":
        configuration["history_namespace"] = configuration["heldout_scenario_namespace"]
    elif change == "dish":
        configuration["dishes"][0]["dish_id"] = "D1"
    elif change == "price":
        configuration["dishes"][0]["unit_price_sgd"] = "-1"
    elif change == "weight":
        configuration["profile"][0]["weight"] = "0.5"
    elif change == "service_overlap":
        configuration["profile"][1]["start"] = "13:00:00"
    elif change == "service_timezone":
        configuration["profile"][0]["start"] = "11:00:00+00:00"
    elif change == "naive_publication":
        configuration["promotions"][0]["publication_date"] = "2025-09-02"
    else:
        raw = catalogue.model_dump(mode="json")
        raw["recipes"][0]["quantity"] = "999"
        catalogue = Catalogue.model_validate(raw)
    with pytest.raises(ValueError):
        generate(tmp_path, configuration, catalogue)


def test_output_boundaries_and_no_overwrite(tmp_path, configuration, catalogue):
    config = HistoryConfig.model_validate(configuration)
    with pytest.raises(ValueError):
        generate_history(
            config,
            catalogue,
            observations=tmp_path / "same",
            evaluator=tmp_path / "same" / "truth",
        )
    repo = Path(__file__).resolve().parents[3]
    with pytest.raises(ValueError):
        generate_history(
            config,
            catalogue,
            observations=repo / "runtime-data",
            evaluator=tmp_path / "truth",
        )
    observations, _ = generate(tmp_path, configuration, catalogue)
    original = (observations / "manifest.json").read_bytes()
    with pytest.raises(ValueError):
        generate(tmp_path, configuration, catalogue)
    assert (observations / "manifest.json").read_bytes() == original


def test_catalogue_recipes_match_seed_without_importing_or_running_database(catalogue):
    # Read literal source only. A seed refactor fails explicitly instead of silently
    # treating a copied ML catalogue as canonical or executing a database seed.
    tree = ast.parse((Path(__file__).parents[1] / "src" / "seed.py").read_text())
    assignments = {
        target.id: node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    dishes = ast.literal_eval(assignments["dishes"])
    assert set(dishes) == {(d.id, d.name) for d in catalogue.menu_items}
    recipes = ast.literal_eval(assignments["recipe_data"])
    assert {
        (dish, ingredient): Decimal(quantity)
        for dish, items in recipes.items()
        for ingredient, quantity in items.items()
    } == {(r.menu_item_id, r.ingredient_id): r.quantity for r in catalogue.recipes}
    ingredient_list = assignments["ingredient_seeds"]
    assert isinstance(ingredient_list, ast.List)
    seed_ingredients = set()
    for item in ingredient_list.elts:
        assert isinstance(item, ast.Call)
        seed_ingredients.add(
            tuple(ast.literal_eval(item.args[i]) for i in (0, 1, 2, 4))
        )
    assert seed_ingredients == {
        (i.id, i.name, i.unit, i.interval_days) for i in catalogue.ingredients
    }


def test_declared_development_configuration_and_partition_counts(tmp_path, catalogue):
    raw = json.loads((FIXTURES / "history_development_v1.json").read_bytes())
    observations, evaluator = generate(tmp_path, raw, catalogue)
    assert validate_dataset(observations=observations, evaluator=evaluator) == {
        "daily_rows": 840,
        "batch_rows": 5880,
        "promotion_rows": 2,
        "target_days": 84,
        "truth_rows": 420,
        "ingredient_rows": 672,
    }
    known = datetime.fromisoformat("2025-11-25T08:00:00+08:00")
    assert [
        len(load_partition_targets(observations, partition=name, known_at=known))
        for name in ("warmup", "train", "validation", "test")
    ] == [28, 28, 14, 14]


@pytest.mark.parametrize("profile_change", ["lunch_only", "shifted"])
def test_offline_validation_rejects_configured_service_interval_mismatch(
    tmp_path, catalogue, profile_change
):
    raw = json.loads((FIXTURES / "history_development_v1.json").read_bytes())
    observations, evaluator = generate(tmp_path, raw, catalogue)
    original_observations = {p.name: p.read_bytes() for p in observations.iterdir()}
    path = evaluator / "configuration.json"
    configuration = json.loads(path.read_bytes())
    if profile_change == "lunch_only":
        configuration["profile"] = [
            {"start": "11:00:00", "end": "14:00:00", "weight": "1"}
        ]
    else:
        # Still fourteen half-hours, but the six lunch intervals are shifted.
        configuration["profile"][0].update(start="10:30:00", end="13:30:00")
    path.write_bytes(canonical_json(configuration))
    refresh_private(observations, evaluator)
    manifest = json.loads((evaluator / "manifest.json").read_bytes())
    assert manifest["files"]["configuration.json"] == sha256(path.read_bytes())
    assert {
        p.name: p.read_bytes() for p in observations.iterdir()
    } == original_observations
    # The configuration is independently valid; only its cross-file meaning is wrong.
    HistoryConfig.model_validate(configuration).check_catalogue(catalogue)
    with pytest.raises(
        ValueError,
        match="Configured service intervals differ from observation manifest",
    ):
        validate_dataset(observations=observations, evaluator=evaluator)


@pytest.mark.parametrize("profile_change", ["reordered", "weights_only"])
def test_offline_validation_accepts_equivalent_service_intervals(
    tmp_path, configuration, catalogue, profile_change
):
    observations, evaluator = generate(tmp_path, configuration, catalogue)
    path = evaluator / "configuration.json"
    raw = json.loads(path.read_bytes())
    if profile_change == "reordered":
        raw["profile"].reverse()
    else:
        # Sampling does not promise exact observed proportions or prove RNG provenance.
        for period in raw["profile"]:
            period["weight"] = "0.5"
    path.write_bytes(canonical_json(raw))
    refresh_private(observations, evaluator)
    assert validate_dataset(observations=observations, evaluator=evaluator) == {
        "daily_rows": 40,
        "batch_rows": 280,
        "promotion_rows": 1,
        "target_days": 4,
        "truth_rows": 20,
        "ingredient_rows": 32,
    }


def test_weekday_and_mild_trend_independent_expected_values(
    tmp_path, configuration, catalogue
):
    configuration.update(
        promotions=[],
        weekday_factors=["1", "2", "0.5", "1", "1", "1", "1"],
        daily_trend="0.01",
    )
    for dish in configuration["dishes"]:
        dish["base_transactions"] = "10" if dish["dish_id"] == "chicken-rice" else "0"
    _, evaluator = generate(tmp_path, configuration, catalogue)
    values = [
        int(r["attempted_transactions"])
        for r in read_csv(evaluator / "attempted_demand.csv", TRUTH_FIELDS)
        if r["dish_id"] == "chicken-rice"
    ]
    # 10*1*1; 10*2*1.01; 10*.5*1.02; 10*1*1.03, rounded half-even.
    assert values == [10, 20, 5, 10]


@pytest.mark.parametrize(
    "change", ["report_error", "censor", "price", "recorded_clock"]
)
def test_declared_fully_supplied_semantics_cannot_be_forged_by_rehash(
    tmp_path, configuration, catalogue, change
):
    observations, evaluator = generate(tmp_path, configuration, catalogue)
    rows = read_csv(observations / "daily_sales.csv", SALES_FIELDS)
    if change == "report_error":
        row = next(
            r
            for r in rows
            if r["revision"] == "1"
            and r["service_date"] == "2025-09-01"
            and r["dish_id"] == "chicken-rice"
        )
        row.update(served="4", paid="4", transactions="4", revenue_sgd="9.40")
    elif change == "censor":
        rows[0]["censored"] = "true"
    elif change == "price":
        # Zero sales allow a coherent but falsely declared price to evade revenue identities.
        row = next(r for r in rows if r["served"] == "0")
        row["unit_price_sgd"] = "99"
    else:
        for row in rows:
            if row["revision"] == "2":
                row["available_at"] = row["available_at"].replace(
                    "T22:00:00", "T23:00:00"
                )
    write_csv(observations / "daily_sales.csv", SALES_FIELDS, rows)
    refresh_public(observations)
    refresh_private(observations, evaluator)
    # Refresh the private copy of public metadata to exercise deeper semantics.
    path = evaluator / "manifest.json"
    private = json.loads(path.read_bytes())
    public = json.loads((observations / "manifest.json").read_bytes())
    private.update({k: v for k, v in public.items() if k != "files"})
    path.write_bytes(canonical_json(private))
    with pytest.raises(ValueError):
        validate_dataset(observations=observations, evaluator=evaluator)


def test_decimal_configuration_rejects_float(tmp_path, configuration, catalogue):
    configuration["dishes"][0]["unit_price_sgd"] = 2.35
    with pytest.raises(ValueError, match="binary floating"):
        generate(tmp_path, configuration, catalogue)
