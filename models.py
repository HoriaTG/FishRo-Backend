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
    promotion = Column(Integer, nullable=False, default=0)
    description = Column(String, nullable=True)
    tech_details = Column(String, nullable=True)
    video_url = Column(String, nullable=True)

    reviews = relationship(
        "ReviewDB",
        back_populates="product",
        cascade="all, delete-orphan",
        order_by="ReviewDB.updated_at.desc()",
    )


class UserDB(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, nullable=False, default="user")
    staff_notifications_start_at = Column(DateTime, nullable=True)

    reviews = relationship("ReviewDB", back_populates="user")


class OrderDB(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    order_number = Column(String, unique=True, index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    total = Column(Float, nullable=False, default=0)
    created_at = Column(DateTime, nullable=True)
    status = Column(String, nullable=False, default="trimisa")

    first_name = Column(String, nullable=False)
    last_name = Column(String, nullable=False)
    address = Column(String, nullable=False)
    phone = Column(String, nullable=False)
    email = Column(String, nullable=False)
    payment_method = Column(String, nullable=False)

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


class ReviewDB(Base):
    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    rating = Column(Integer, nullable=False)
    comment = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=True)

    product = relationship("ProductDB", back_populates="reviews")
    user = relationship("UserDB", back_populates="reviews")


class TicketDB(Base):
    __tablename__ = "tickets"

    id = Column(Integer, primary_key=True, index=True)
    ticket_number = Column(String, unique=True, index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    category = Column(String, nullable=False)
    status = Column(String, nullable=False, default="open")
    created_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=True)
    last_message_at = Column(DateTime, nullable=True)
    assigned_to_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    staff_last_read_message_id = Column(Integer, nullable=True)

    user = relationship("UserDB", foreign_keys=[user_id])
    assigned_to_user = relationship("UserDB", foreign_keys=[assigned_to_user_id])

    messages = relationship(
        "TicketMessageDB",
        back_populates="ticket",
        cascade="all, delete-orphan",
        order_by="TicketMessageDB.created_at",
    )
    read_states = relationship(
        "TicketReadStateDB",
        back_populates="ticket",
        cascade="all, delete-orphan",
    )


class TicketMessageDB(Base):
    __tablename__ = "ticket_messages"

    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=False, index=True)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    message = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=True)

    ticket = relationship("TicketDB", back_populates="messages")
    sender = relationship("UserDB")


class TicketReadStateDB(Base):
    __tablename__ = "ticket_read_states"

    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    last_read_message_id = Column(Integer, nullable=True)

    ticket = relationship("TicketDB", back_populates="read_states")
    user = relationship("UserDB")