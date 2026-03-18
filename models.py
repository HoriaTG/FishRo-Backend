from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from db import Base


class ProductDB(Base):
    __tablename__ = "products"

    code = Column(String, unique=True, index=True, nullable=False)
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    category = Column(String, nullable=False)
    price = Column(Float, nullable=False)
    quantity = Column(Integer, nullable=False, default=0)
    description = Column(String, nullable=True)
    tech_details = Column(String, nullable=True)
    video_url = Column(String, nullable=True)


class UserDB(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, nullable=False, default="user")


class OrderDB(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    order_number = Column(String, unique=True, index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    total = Column(Float, nullable=False, default=0)
    created_at = Column(DateTime, nullable=True)

    user = relationship("UserDB")
    items = relationship("OrderItemDB", back_populates="order")
    

class OrderItemDB(Base):
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)

    product_name = Column(String, nullable=False)
    product_code = Column(String, nullable=False)
    unit_price = Column(Float, nullable=False)
    quantity = Column(Integer, nullable=False)
    line_total = Column(Float, nullable=False)

    order = relationship("OrderDB", back_populates="items")


class CartItemDB(Base):
    __tablename__ = "cart_items"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    quantity = Column(Integer, nullable=False, default=1)

    user = relationship("UserDB")
    product = relationship("ProductDB")