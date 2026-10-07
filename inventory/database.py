"""SQLite persistence for products, their movements, and operation retries."""

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, Text, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Base(DeclarativeBase):
    pass


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("quantity >= 0", name="product_nonnegative_quantity"),
        CheckConstraint("revision >= 1", name="product_positive_revision"),
        CheckConstraint("price_cents IS NULL OR price_cents >= 0", name="product_nonnegative_price"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    barcode: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(100), default="")
    brand: Mapped[str] = mapped_column(String(100), default="")
    model: Mapped[str] = mapped_column(String(100), default="")
    color: Mapped[str] = mapped_column(String(100), default="")
    material: Mapped[str] = mapped_column(String(100), default="")
    # Dimensions are optional display attributes, not quantities or monetary values.
    width: Mapped[float | None] = mapped_column(nullable=True)
    height: Mapped[float | None] = mapped_column(nullable=True)
    dimension_unit: Mapped[str] = mapped_column(String(2), default="in")
    location: Mapped[str] = mapped_column(String(160), default="")
    price_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    archived: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[str] = mapped_column(String(30), default=utc_now)
    updated_at: Mapped[str] = mapped_column(String(30), default=utc_now)


class Movement(Base):
    __tablename__ = "stock_movements"
    __table_args__ = (
        CheckConstraint("quantity_after >= 0", name="movement_nonnegative_quantity"),
        CheckConstraint("kind IN ('receipt', 'sale', 'return', 'correction')", name="movement_kind"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    kind: Mapped[str] = mapped_column(String(12))
    delta: Mapped[int] = mapped_column(Integer)
    quantity_after: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    request_id: Mapped[str] = mapped_column(String(36), unique=True)
    created_at: Mapped[str] = mapped_column(String(30), default=utc_now)


class Operation(Base):
    """Persist the exact acknowledged result so a network retry never rescans."""

    __tablename__ = "stock_operations"

    request_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    payload_json: Mapped[str] = mapped_column(Text)
    response_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(30), default=utc_now)


def open_database(db_path: Path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{db_path.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )

    @event.listens_for(engine, "connect")
    def configure_connection(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    # WAL lets the UI read while one stock write is in progress. All mutations
    # still take an immediate transaction, including metadata and archival.
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA journal_mode=WAL")
        connection.commit()
    Base.metadata.create_all(engine)
    return engine

