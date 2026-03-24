from datetime import datetime, timedelta

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from auth import create_access_token, hash_password, verify_password
from db import Base, engine
from app_constants import ORDER_STATUSES, PROMOTION_VALUES, TICKET_CREATE_COOLDOWN_HOURS
from chatbot_service import get_discounted_price, handle_assistant_chat
from dependencies import (
    get_current_user,
    get_db,
    get_optional_current_user,
    require_admin,
    require_moderator_or_admin,
)
from models import (
    CartItemDB,
    OrderDB,
    OrderItemDB,
    ProductDB,
    TicketDB,
    TicketMessageDB,
    TicketReadStateDB,
    UserDB,
)
from schemas import (
    AssignableStaffRead,
    AssistantChatRequest,
    AssistantChatResponse,
    CartItemAdd,
    CartItemRead,
    CartItemUpdate,
    CartRead,
    OrderRead,
    OrderStatusUpdate,
    ProductCreate,
    ProductRead,
    ProductUpdate,
    TicketAssignPayload,
    TicketCreate,
    TicketCreateAvailabilityRead,
    TicketDetailRead,
    TicketListRead,
    TicketMessageCreate,
    TicketMessageRead,
    TicketUnreadCountRead,
    Token,
    UserCreate,
    UserLogin,
    UserRead,
)

app = FastAPI(title="Fishing App - SQLite")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:4173",
        "http://192.168.1.135:4173",
        "http://127.0.0.1:4173",
        "http://192.168.1.131:4173",
        "http://192.168.0.107:4173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Base.metadata.create_all(bind=engine)


def generate_order_number() -> str:
    return f"RO-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}"


def generate_ticket_number() -> str:
    return f"TCK-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}"


def build_cart_response(db: Session, current_user: UserDB) -> CartRead:
    cart_items = (
        db.query(CartItemDB)
        .options(joinedload(CartItemDB.product))
        .filter(CartItemDB.user_id == current_user.id)
        .all()
    )

    changed = False
    result_items = []
    total = 0.0

    for item in cart_items:
        product = item.product

        if not product or product.quantity <= 0:
            db.delete(item)
            changed = True
            continue

        if item.quantity > product.quantity:
            item.quantity = product.quantity
            changed = True

        discounted_price = get_discounted_price(product.price, getattr(product, "promotion", 0))
        line_total = discounted_price * item.quantity
        total += line_total

        result_items.append(
            CartItemRead(
                id=item.id,
                product_id=product.id,
                product_name=product.name,
                product_code=product.code,
                unit_price=discounted_price,
                quantity=item.quantity,
                stock=product.quantity,
                image_url=f"/images/products/{product.code}.jpg",
                unavailable=False,
            )
        )

    if changed:
        db.commit()

    return CartRead(items=result_items, total=total)


def can_access_ticket(ticket: TicketDB, current_user: UserDB) -> bool:
    if current_user.role in ["moderator", "admin"]:
        return True
    return ticket.user_id == current_user.id


def get_ticket_or_404(ticket_id: int, db: Session) -> TicketDB:
    ticket = (
        db.query(TicketDB)
        .options(
            joinedload(TicketDB.user),
            joinedload(TicketDB.assigned_to_user),
            joinedload(TicketDB.messages).joinedload(TicketMessageDB.sender),
        )
        .filter(TicketDB.id == ticket_id)
        .first()
    )
    if not ticket:
        raise HTTPException(status_code=404, detail="Tichetul nu exista")
    return ticket


def serialize_ticket_message(message: TicketMessageDB) -> TicketMessageRead:
    return TicketMessageRead(
        id=message.id,
        ticket_id=message.ticket_id,
        sender_id=message.sender_id,
        sender_username=message.sender.username if message.sender else "-",
        sender_role=message.sender.role if message.sender else "user",
        message=message.message,
        created_at=message.created_at,
    )


def ticket_has_unread_for_user(ticket: TicketDB, current_user: UserDB, db: Session) -> bool:
    latest_message = (
        db.query(TicketMessageDB)
        .filter(TicketMessageDB.ticket_id == ticket.id)
        .order_by(TicketMessageDB.id.desc())
        .first()
    )

    if not latest_message:
        return False

    if current_user.role in ["moderator", "admin"]:
        if latest_message.sender_id == current_user.id:
            return False

        if latest_message.sender and latest_message.sender.role in ["moderator", "admin"]:
            return False

        staff_start = current_user.staff_notifications_start_at
        if staff_start and latest_message.created_at and latest_message.created_at < staff_start:
            return False

        if ticket.staff_last_read_message_id is None:
            return True

        return ticket.staff_last_read_message_id < latest_message.id

    if latest_message.sender_id == current_user.id:
        return False

    state = (
        db.query(TicketReadStateDB)
        .filter(
            TicketReadStateDB.ticket_id == ticket.id,
            TicketReadStateDB.user_id == current_user.id,
        )
        .first()
    )

    if not state or state.last_read_message_id is None:
        return True

    return state.last_read_message_id < latest_message.id


def serialize_ticket_list(ticket: TicketDB, current_user: UserDB, db: Session) -> TicketListRead:
    assigned_to_user_id = None
    assigned_to_username = None

    if current_user.role in ["moderator", "admin"]:
        assigned_to_user_id = ticket.assigned_to_user_id
        assigned_to_username = ticket.assigned_to_user.username if ticket.assigned_to_user else None

    return TicketListRead(
        id=ticket.id,
        ticket_number=ticket.ticket_number,
        user_id=ticket.user_id,
        username=ticket.user.username if ticket.user else "-",
        category=ticket.category,
        status=ticket.status,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
        last_message_at=ticket.last_message_at,
        has_unread=ticket_has_unread_for_user(ticket, current_user, db),
        assigned_to_user_id=assigned_to_user_id,
        assigned_to_username=assigned_to_username,
    )


def serialize_ticket_detail(ticket: TicketDB, current_user: UserDB) -> TicketDetailRead:
    assigned_to_user_id = None
    assigned_to_username = None

    if current_user.role in ["moderator", "admin"]:
        assigned_to_user_id = ticket.assigned_to_user_id
        assigned_to_username = ticket.assigned_to_user.username if ticket.assigned_to_user else None

    return TicketDetailRead(
        id=ticket.id,
        ticket_number=ticket.ticket_number,
        user_id=ticket.user_id,
        username=ticket.user.username if ticket.user else "-",
        category=ticket.category,
        status=ticket.status,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
        last_message_at=ticket.last_message_at,
        assigned_to_user_id=assigned_to_user_id,
        assigned_to_username=assigned_to_username,
        messages=[serialize_ticket_message(message) for message in ticket.messages],
    )


def get_or_create_read_state(ticket_id: int, user_id: int, db: Session) -> TicketReadStateDB:
    state = (
        db.query(TicketReadStateDB)
        .filter(
            TicketReadStateDB.ticket_id == ticket_id,
            TicketReadStateDB.user_id == user_id,
        )
        .first()
    )
    if state:
        return state

    state = TicketReadStateDB(ticket_id=ticket_id, user_id=user_id, last_read_message_id=None)
    db.add(state)
    db.flush()
    return state


def mark_ticket_as_read(ticket: TicketDB, current_user: UserDB, db: Session) -> None:
    if not ticket.messages:
        return

    state = get_or_create_read_state(ticket.id, current_user.id, db)
    latest_message_id = max(message.id for message in ticket.messages)
    if state.last_read_message_id != latest_message_id:
        state.last_read_message_id = latest_message_id
        db.commit()


def mark_ticket_as_read_for_staff(ticket: TicketDB, current_user: UserDB, db: Session) -> None:
    if not ticket.messages:
        return

    latest_message = max(ticket.messages, key=lambda message: message.id)

    if ticket.staff_last_read_message_id != latest_message.id:
        ticket.staff_last_read_message_id = latest_message.id
        db.commit()


def count_unread_tickets_for_user(db: Session, current_user: UserDB) -> int:
    latest_subquery = (
        db.query(
            TicketMessageDB.ticket_id.label("ticket_id"),
            func.max(TicketMessageDB.id).label("latest_message_id"),
        )
        .group_by(TicketMessageDB.ticket_id)
        .subquery()
    )

    query = (
        db.query(TicketDB.id)
        .join(latest_subquery, latest_subquery.c.ticket_id == TicketDB.id)
        .join(TicketMessageDB, TicketMessageDB.id == latest_subquery.c.latest_message_id)
    )

    if current_user.role in ["moderator", "admin"]:
        if current_user.staff_notifications_start_at is not None:
            query = query.filter(
                TicketMessageDB.created_at >= current_user.staff_notifications_start_at
            )

        query = query.filter(~TicketMessageDB.sender.has(UserDB.role.in_(["moderator", "admin"])))
        query = query.filter(
            (TicketDB.staff_last_read_message_id.is_(None))
            | (TicketDB.staff_last_read_message_id < TicketMessageDB.id)
        )

        return query.distinct().count()

    query = query.outerjoin(
        TicketReadStateDB,
        (TicketReadStateDB.ticket_id == TicketDB.id)
        & (TicketReadStateDB.user_id == current_user.id),
    )

    query = query.filter(TicketDB.user_id == current_user.id)
    query = query.filter(TicketMessageDB.sender_id != current_user.id)
    query = query.filter(
        (TicketReadStateDB.last_read_message_id.is_(None))
        | (TicketReadStateDB.last_read_message_id < TicketMessageDB.id)
    )

    return query.distinct().count()


def get_ticket_create_availability(db: Session, current_user: UserDB) -> TicketCreateAvailabilityRead:
    if current_user.role in ["moderator", "admin"]:
        return TicketCreateAvailabilityRead(
            can_create=True,
            remaining_seconds=0,
            next_allowed_at=None,
        )

    latest_ticket = (
        db.query(TicketDB)
        .filter(TicketDB.user_id == current_user.id)
        .order_by(TicketDB.created_at.desc(), TicketDB.id.desc())
        .first()
    )

    if not latest_ticket or not latest_ticket.created_at:
        return TicketCreateAvailabilityRead(
            can_create=True,
            remaining_seconds=0,
            next_allowed_at=None,
        )

    next_allowed_at = latest_ticket.created_at + timedelta(hours=TICKET_CREATE_COOLDOWN_HOURS)
    now = datetime.utcnow()

    if now >= next_allowed_at:
        return TicketCreateAvailabilityRead(
            can_create=True,
            remaining_seconds=0,
            next_allowed_at=next_allowed_at,
        )

    remaining_seconds = int((next_allowed_at - now).total_seconds())
    return TicketCreateAvailabilityRead(
        can_create=False,
        remaining_seconds=max(0, remaining_seconds),
        next_allowed_at=next_allowed_at,
    )


# -------------------- PRODUCTS --------------------
@app.post("/products", response_model=ProductRead)
def create_product(
    payload: ProductCreate,
    db: Session = Depends(get_db),
    _: UserDB = Depends(require_admin),
):
    if payload.promotion not in PROMOTION_VALUES:
        raise HTTPException(status_code=400, detail="Promotie invalida")

    existing = db.query(ProductDB).filter(ProductDB.code == payload.code).first()

    if existing:
        existing.quantity += payload.quantity
        existing.name = payload.name
        existing.category = payload.category
        existing.price = payload.price
        existing.promotion = payload.promotion

        if payload.description is not None:
            existing.description = payload.description
        if payload.tech_details is not None:
            existing.tech_details = payload.tech_details
        if payload.video_url is not None:
            existing.video_url = payload.video_url

        db.commit()
        db.refresh(existing)
        return existing

    product = ProductDB(
        code=payload.code,
        name=payload.name,
        category=payload.category,
        price=payload.price,
        quantity=payload.quantity,
        promotion=payload.promotion,
        description=payload.description,
        tech_details=payload.tech_details,
        video_url=payload.video_url,
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


@app.get("/products", response_model=list[ProductRead])
def get_products(db: Session = Depends(get_db)):
    return db.query(ProductDB).all()


@app.get("/products/{product_id}", response_model=ProductRead)
def get_product_by_id(product_id: int, db: Session = Depends(get_db)):
    product = db.query(ProductDB).filter(ProductDB.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produsul nu exista")
    return product


@app.patch("/products/{product_id}", response_model=ProductRead)
def update_product(
    product_id: int,
    payload: ProductUpdate,
    db: Session = Depends(get_db),
    _: UserDB = Depends(require_admin),
):
    product = db.query(ProductDB).filter(ProductDB.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produs inexistent")

    data = payload.model_dump(exclude_unset=True)

    if "promotion" in data and data["promotion"] not in PROMOTION_VALUES:
        raise HTTPException(status_code=400, detail="Promotie invalida")

    for key, value in data.items():
        setattr(product, key, value)

    db.commit()
    db.refresh(product)
    return product


@app.delete("/products/{product_id}")
def delete_product(
    product_id: int,
    db: Session = Depends(get_db),
    _: UserDB = Depends(require_admin),
):
    product = db.query(ProductDB).filter(ProductDB.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produs inexistent")

    db.delete(product)
    db.commit()
    return {"ok": True}


# -------------------- AUTH --------------------
@app.post("/auth/register", response_model=UserRead)
def register(payload: UserCreate, db: Session = Depends(get_db)):
    existing_email = db.query(UserDB).filter(UserDB.email == payload.email).first()
    if existing_email:
        raise HTTPException(status_code=400, detail="Email already registered")

    existing_username = db.query(UserDB).filter(UserDB.username == payload.username).first()
    if existing_username:
        raise HTTPException(status_code=400, detail="Username already taken")

    user = UserDB(
        username=payload.username,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        role="user",
    )

    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@app.post("/auth/login", response_model=Token)
def login(payload: UserLogin, db: Session = Depends(get_db)):
    user = db.query(UserDB).filter(UserDB.email == payload.email).first()

    if not user:
        raise HTTPException(status_code=400, detail="Invalid credentials")

    if not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Invalid credentials")

    access_token = create_access_token(data={"sub": str(user.id), "role": user.role})

    return {
        "access_token": access_token,
        "token_type": "bearer",
    }


@app.get("/auth/me", response_model=UserRead)
def me(current_user: UserDB = Depends(get_current_user)):
    return current_user


# -------------------- CART --------------------
@app.get("/cart", response_model=CartRead)
def get_cart(
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    return build_cart_response(db, current_user)


@app.post("/cart/items", response_model=CartRead)
def add_cart_item(
    payload: CartItemAdd,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    product = db.query(ProductDB).filter(ProductDB.id == payload.product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produsul nu exista")

    if product.quantity <= 0:
        raise HTTPException(status_code=400, detail="Produs indisponibil")

    qty = max(1, payload.quantity)

    existing = (
        db.query(CartItemDB)
        .filter(CartItemDB.user_id == current_user.id, CartItemDB.product_id == payload.product_id)
        .first()
    )

    if existing:
        existing.quantity = min(existing.quantity + qty, product.quantity)
    else:
        db.add(
            CartItemDB(
                user_id=current_user.id,
                product_id=payload.product_id,
                quantity=min(qty, product.quantity),
            )
        )

    db.commit()
    return build_cart_response(db, current_user)


@app.patch("/cart/items/{product_id}", response_model=CartRead)
def update_cart_item(
    product_id: int,
    payload: CartItemUpdate,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    item = (
        db.query(CartItemDB)
        .filter(CartItemDB.user_id == current_user.id, CartItemDB.product_id == product_id)
        .first()
    )

    if not item:
        raise HTTPException(status_code=404, detail="Produsul nu este in cos")

    product = db.query(ProductDB).filter(ProductDB.id == product_id).first()
    if not product:
        db.delete(item)
        db.commit()
        return build_cart_response(db, current_user)

    if payload.quantity <= 0:
        db.delete(item)
        db.commit()
        return build_cart_response(db, current_user)

    item.quantity = min(payload.quantity, max(0, product.quantity))

    if item.quantity <= 0:
        db.delete(item)

    db.commit()
    return build_cart_response(db, current_user)


@app.delete("/cart/items/{product_id}", response_model=CartRead)
def delete_cart_item(
    product_id: int,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    item = (
        db.query(CartItemDB)
        .filter(CartItemDB.user_id == current_user.id, CartItemDB.product_id == product_id)
        .first()
    )

    if item:
        db.delete(item)
        db.commit()

    return build_cart_response(db, current_user)


@app.delete("/cart/clear", response_model=CartRead)
def clear_cart_endpoint(
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    db.query(CartItemDB).filter(CartItemDB.user_id == current_user.id).delete()
    db.commit()
    return CartRead(items=[], total=0.0)


# -------------------- ORDERS --------------------
@app.post("/orders", response_model=OrderRead)
def create_order(
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    cart_items = (
        db.query(CartItemDB)
        .options(joinedload(CartItemDB.product))
        .filter(CartItemDB.user_id == current_user.id)
        .all()
    )

    if not cart_items:
        raise HTTPException(status_code=400, detail="Cosul este gol")

    order = OrderDB(
        order_number=generate_order_number(),
        user_id=current_user.id,
        total=0,
        created_at=datetime.utcnow(),
        status="trimisa",
    )
    db.add(order)
    db.flush()

    total = 0.0
    items_to_delete = []

    for cart_item in cart_items:
        product = cart_item.product

        if not product:
            items_to_delete.append(cart_item)
            continue

        if cart_item.quantity <= 0:
            items_to_delete.append(cart_item)
            continue

        if product.quantity < cart_item.quantity:
            raise HTTPException(
                status_code=400,
                detail=f"Stoc insuficient pentru produsul {product.name}",
            )

        discounted_price = get_discounted_price(product.price, getattr(product, "promotion", 0))
        line_total = discounted_price * cart_item.quantity

        order_item = OrderItemDB(
            order_id=order.id,
            product_id=product.id,
            product_name=product.name,
            product_code=product.code,
            unit_price=discounted_price,
            quantity=cart_item.quantity,
            line_total=line_total,
        )
        db.add(order_item)

        product.quantity -= cart_item.quantity
        total += line_total
        items_to_delete.append(cart_item)

    order.total = total

    for item in items_to_delete:
        db.delete(item)

    db.commit()

    saved_order = (
        db.query(OrderDB)
        .options(joinedload(OrderDB.items), joinedload(OrderDB.user))
        .filter(OrderDB.id == order.id)
        .first()
    )

    return saved_order


@app.get("/orders/my", response_model=list[OrderRead])
def get_my_orders(
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    return (
        db.query(OrderDB)
        .options(joinedload(OrderDB.items), joinedload(OrderDB.user))
        .filter(OrderDB.user_id == current_user.id)
        .order_by(OrderDB.id.desc())
        .all()
    )


@app.get("/orders", response_model=list[OrderRead])
def get_all_orders(
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_moderator_or_admin),
):
    return (
        db.query(OrderDB)
        .options(joinedload(OrderDB.items), joinedload(OrderDB.user))
        .order_by(OrderDB.id.desc())
        .all()
    )


@app.get("/orders/{order_id}", response_model=OrderRead)
def get_order_by_id(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    order = (
        db.query(OrderDB)
        .options(joinedload(OrderDB.items), joinedload(OrderDB.user))
        .filter(OrderDB.id == order_id)
        .first()
    )

    if not order:
        raise HTTPException(status_code=404, detail="Comanda nu exista")

    is_staff = current_user.role in ["moderator", "admin"]
    is_owner = order.user_id == current_user.id

    if not is_staff and not is_owner:
        raise HTTPException(status_code=403, detail="Nu ai acces la aceasta comanda")

    return order


@app.patch("/orders/{order_id}/status", response_model=OrderRead)
def update_order_status(
    order_id: int,
    payload: OrderStatusUpdate,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_moderator_or_admin),
):
    if payload.status not in ORDER_STATUSES:
        raise HTTPException(status_code=400, detail="Status invalid")

    order = (
        db.query(OrderDB)
        .options(joinedload(OrderDB.items), joinedload(OrderDB.user))
        .filter(OrderDB.id == order_id)
        .first()
    )

    if not order:
        raise HTTPException(status_code=404, detail="Comanda nu exista")

    order.status = payload.status
    db.commit()
    db.refresh(order)
    return order


# -------------------- TICKETS --------------------
@app.get("/tickets/create-availability", response_model=TicketCreateAvailabilityRead)
def get_ticket_create_availability_endpoint(
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    return get_ticket_create_availability(db, current_user)


@app.post("/tickets", response_model=TicketDetailRead)
def create_ticket(
    payload: TicketCreate,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    availability = get_ticket_create_availability(db, current_user)
    if not availability.can_create:
        hours = availability.remaining_seconds // 3600
        minutes = (availability.remaining_seconds % 3600) // 60
        seconds = availability.remaining_seconds % 60
        raise HTTPException(
            status_code=400,
            detail=(
                "Poți deschide un nou tichet peste "
                f"{hours:02d}:{minutes:02d}:{seconds:02d}."
            ),
        )

    now = datetime.utcnow()
    clean_message = payload.message.strip()
    if not clean_message:
        raise HTTPException(status_code=400, detail="Mesajul nu poate fi gol")

    ticket = TicketDB(
        ticket_number=generate_ticket_number(),
        user_id=current_user.id,
        category=payload.category,
        status="open",
        created_at=now,
        updated_at=now,
        last_message_at=now,
        assigned_to_user_id=None,
    )
    db.add(ticket)
    db.flush()

    message = TicketMessageDB(
        ticket_id=ticket.id,
        sender_id=current_user.id,
        message=clean_message,
        created_at=now,
    )
    db.add(message)
    db.flush()

    owner_state = TicketReadStateDB(
        ticket_id=ticket.id,
        user_id=current_user.id,
        last_read_message_id=message.id,
    )
    db.add(owner_state)
    db.commit()

    saved_ticket = get_ticket_or_404(ticket.id, db)
    return serialize_ticket_detail(saved_ticket, current_user)


@app.get("/tickets/my", response_model=list[TicketListRead])
def get_my_tickets(
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    tickets = (
        db.query(TicketDB)
        .options(joinedload(TicketDB.user), joinedload(TicketDB.assigned_to_user))
        .filter(TicketDB.user_id == current_user.id)
        .order_by(TicketDB.last_message_at.desc(), TicketDB.id.desc())
        .all()
    )
    return [serialize_ticket_list(ticket, current_user, db) for ticket in tickets]


@app.get("/tickets", response_model=list[TicketListRead])
def get_all_tickets(
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_moderator_or_admin),
):
    tickets = (
        db.query(TicketDB)
        .options(joinedload(TicketDB.user), joinedload(TicketDB.assigned_to_user))
        .order_by(TicketDB.last_message_at.desc(), TicketDB.id.desc())
        .all()
    )
    return [serialize_ticket_list(ticket, current_user, db) for ticket in tickets]


@app.get("/tickets/unread-count", response_model=TicketUnreadCountRead)
def get_unread_ticket_count(
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    return TicketUnreadCountRead(count=count_unread_tickets_for_user(db, current_user))


@app.get("/tickets/assignable-users", response_model=list[AssignableStaffRead])
def get_assignable_users(
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_moderator_or_admin),
):
    return (
        db.query(UserDB)
        .filter(UserDB.role.in_(["moderator", "admin"]))
        .order_by(UserDB.role.asc(), UserDB.username.asc())
        .all()
    )


@app.get("/tickets/{ticket_id}", response_model=TicketDetailRead)
def get_ticket_detail(
    ticket_id: int,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    ticket = get_ticket_or_404(ticket_id, db)

    if not can_access_ticket(ticket, current_user):
        raise HTTPException(status_code=403, detail="Nu ai acces la acest tichet")

    if current_user.role in ["moderator", "admin"]:
        mark_ticket_as_read_for_staff(ticket, current_user, db)
    else:
        mark_ticket_as_read(ticket, current_user, db)

    refreshed_ticket = get_ticket_or_404(ticket_id, db)
    return serialize_ticket_detail(refreshed_ticket, current_user)


@app.post("/tickets/{ticket_id}/messages", response_model=TicketDetailRead)
def add_ticket_message(
    ticket_id: int,
    payload: TicketMessageCreate,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user),
):
    ticket = get_ticket_or_404(ticket_id, db)

    if not can_access_ticket(ticket, current_user):
        raise HTTPException(status_code=403, detail="Nu ai acces la acest tichet")

    if ticket.status == "closed":
        raise HTTPException(status_code=400, detail="Tichetul este inchis")

    clean_message = payload.message.strip()
    if not clean_message:
        raise HTTPException(status_code=400, detail="Mesajul nu poate fi gol")

    now = datetime.utcnow()
    message = TicketMessageDB(
        ticket_id=ticket.id,
        sender_id=current_user.id,
        message=clean_message,
        created_at=now,
    )
    db.add(message)
    db.flush()

    ticket.updated_at = now
    ticket.last_message_at = now

    if current_user.role in ["moderator", "admin"]:
        ticket.staff_last_read_message_id = message.id
    else:
        ticket.staff_last_read_message_id = None
        sender_state = get_or_create_read_state(ticket.id, current_user.id, db)
        sender_state.last_read_message_id = message.id

    db.commit()

    saved_ticket = get_ticket_or_404(ticket.id, db)
    return serialize_ticket_detail(saved_ticket, current_user)


@app.patch("/tickets/{ticket_id}/assign", response_model=TicketDetailRead)
def assign_ticket(
    ticket_id: int,
    payload: TicketAssignPayload,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_moderator_or_admin),
):
    ticket = get_ticket_or_404(ticket_id, db)

    if payload.assigned_to_user_id is None:
        ticket.assigned_to_user_id = None
        ticket.updated_at = datetime.utcnow()
        db.commit()
        saved_ticket = get_ticket_or_404(ticket.id, db)
        return serialize_ticket_detail(saved_ticket, current_user)

    staff_user = (
        db.query(UserDB)
        .filter(
            UserDB.id == payload.assigned_to_user_id,
            UserDB.role.in_(["moderator", "admin"]),
        )
        .first()
    )

    if not staff_user:
        raise HTTPException(status_code=404, detail="Responsabilul selectat nu exista")

    ticket.assigned_to_user_id = staff_user.id
    ticket.updated_at = datetime.utcnow()
    db.commit()

    saved_ticket = get_ticket_or_404(ticket.id, db)
    return serialize_ticket_detail(saved_ticket, current_user)


@app.patch("/tickets/{ticket_id}/close", response_model=TicketDetailRead)
def close_ticket(
    ticket_id: int,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_moderator_or_admin),
):
    ticket = get_ticket_or_404(ticket_id, db)
    now = datetime.utcnow()
    ticket.status = "closed"
    ticket.updated_at = now
    db.commit()

    saved_ticket = get_ticket_or_404(ticket.id, db)
    return serialize_ticket_detail(saved_ticket, current_user)


@app.post("/assistant/chat", response_model=AssistantChatResponse)
def assistant_chat(
    payload: AssistantChatRequest,
    db: Session = Depends(get_db),
    current_user: UserDB | None = Depends(get_optional_current_user),
):
    return handle_assistant_chat(
        payload=payload,
        db=db,
        current_user=current_user,
        build_cart_response=build_cart_response,
    )