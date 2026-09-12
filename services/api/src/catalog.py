from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy import ColumnElement, Table, select

from src import database as db
from src.auth import SessionDep, authenticate
from src.schemas import (
    Holiday,
    Ingredient,
    InventoryLot,
    MenuItem,
    RecipeItem,
    Supplier,
    SupplierOffer,
)

router = APIRouter(tags=["Catalog and inventory"], dependencies=[Depends(authenticate)])


def catalog_rows(
    session: SessionDep, table: Table, *ordering: ColumnElement[Any]
) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in session.execute(select(table).order_by(*ordering)).mappings().all()
    ]


@router.get("/menu-items", response_model=list[MenuItem])
def menu_items(session: SessionDep):
    return catalog_rows(session, db.menu_items, db.menu_items.c.id)


@router.get("/ingredients", response_model=list[Ingredient])
def ingredients(session: SessionDep):
    return catalog_rows(session, db.ingredients, db.ingredients.c.id)


@router.get("/recipes", response_model=list[RecipeItem])
def recipes(session: SessionDep):
    return catalog_rows(
        session, db.recipes, db.recipes.c.menu_item_id, db.recipes.c.ingredient_id
    )


@router.get("/suppliers", response_model=list[Supplier])
def suppliers(session: SessionDep):
    return catalog_rows(session, db.suppliers, db.suppliers.c.id)


@router.get("/supplier-offers", response_model=list[SupplierOffer])
def supplier_offers(session: SessionDep):
    return catalog_rows(session, db.supplier_offers, db.supplier_offers.c.id)


@router.get("/holidays", response_model=list[Holiday])
def holidays(session: SessionDep):
    return catalog_rows(session, db.holidays, db.holidays.c.date)


@router.get(
    "/inventory",
    response_model=list[InventoryLot],
    description="Latest stored physical observations, including historical expired lots. "
    "These quantities are not current usable or estimated stock.",
)
def inventory(session: SessionDep):
    latest = (
        select(db.stock_counts)
        .distinct(db.stock_counts.c.lot_id)
        .order_by(
            db.stock_counts.c.lot_id,
            db.stock_counts.c.counted_at.desc(),
            db.stock_counts.c.sequence.desc(),
        )
        .subquery()
    )
    query = (
        select(
            db.inventory_lots,
            db.ingredients.c.unit,
            latest.c.quantity,
            latest.c.counted_at,
        )
        .join(db.ingredients, db.inventory_lots.c.ingredient_id == db.ingredients.c.id)
        .join(latest, latest.c.lot_id == db.inventory_lots.c.id)
        .order_by(db.inventory_lots.c.id)
    )
    rows = session.execute(query).mappings().all()
    singapore = ZoneInfo("Asia/Singapore")
    return [
        {
            **row,
            "counted_at": row["counted_at"].astimezone(singapore),
            "received_at": row["received_at"].astimezone(singapore),
        }
        for row in rows
    ]
