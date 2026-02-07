from db import SessionLocal
from models import UserDB

EMAIL = "user@test.com"

db = SessionLocal()
try:
    user = db.query(UserDB).filter(UserDB.email == EMAIL).first()
    if not user:
        print("User not found")
    else:
        user.role = "admin"
        db.commit()
        print(f"OK: {user.email} is now {user.role}")
finally:
    db.close()
