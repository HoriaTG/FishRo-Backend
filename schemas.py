from pydantic import BaseModel, EmailStr, Field


class ProductCreate(BaseModel):
    code: str = Field(..., min_length=1)   # îl validăm ca string
    name: str
    category: str
    price: float
    quantity: int = 0  # default

class ProductRead(BaseModel):
    id: int
    code: str
    name: str
    category: str
    price: float
    quantity: int

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
