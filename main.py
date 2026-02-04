from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session

from db import Base, engine, SessionLocal
from models import ProductDB
from schemas import ProductCreate, ProductRead

from models import UserDB
from schemas import UserCreate, UserRead, Token
from auth import hash_password, verify_password, create_access_token


from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Fishing App - SQLite")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 1) Cream tabelele in DB daca nu exista deja
Base.metadata.create_all(bind=engine)

# 2) Dependency: ne da o sesiune DB pentru fiecare request
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# -------------------- PRODUCTS --------------------

@app.post("/products", response_model=ProductRead)
def create_product(payload: ProductCreate, db: Session = Depends(get_db)):
    product = ProductDB(
        name=payload.name,
        category=payload.category,
        price=payload.price
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
        hashed_password=hash_password(payload.password)
    )

    db.add(user)
    db.commit()
    db.refresh(user)
    return user
