from db import SessionLocal
from models import ProductDB

CATEGORY_MAP = {
    "undite": "undita",
    "undita": "undita",

    "lansete": "lanseta",
    "lanseta": "lanseta",

    "mulinete": "mulineta",
    "mulineta": "mulineta",

    "carlige": "carlig",
    "carlig": "carlig",

    "plumbi": "plumb",
    "plumb": "plumb",

    "nailoane": "nailon",
    "nailon": "nailon",

    "echipament": "echipamente",
    "echipamente": "echipamente",
    "scaune": "echipamente",
    "corturi": "echipamente",

    "momeala": "momeli",
    "momeli": "momeli",

    "divers": "diverse",
    "diverse": "diverse",

    "nade": "nada",
    "nada": "nada",

    "pluta": "plute",
    "plute": "plute",
}

db = SessionLocal()

try:
    products = db.query(ProductDB).all()

    changed = 0
    unknown = []

    for product in products:
        old_category = (product.category or "").strip().lower()

        if old_category in CATEGORY_MAP:
            new_category = CATEGORY_MAP[old_category]
            if product.category != new_category:
                print(f"[UPDATE] {product.name}: {product.category} -> {new_category}")
                product.category = new_category
                changed += 1
        else:
            unknown.append((product.id, product.name, product.category))

    if changed > 0:
        db.commit()

    print(f"\nDone. Updated {changed} product(s).")

    if unknown:
        print("\nUnknown categories found:")
        for pid, name, cat in unknown:
            print(f" - id={pid}, name={name}, category={cat}")

finally:
    db.close()