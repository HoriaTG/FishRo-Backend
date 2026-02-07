from pydantic import BaseModel, EmailStr


class ProductCreate(BaseModel):
    name: str
    category: str
    price: float

class ProductRead(BaseModel):
    id: int
    name: str
    category: str
    price: float

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
