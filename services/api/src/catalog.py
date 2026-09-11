from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy import select

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


@router.get("/menu-items", response_model=list[MenuItem])
def menu_items(session: SessionDep):
    return (
        session.execute(select(db.menu_items).order_by(db.menu_items.c.id))
        .mappings()
        .all()
    )


@router.get("/ingredients", response_model=list[Ingredient])
def ingredients(session: SessionDep):
    return (
        session.execute(select(db.ingredients).order_by(db.ingredients.c.id))
        .mappings()
        .all()
    )


@router.get("/recipes", response_model=list[RecipeItem])
def recipes(session: SessionDep):
    return (
        session.execute(
            select(db.recipes).order_by(
                db.recipes.c.menu_item_id, db.recipes.c.ingredient_id
            )
        )
        .mappings()
        .all()
    )


@router.get("/suppliers", response_model=list[Supplier])
def suppliers(session: SessionDep):
    return (
        session.execute(select(db.suppliers).order_by(db.suppliers.c.id))
        .mappings()
        .all()
    )


@router.get("/supplier-offers", response_model=list[SupplierOffer])
def supplier_offers(session: SessionDep):
    return (
        session.execute(select(db.supplier_offers).order_by(db.supplier_offers.c.id))
        .mappings()
        .all()
    )


@router.get("/holidays", response_model=list[Holiday])
def holidays(session: SessionDep):
    return (
        session.execute(select(db.holidays).order_by(db.holidays.c.date))
        .mappings()
        .all()
    )


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
