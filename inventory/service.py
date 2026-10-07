"""Inventory rules: atomic writes, revision checks, and scan retry handling."""

import json
from decimal import Decimal

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .database import Movement, Operation, Product, utc_now
from .schemas import MAX_QUANTITY, METADATA_FIELDS, ArchiveRequest, ProductCreate, ProductPatch, StockRequest


def product_dict(product: Product) -> dict:
    result = {field: getattr(product, field) for field in METADATA_FIELDS if field != "price"}
    result.update(
        id=product.id,
        barcode=product.barcode,
        price=None if product.price_cents is None else format(Decimal(product.price_cents) / 100, ".2f"),
        quantity=product.quantity,
        revision=product.revision,
        archived=product.archived,
        created_at=product.created_at,
        updated_at=product.updated_at,
    )
    return result


def movement_dict(movement: Movement, product: Product) -> dict:
    return {
        "id": movement.id,
        "product_id": movement.product_id,
        "kind": movement.kind,
        "delta": movement.delta,
        "quantity_after": movement.quantity_after,
        "reason": movement.reason,
        "request_id": movement.request_id,
        "created_at": movement.created_at,
        "product_name": product.name,
        "barcode": product.barcode,
    }


def require_product(session: Session, product_id: int) -> Product:
    product = session.get(Product, product_id)
    if product is None:
        raise HTTPException(404, "Product not found")
    return product


def require_revision(product: Product, revision: int):
    if product.revision != revision:
        raise HTTPException(409, {
            "message": "This product changed since it was opened. Refresh it before saving.",
            "current_product": product_dict(product),
        })


def set_metadata(product: Product, fields: ProductCreate):
    for field in METADATA_FIELDS:
        if field != "price":
            setattr(product, field, getattr(fields, field))
    product.price_cents = None if fields.price is None else int(Decimal(fields.price) * 100)


class InventoryService:
    def __init__(self, engine):
        self.engine = engine

    def list_products(self, include_archived: bool) -> list[dict]:
        with Session(self.engine) as session:
            query = select(Product).order_by(Product.id)
            if not include_archived:
                query = query.where(Product.archived.is_(False))
            return [product_dict(product) for product in session.scalars(query)]

    def get_product(self, product_id: int) -> dict:
        with Session(self.engine) as session:
            return product_dict(require_product(session, product_id))

    def create_product(self, fields: ProductCreate) -> dict:
        with Session(self.engine) as session:
            session.execute(text("BEGIN IMMEDIATE"))
            # The temporary barcode exists only inside this transaction. It is
            # replaced with the stable ID before the new product is committed.
            product = Product(barcode="pending")
            set_metadata(product, fields)
            session.add(product)
            session.flush()
            product.barcode = f"BL-{product.id:06d}"
            session.flush()
            result = product_dict(product)
            session.commit()
            return result

    def patch_product(self, product_id: int, change: ProductPatch) -> dict:
        with Session(self.engine) as session:
            session.execute(text("BEGIN IMMEDIATE"))
            product = require_product(session, product_id)
            require_revision(product, change.revision)
            combined = {key: value for key, value in product_dict(product).items() if key in METADATA_FIELDS}
            combined.update(change.model_dump(exclude_unset=True, exclude={"revision"}))
            try:
                fields = ProductCreate.model_validate(combined)
            except ValidationError as error:
                raise HTTPException(422, [
                    {"loc": ["body", *item["loc"]], "msg": item["msg"], "type": item["type"]}
                    for item in error.errors()
                ]) from error
            set_metadata(product, fields)
            product.revision += 1
            product.updated_at = utc_now()
            session.flush()
            result = product_dict(product)
            session.commit()
            return result

    def archive_product(self, product_id: int, change: ArchiveRequest) -> dict:
        with Session(self.engine) as session:
            session.execute(text("BEGIN IMMEDIATE"))
            product = require_product(session, product_id)
            require_revision(product, change.revision)
            if change.archived and product.quantity != 0:
                raise HTTPException(409, "Only a product with zero stock can be archived")
            if product.archived != change.archived:
                product.archived = change.archived
                product.revision += 1
                product.updated_at = utc_now()
                session.flush()
            result = product_dict(product)
            session.commit()
            return result

    def apply_stock(self, request: StockRequest) -> dict:
        request_id = str(request.request_id)
        payload = json.dumps(request.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        with Session(self.engine) as session:
            # SQLite's write lock is acquired before either the stock or the
            # operation ID is read. Competing sales cannot oversell stock.
            session.execute(text("BEGIN IMMEDIATE"))
            previous = session.get(Operation, request_id)
            if previous is not None:
                if previous.payload_json != payload:
                    raise HTTPException(409, "This request ID was already used for a different stock operation")
                result = json.loads(previous.response_json)
                result["replayed"] = True
                session.rollback()
                return result

            product = session.scalar(select(Product).where(Product.barcode == request.barcode))
            if product is None:
                raise HTTPException(404, "Barcode not found. Create or select its product first.")
            if product.archived:
                raise HTTPException(409, "This product is archived. Restore it before changing stock.")
            if request.kind == "correction":
                require_revision(product, request.revision)
                delta = request.quantity - product.quantity
            else:
                quantity = 1 if request.quantity is None else request.quantity
                delta = -quantity if request.kind == "sale" else quantity
            new_quantity = product.quantity + delta
            if new_quantity < 0:
                raise HTTPException(409, "Not enough in stock.")
            if new_quantity > MAX_QUANTITY:
                raise HTTPException(409, "The inventory quantity limit has been reached")

            product.quantity = new_quantity
            product.revision += 1
            product.updated_at = utc_now()
            movement = Movement(
                product_id=product.id,
                kind=request.kind,
                delta=delta,
                quantity_after=new_quantity,
                reason=request.reason,
                request_id=request_id,
            )
            session.add(movement)
            session.flush()
            result = {"product": product_dict(product), "movement": movement_dict(movement, product), "replayed": False}
            session.add(Operation(
                request_id=request_id,
                payload_json=payload,
                response_json=json.dumps(result, sort_keys=True, separators=(",", ":")),
            ))
            session.commit()
            return result

    def list_movements(self, product_id: int | None) -> list[dict]:
        with Session(self.engine) as session:
            if product_id is not None:
                require_product(session, product_id)
            query = select(Movement, Product).join(Product).order_by(Movement.id.desc())
            if product_id is not None:
                query = query.where(Movement.product_id == product_id)
            return [movement_dict(movement, product) for movement, product in session.execute(query)]

