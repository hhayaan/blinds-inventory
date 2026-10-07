"""Input contracts shared by the HTTP routes and inventory operations."""

from decimal import Decimal, InvalidOperation
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator, model_validator


MAX_QUANTITY = 1_000_000_000
METADATA_FIELDS = (
    "name", "description", "category", "brand", "model", "color", "material",
    "width", "height", "dimension_unit", "location", "price",
)
TEXT_FIELDS = ("description", "category", "brand", "model", "color", "material", "location")


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @field_validator("*", mode="before", check_fields=False)
    @classmethod
    def normalize_optional_text(cls, value, info):
        if info.field_name in TEXT_FIELDS and value is None:
            return ""
        if info.field_name == "price" and value == "":
            return None
        if info.field_name in ("width", "height") and isinstance(value, bool):
            raise ValueError("Dimensions must be numbers, not true/false")
        return value

    @field_validator("price", check_fields=False)
    @classmethod
    def validate_price(cls, value):
        if value is None:
            return value
        try:
            amount = Decimal(value)
        except InvalidOperation as error:
            raise ValueError("Price must be a decimal amount") from error
        if not amount.is_finite() or amount < 0 or amount > Decimal("99999999.99"):
            raise ValueError("Price must be between 0 and 99999999.99")
        if amount.as_tuple().exponent < -2:
            raise ValueError("Price may have at most two decimal places")
        return format(amount, ".2f")


class ProductCreate(InputModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2000)
    category: str = Field(default="", max_length=100)
    brand: str = Field(default="", max_length=100)
    model: str = Field(default="", max_length=100)
    color: str = Field(default="", max_length=100)
    material: str = Field(default="", max_length=100)
    width: float | None = Field(default=None, gt=0, le=1_000_000, allow_inf_nan=False)
    height: float | None = Field(default=None, gt=0, le=1_000_000, allow_inf_nan=False)
    dimension_unit: Literal["in", "cm", "mm"] = "in"
    location: str = Field(default="", max_length=160)
    price: str | None = Field(default=None, max_length=32)


class ProductPatch(InputModel):
    revision: StrictInt = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    category: str | None = Field(default=None, max_length=100)
    brand: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, max_length=100)
    color: str | None = Field(default=None, max_length=100)
    material: str | None = Field(default=None, max_length=100)
    width: float | None = Field(default=None, gt=0, le=1_000_000, allow_inf_nan=False)
    height: float | None = Field(default=None, gt=0, le=1_000_000, allow_inf_nan=False)
    dimension_unit: Literal["in", "cm", "mm"] | None = None
    location: str | None = Field(default=None, max_length=160)
    price: str | None = Field(default=None, max_length=32)

    @model_validator(mode="after")
    def require_editable_fields(self):
        fields = self.model_fields_set - {"revision"}
        if not fields:
            raise ValueError("Supply at least one product field to edit")
        if "name" in fields and self.name is None:
            raise ValueError("Product name cannot be null")
        if "dimension_unit" in fields and self.dimension_unit is None:
            raise ValueError("Measurement unit cannot be null")
        return self


class ArchiveRequest(InputModel):
    revision: StrictInt = Field(ge=1)
    archived: StrictBool


class StockRequest(InputModel):
    barcode: str = Field(min_length=1, max_length=80)
    kind: Literal["receipt", "sale", "return", "correction"]
    request_id: UUID
    revision: StrictInt | None = Field(default=None, ge=1)
    # Keep omitted quantities as null in saved request payloads so retries of
    # previously accepted one-item scans still match their persisted operation.
    quantity: StrictInt | None = Field(default=None, ge=0, le=MAX_QUANTITY)
    reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_operation(self):
        if self.kind == "correction":
            if self.quantity is None or self.revision is None:
                raise ValueError("A correction needs a target quantity and current revision")
            if not self.reason:
                raise ValueError("A correction needs a reason")
        elif self.quantity is not None and self.quantity < 1:
            raise ValueError("Stock quantity must be a positive whole number")
        return self

