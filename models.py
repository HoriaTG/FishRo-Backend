from sqlalchemy import Column, Integer, String, Float
from db import Base

class ProductDB(Base):
    __tablename__ = "products"

    code = Column(String, unique=True, index=True, nullable=False)  # cod unic (numeric, dar îl ținem ca string)
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    category = Column(String, nullable=False)
    price = Column(Float, nullable=False)
    quantity = Column(Integer, nullable=False, default=0)  # default 0


class UserDB(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, nullable=False, default="user")  # user / moderator / admin