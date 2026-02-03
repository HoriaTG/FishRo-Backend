from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# URL-ul bazei de date SQLite:
# sqlite:///app.db = fisier app.db in folderul curent
SQLALCHEMY_DATABASE_URL = "sqlite:///./app.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False}  # necesar pt SQLite + FastAPI
)

# SessionLocal = "fabrica" de sesiuni DB (conexiuni)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base = clasa de baza pt toate tabelele (modelele) noastre
Base = declarative_base()
