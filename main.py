from fastapi import FastAPI, Depends, HTTPException, Header
from sqlalchemy.orm import Session

from db import Base, engine, SessionLocal
from models import ProductDB, UserDB
from schemas import ProductCreate, ProductRead, UserCreate, UserRead, UserLogin, Token
from auth import hash_password, verify_password, create_access_token, decode_access_token
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials




app = FastAPI(title="Fishing App - SQLite")
bearer_scheme = HTTPBearer()


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

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db)
) -> UserDB:
    token = credentials.credentials  # tokenul fără "Bearer"

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





# -------------------- PRODUCTS --------------------

@app.post("/products", response_model=ProductRead)
def create_product(
    payload: ProductCreate,
    db: Session = Depends(get_db),
    admin_user: UserDB = Depends(require_admin)
):
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
        hashed_password=hash_password(payload.password),
        role="user"
    )

    db.add(user)
    db.commit()
    db.refresh(user)
    return user



@app.post("/auth/login", response_model=Token)
def login(payload: UserLogin, db: Session = Depends(get_db)):
    # 1. căutăm user-ul după email
    user = db.query(UserDB).filter(UserDB.email == payload.email).first()

    if not user:
        raise HTTPException(status_code=400, detail="Invalid credentials")

    # 2. verificăm parola
    if not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Invalid credentials")

    # 3. creăm token-ul
    access_token = create_access_token(
        data={"sub": str(user.id), "role": user.role}
    )

    # 4. îl returnăm
    return {
        "access_token": access_token,
        "token_type": "bearer"
    }


@app.get("/auth/me", response_model=UserRead)
def me(current_user: UserDB = Depends(get_current_user)):
    return current_user
