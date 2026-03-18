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

TicketCategory = Literal[
    "comanda",
    "produs",
    "plata",
    "livrare",
    "alta",
]

TicketStatus = Literal["open", "closed"]


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


class CartItemAdd(BaseModel):
    product_id: int
    quantity: int = 1


class CartItemUpdate(BaseModel):
    quantity: int


class CartItemRead(BaseModel):
    id: int
    product_id: int
    product_name: str
    product_code: str
    unit_price: float
    quantity: int
    stock: int
    image_url: str | None = None
    unavailable: bool

    class Config:
        from_attributes = True


class CartRead(BaseModel):
    items: list[CartItemRead]
    total: float


class TicketCreate(BaseModel):
    category: TicketCategory
    message: str = Field(..., min_length=1)


class TicketMessageCreate(BaseModel):
    message: str = Field(..., min_length=1)


class TicketMessageRead(BaseModel):
    id: int
    ticket_id: int
    sender_id: int
    sender_username: str
    sender_role: str
    message: str
    created_at: datetime | None = None


class TicketListRead(BaseModel):
    id: int
    ticket_number: str
    user_id: int
    username: str
    category: str
    status: TicketStatus
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_message_at: datetime | None = None
    has_unread: bool = False


class TicketDetailRead(BaseModel):
    id: int
    ticket_number: str
    user_id: int
    username: str
    category: str
    status: TicketStatus
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_message_at: datetime | None = None
    messages: list[TicketMessageRead]


class TicketUnreadCountRead(BaseModel):
    count: int