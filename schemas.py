from pydantic import BaseModel, EmailStr, Field
from typing import Optional, Literal
from datetime import datetime


ProductCategory = Literal[
    "undita",
    "lanseta",
    "mulineta",
    "carlig",
    "plumb",
    "nailon",
    "echipamente",
    "momeli",
    "diverse",
    "nada",
    "plute",
]


class ProductCreate(BaseModel):
    code: str = Field(..., min_length=1)
    name: str
    category: ProductCategory
    price: float
    quantity: int = 0
    description: str | None = None
    tech_details: str | None = None
    video_url: str | None = None


class ProductRead(BaseModel):
    id: int
    code: str
    name: str
    category: ProductCategory
    price: float
    quantity: int
    description: str | None = None
    tech_details: str | None = None
    video_url: str | None = None

    class Config:
        from_attributes = True


class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str


class UserRead(BaseModel):
    id: int
    username: str
    email: EmailStr
    role: str

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[ProductCategory] = None
    price: Optional[float] = None
    quantity: Optional[int] = None
    description: Optional[str] = None
    tech_details: Optional[str] = None
    video_url: Optional[str] = None


class OrderCreateItem(BaseModel):
    product_id: int
    quantity: int


class OrderCreate(BaseModel):
    items: list[OrderCreateItem]


class OrderItemRead(BaseModel):
    id: int
    product_id: int
    product_name: str
    product_code: str
    unit_price: float
    quantity: int
    line_total: float

    class Config:
        from_attributes = True


class OrderRead(BaseModel):
    id: int
    order_number: str
    user_id: int
    total: float
    created_at: datetime | None = None
    user: UserRead | None = None
    items: list[OrderItemRead]

    class Config:
        from_attributes = True