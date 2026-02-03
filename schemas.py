from pydantic import BaseModel

class MessageCreate(BaseModel):
    text: str
    autor: str

class MessageRead(BaseModel):
    id: int
    text: str
    autor: str

    class Config:
        from_attributes = True


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