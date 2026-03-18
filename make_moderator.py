from db import SessionLocal
from models import UserDB

EMAIL = "moderator2@fishro.com"   # schimbă cu emailul utilizatorului

db = SessionLocal()
try:
    user = db.query(UserDB).filter(UserDB.email == EMAIL).first()

    if not user:
        print("User not found")
    else:
        user.role = "moderator"
        db.commit()
        print(f"OK: {user.email} is now {user.role}")
finally:
    db.close()