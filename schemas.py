from pydantic import BaseModel, EmailStr, Field
from typing import Optional, Literal

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