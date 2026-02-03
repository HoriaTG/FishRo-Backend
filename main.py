from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session

from db import Base, engine, SessionLocal
from models import MessageDB, ProductDB
from schemas import MessageCreate, MessageRead, ProductCreate, ProductRead

app = FastAPI(title="Fishing App - SQLite")

# 1) Cream tabelele in DB daca nu exista deja
Base.metadata.create_all(bind=engine)

# 2) Dependency: ne da o sesiune DB pentru fiecare request
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# 3) POST: creeaza mesaj in baza de date
@app.post("/messages", response_model=MessageRead)
def create_message(payload: MessageCreate, db: Session = Depends(get_db)):
    message = MessageDB(text=payload.text, autor=payload.autor)
    db.add(message)
    db.commit()
    db.refresh(message)  # dupa commit, message primeste id-ul generat de DB
    return message

# 4) GET: lista mesaje din baza de date
@app.get("/messages", response_model=list[MessageRead])
def get_messages(db: Session = Depends(get_db)):
    return db.query(MessageDB).all()

# 5) GET: un mesaj dupa id
@app.get("/messages/{message_id}", response_model=MessageRead)
def get_message_by_id(message_id: int, db: Session = Depends(get_db)):
    message = db.query(MessageDB).filter(MessageDB.id == message_id).first()
    if not message:
        raise HTTPException(status_code=404, detail="Mesajul nu exista")
    return message


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
