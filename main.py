from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from datetime import datetime

from db import Base, engine, SessionLocal
from models import ProductDB, UserDB, OrderDB, OrderItemDB, CartItemDB
from schemas import (
    ProductCreate,
    ProductRead,
    ProductUpdate,
    UserCreate,
    UserRead,
    UserLogin,
    Token,
    OrderRead,
    CartItemAdd,
    CartItemUpdate,
    CartItemRead,
    CartRead,
)
from auth import hash_password, verify_password, create_access_token, decode_access_token
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials


app = FastAPI(title="Fishing App - SQLite")
bearer_scheme = HTTPBearer()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:4173",
        "http://192.168.1.135:4173",
        "http://127.0.0.1:4173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db)
) -> UserDB:
    token = credentials.credentials
    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        raise HTTPException(status_code=401, detail="Invalid token")

    user_id = int(payload["sub"])
    user = db.query(UserDB).filter(UserDB.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return user


def require_admin(current_user: UserDB = Depends(get_current_user)) -> UserDB:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return current_user


def require_moderator_or_admin(current_user: UserDB = Depends(get_current_user)) -> UserDB:
    if current_user.role not in ["moderator", "admin"]:
        raise HTTPException(status_code=403, detail="Moderator or Admin only")
    return current_user


def generate_order_number() -> str:
    return f"RO-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}"


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

        line_total = product.price * item.quantity
        total += line_total

        result_items.append(
            CartItemRead(
                id=item.id,
                product_id=product.id,
                product_name=product.name,
                product_code=product.code,
                unit_price=product.price,
                quantity=item.quantity,
                stock=product.quantity,
                image_url=f"/images/products/{product.code}.jpg",
                unavailable=False,
            )
        )

    if changed:
        db.commit()

    return CartRead(items=result_items, total=total)


# -------------------- PRODUCTS --------------------
@app.post("/products", response_model=ProductRead)
def create_product(
    payload: ProductCreate,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user)
):
    existing = db.query(ProductDB).filter(ProductDB.code == payload.code).first()

    if existing:
        existing.quantity += payload.quantity
        existing.name = payload.name
        existing.category = payload.category
        existing.price = payload.price

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
        description=payload.description,
        tech_details=payload.tech_details,
        video_url=payload.video_url
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
    current_user=Depends(get_current_user),
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    product = db.query(ProductDB).filter(ProductDB.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produs inexistent")

    data = payload.model_dump(exclude_unset=True)

    for key, value in data.items():
        setattr(product, key, value)

    db.commit()
    db.refresh(product)

    return product


@app.delete("/products/{product_id}")
def delete_product(
    product_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    p = db.query(ProductDB).filter(ProductDB.id == product_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Produs inexistent")

    db.delete(p)
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
        role="user"
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

    access_token = create_access_token(
        data={"sub": str(user.id), "role": user.role}
    )

    return {
        "access_token": access_token,
        "token_type": "bearer"
    }


@app.get("/auth/me", response_model=UserRead)
def me(current_user: UserDB = Depends(get_current_user)):
    return current_user


# -------------------- CART --------------------
@app.get("/cart", response_model=CartRead)
def get_cart(
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user)
):
    return build_cart_response(db, current_user)


@app.post("/cart/items", response_model=CartRead)
def add_cart_item(
    payload: CartItemAdd,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user)
):
    product = db.query(ProductDB).filter(ProductDB.id == payload.product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produsul nu exista")

    if product.quantity <= 0:
        raise HTTPException(status_code=400, detail="Produs indisponibil")

    qty = max(1, payload.quantity)

    existing = (
        db.query(CartItemDB)
        .filter(
            CartItemDB.user_id == current_user.id,
            CartItemDB.product_id == payload.product_id
        )
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
    current_user: UserDB = Depends(get_current_user)
):
    item = (
        db.query(CartItemDB)
        .filter(
            CartItemDB.user_id == current_user.id,
            CartItemDB.product_id == product_id
        )
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
    current_user: UserDB = Depends(get_current_user)
):
    item = (
        db.query(CartItemDB)
        .filter(
            CartItemDB.user_id == current_user.id,
            CartItemDB.product_id == product_id
        )
        .first()
    )

    if item:
        db.delete(item)
        db.commit()

    return build_cart_response(db, current_user)


@app.delete("/cart/clear", response_model=CartRead)
def clear_cart_endpoint(
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user)
):
    db.query(CartItemDB).filter(CartItemDB.user_id == current_user.id).delete()
    db.commit()
    return CartRead(items=[], total=0.0)


# -------------------- ORDERS --------------------
@app.post("/orders", response_model=OrderRead)
def create_order(
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user)
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
        created_at=datetime.utcnow()
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
                detail=f"Stoc insuficient pentru produsul {product.name}"
            )

        line_total = product.price * cart_item.quantity

        order_item = OrderItemDB(
            order_id=order.id,
            product_id=product.id,
            product_name=product.name,
            product_code=product.code,
            unit_price=product.price,
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
    current_user: UserDB = Depends(get_current_user)
):
    orders = (
        db.query(OrderDB)
        .options(joinedload(OrderDB.items), joinedload(OrderDB.user))
        .filter(OrderDB.user_id == current_user.id)
        .order_by(OrderDB.id.desc())
        .all()
    )
    return orders


@app.get("/orders", response_model=list[OrderRead])
def get_all_orders(
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(require_moderator_or_admin)
):
    orders = (
        db.query(OrderDB)
        .options(joinedload(OrderDB.items), joinedload(OrderDB.user))
        .order_by(OrderDB.id.desc())
        .all()
    )
    return orders


@app.get("/orders/{order_id}", response_model=OrderRead)
def get_order_by_id(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: UserDB = Depends(get_current_user)
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