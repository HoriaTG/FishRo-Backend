from datetime import datetime, timedelta

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import re
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from auth import create_access_token, decode_access_token, hash_password, verify_password
from db import Base, SessionLocal, engine

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
    AssistantChatRequest,
    AssistantChatResponse,
    AssistantProductSuggestion,
    AssistantContextProduct,
)

app = FastAPI(title="Fishing App - SQLite")
bearer_scheme = HTTPBearer()
optional_bearer_scheme = HTTPBearer(auto_error=False)

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

TICKET_CREATE_COOLDOWN_HOURS = 12
ORDER_STATUSES = {"trimisa", "confirmata", "in_tranzit", "livrata", "anulata"}
PROMOTION_VALUES = {0, 10, 20, 30, 40, 50, 60, 70, 80, 90}


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
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

def get_optional_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(optional_bearer_scheme),
    db: Session = Depends(get_db),
) -> UserDB | None:
    if not credentials:
        return None

    token = credentials.credentials
    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        return None

    user_id = int(payload["sub"])
    user = db.query(UserDB).filter(UserDB.id == user_id).first()
    return user


def get_discounted_price(price: float, promotion: int | None) -> float:
    promo = promotion or 0
    promo = max(0, min(90, promo))
    return round(price * (1 - promo / 100), 2)


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

def phrase_in_text(message: str, phrase: str) -> bool:
    normalized_message = f" {normalize_text(message)} "
    normalized_phrase = f" {normalize_text(phrase)} "
    return normalized_phrase in normalized_message


def score_intent(message: str, phrases_with_scores: dict[str, int]) -> int:
    score = 0
    for phrase, points in phrases_with_scores.items():
        if phrase_in_text(message, phrase):
            score += points
    return score


def is_product_comparison_question(message: str) -> bool:
    comparison_phrases = [
        "mai bun",
        "mai buna",
        "mai bună",
        "care e mai bun",
        "care este mai bun",
        "care e mai buna",
        "care este mai buna",
        "care este mai bună",
        "ce e mai bun",
        "ce este mai bun",
        "pe care il recomanzi",
        "pe care il recomanzi dintre",
        "care e mai ok",
        "care este mai ok",
        "care merita",
        "care merită",
        "ce aleg",
        "ce sa aleg",
        "ce să aleg",
        "ce imi recomanzi dintre",
        "ce îmi recomanzi dintre",
        "dintre cele 2",
        "dintre cele doua",
        "dintre astea doua",
    ]
    normalized = normalize_text(message)
    return any(phrase in normalized for phrase in comparison_phrases)


def compare_context_products(context_products: list[AssistantContextProduct]) -> str:
    if len(context_products) < 2:
        return (
            "Pot compara două produse dacă îmi pui întrebarea imediat după ce îți afișez două sugestii relevante. "
            "Spune-mi din nou după ce primești produsele în chat."
        )

    first = context_products[0]
    second = context_products[1]

    reasons_first = []
    reasons_second = []

    if first.promotion > second.promotion:
        reasons_first.append("are reducere mai mare")
    elif second.promotion > first.promotion:
        reasons_second.append("are reducere mai mare")

    if first.discounted_price < second.discounted_price:
        reasons_first.append("este mai ieftin")
    elif second.discounted_price < first.discounted_price:
        reasons_second.append("este mai ieftin")

    if first.category == second.category:
        same_category_note = "Fac parte din aceeași categorie"
    else:
        same_category_note = "Fac parte din categorii diferite"

    score_first = len(reasons_first)
    score_second = len(reasons_second)

    if score_first > score_second:
        why = ", ".join(reasons_first)
        return (
            f"Dintre cele două, aș înclina spre „{first.name}”, deoarece {why}. "
            f"{same_category_note}. Totuși, alegerea finală depinde și de stilul tău de pescuit și de buget."
        )

    if score_second > score_first:
        why = ", ".join(reasons_second)
        return (
            f"Dintre cele două, aș înclina spre „{second.name}”, deoarece {why}. "
            f"{same_category_note}. Totuși, alegerea finală depinde și de stilul tău de pescuit și de buget."
        )

    return (
        f"Între „{first.name}” și „{second.name}”, nu există un câștigător clar doar din preț și promoție. "
        f"{same_category_note}. Dacă vrei, îți pot recomanda varianta mai potrivită pentru începători sau pentru pescuit la crap."
    )

def normalize_text(text: str) -> str:
    text = text.lower().strip()
    replacements = {
        "ă": "a",
        "â": "a",
        "î": "i",
        "ș": "s",
        "ş": "s",
        "ț": "t",
        "ţ": "t",
    }
    for src, dest in replacements.items():
        text = text.replace(src, dest)
    return text

CATEGORY_KEYWORDS = {
    "undita": ["undita", "undite"],
    "lanseta": ["lanseta", "lansete"],
    "mulineta": ["mulineta", "mulinete"],
    "carlig": ["carlig", "carlige", "cârlig", "cârlige"],
    "plumb": ["plumb", "plumbi"],
    "nailon": ["nailon", "fir", "fire", "monofilament"],
    "echipamente": ["echipament", "echipamente", "accesorii"],
    "momeli": ["momeala", "momeli", "boilies", "pelete"],
    "diverse": ["diverse", "alte produse"],
    "nada": ["nada", "nade"],
    "plute": ["pluta", "plute"],
}

FISHING_STYLE_HINTS = {
    "crap": ["lanseta", "mulineta", "nada", "momeli"],
    "feeder": ["lanseta", "mulineta", "momeli", "nada"],
    "spinning": ["lanseta", "mulineta", "momeli"],
    "stationar": ["undita", "plute", "carlig", "nailon"],
}


def format_price(value: float) -> str:
    return f"{value:.2f} lei"


def serialize_assistant_product(product: ProductDB) -> AssistantProductSuggestion:
    discounted = get_discounted_price(product.price, product.promotion)
    return AssistantProductSuggestion(
        id=product.id,
        name=product.name,
        category=product.category,
        price=product.price,
        discounted_price=discounted,
        promotion=product.promotion or 0,
        image_url=f"/images/products/{product.code}.jpg",
    )


def detect_category_from_text(message: str) -> str | None:
    for category, keywords in CATEGORY_KEYWORDS.items():
        for keyword in keywords:
            if keyword in message:
                return category
    return None


def detect_budget_from_text(message: str) -> int | None:
    match = re.search(r"(?:sub|subt?|maxim|maximum|pana la|pana in|buget(?: de)?)\s*(\d{1,5})", message)
    if match:
        return int(match.group(1))

    standalone = re.search(r"(\d{1,5})\s*lei", message)
    if standalone and any(token in message for token in ["sub", "max", "buget", "pana la", "pana in"]):
        return int(standalone.group(1))

    return None


def get_top_promotions(db: Session, limit: int = 4) -> list[ProductDB]:
    return (
        db.query(ProductDB)
        .filter(ProductDB.quantity > 0, ProductDB.promotion > 0)
        .order_by(ProductDB.promotion.desc(), ProductDB.price.asc())
        .limit(limit)
        .all()
    )


def get_products_by_category(db: Session, category: str, limit: int = 4) -> list[ProductDB]:
    return (
        db.query(ProductDB)
        .filter(ProductDB.category == category, ProductDB.quantity > 0)
        .order_by(ProductDB.promotion.desc(), ProductDB.price.asc())
        .limit(limit)
        .all()
    )


def get_products_under_budget(db: Session, budget: int, limit: int = 4) -> list[ProductDB]:
    products = (
        db.query(ProductDB)
        .filter(ProductDB.quantity > 0)
        .order_by(ProductDB.price.asc())
        .all()
    )

    filtered = [
        product for product in products
        if get_discounted_price(product.price, product.promotion) <= budget
    ]
    return filtered[:limit]


def get_products_for_style(db: Session, style: str, limit: int = 4) -> list[ProductDB]:
    categories = FISHING_STYLE_HINTS.get(style, [])
    if not categories:
        return []

    products = (
        db.query(ProductDB)
        .filter(ProductDB.category.in_(categories), ProductDB.quantity > 0)
        .order_by(ProductDB.promotion.desc(), ProductDB.price.asc())
        .limit(limit)
        .all()
    )
    return products

def is_product_detail_question(message: str) -> bool:
    detail_phrases = [
        "de ce e special",
        "de ce este special",
        "ce are special",
        "ce il face special",
        "ce îl face special",
        "de ce e bun",
        "de ce este bun",
        "ce are bun",
        "ce are interesant",
        "merita",
        "merită",
        "e bun",
        "este bun",
        "e ok",
        "este ok",
        "e potrivit",
        "este potrivit",
    ]
    normalized = normalize_text(message)
    return any(phrase in normalized for phrase in detail_phrases)


def is_category_browse_question(message: str) -> bool:
    browse_phrases = [
        "arata-mi",
        "arata",
        "ce aveti",
        "ce ai",
        "ce produse",
        "vreau",
        "caut",
        "recomanda-mi",
        "recomanda",
        "ai",
        "aveti",
    ]
    normalized = normalize_text(message)
    return any(phrase in normalized for phrase in browse_phrases)


def explain_context_product(
    message: str,
    context_products: list[AssistantContextProduct],
    focused_product: AssistantContextProduct | None,
) -> str:
    product = resolve_focused_product(message, context_products, focused_product)

    if not product:
        return (
            "Pot să îți spun mai multe despre un produs dacă îmi pui întrebarea imediat după ce îți afișez acel produs în chat."
        )

    details = []

    if product.promotion > 0:
        details.append(f"are o reducere de {product.promotion}%")

    if product.discounted_price < product.price:
        details.append(
            f"prețul actual este {product.discounted_price:.2f} lei, față de {product.price:.2f} lei inițial"
        )
    else:
        details.append(f"are prețul de {product.price:.2f} lei")

    details.append(f"face parte din categoria {product.category}")

    details_text = ", iar ".join(details)

    return (
        f"Produsul „{product.name}” poate fi interesant deoarece {details_text}. "
        "Dacă vrei o recomandare mai exactă, îți pot spune și dacă pare mai potrivit pentru începători sau pentru un anumit stil de pescuit."
    )

def is_product_comparison_question(message: str) -> bool:
    normalized = normalize_text(message)

    comparison_keywords = [
        "mai bun",
        "mai buna",
        "mai bună",
        "care e mai bun",
        "care este mai bun",
        "pe care il recomanzi",
        "pe care mi-l recomanzi",
        "pe care mi l recomanzi",
        "ce aleg",
        "ce sa aleg",
        "dintre",
        "din astea",
        "din cele",
        "care din",
        "recomanzi mai mult",
    ]

    return any(k in normalized for k in comparison_keywords)

def compare_context_products(context_products: list[AssistantContextProduct]) -> str:
    if len(context_products) < 2:
        return "Am nevoie de cel puțin două produse pentru a face o comparație."

    p1 = context_products[0]
    p2 = context_products[1]

    # calculează reducerea %
    def discount(p):
        if p.price == 0:
            return 0
        return (p.price - p.discounted_price) / p.price

    d1 = discount(p1)
    d2 = discount(p2)

    # alegere simplă
    if d1 > d2:
        better = p1
        other = p2
        reason = "are o reducere mai mare"
    elif d2 > d1:
        better = p2
        other = p1
        reason = "are o reducere mai mare"
    else:
        # fallback: mai ieftin
        if p1.discounted_price < p2.discounted_price:
            better = p1
            other = p2
        else:
            better = p2
            other = p1
        reason = "are un preț mai bun"

    return (
        f"Dintre „{p1.name}” și „{p2.name}”, ți-aș recomanda mai degrabă „{better.name}”, "
        f"pentru că {reason}. "
        f"Totuși, dacă vrei, îți pot spune și în funcție de stilul tău de pescuit care e mai potrivit."
    )

def is_followup_product_reference(message: str) -> bool:
    followup_phrases = [
        "dar ala",
        "dar aia",
        "dar acela",
        "dar aceasta",
        "dar acesta",
        "dar celalalt",
        "dar cealalta",
        "si ala",
        "si aia",
        "si acesta",
        "si aceasta",
        "si celalalt",
        "si scaunul",
        "si mulineta",
        "si lanseta",
        "dar scaunul",
        "dar mulineta",
        "dar lanseta",
        "dar carligul",
        "dar pluta",
    ]
    normalized = normalize_text(message)
    return any(phrase in normalized for phrase in followup_phrases)


def resolve_focused_product(
    message: str,
    context_products: list[AssistantContextProduct],
    focused_product: AssistantContextProduct | None,
) -> AssistantContextProduct | None:
    normalized_message = normalize_text(message)

    for product in context_products:
        product_name = normalize_text(product.name)
        product_category = normalize_text(product.category)

        if product_name in normalized_message or product_category in normalized_message:
            return product

    if focused_product:
        return focused_product

    if context_products:
        return context_products[0]

    return None

ASSISTANT_INTENT_SCORES = {
    "greeting": {
        "salut": 6,
        "hello": 6,
        "buna ziua": 6,
        "hey": 5,
        "neata": 6,
    },
    "thanks": {
        "multumesc": 8,
        "mersi": 8,
        "merci": 8,
        "ms": 6,
        "super, multumesc": 10,
        "ok, multumesc": 10,
        "bine, multumesc": 10,
        "sarut mana": 8,
    },
    "promotions": {
        "promotie": 4,
        "promotii": 4,
        "reducere": 4,
        "reduceri": 4,
        "oferta": 3,
        "oferte": 3,
        "produse reduse": 5,
        "ce aveti la promotie": 6,
        "ce ai la promotie": 6,
        "arata-mi promotiile": 6,
        "arata promotiile": 5,
    },
    "general_recommendation": {
        "ce produse imi recomanzi": 10,
        "ce produse imi recomandati": 10,
        "ce imi recomanzi": 9,
        "ce mi recomanzi": 9,
        "ce recomandari ai": 8,
        "ce recomandari aveti": 8,
        "ce recomanzi": 7,
        "imi recomanzi ceva": 8,
        "vreau o recomandare": 8,
        "ce produse recomanzi": 9,
    },
    "budget": {
        "sub": 2,
        "maxim": 2,
        "maximum": 2,
        "buget": 3,
        "pana la": 3,
        "pana in": 3,
        "ieftin": 2,
        "ieftine": 2,
    },
    "carp_recommendation": {
        "crap": 5,
        "pescuit la crap": 7,
        "pentru crap": 5,
        "recomanzi pentru crap": 7,
        "recomandare pentru crap": 7,
    },
    "beginner_recommendation": {
        "incepator": 6,
        "incepatoare": 6,
        "incepatori": 6,
        "la inceput": 5,
        "sunt incepator": 7,
        "sunt la inceput": 7,
        "recomanzi pentru incepatori": 7,
        "recomandare pentru incepatori": 7,
    },
    "cart_summary": {
        "ce am in cos": 8,
        "mai am ceva in cos": 9,
        "am ceva in cos": 8,
        "cosul meu": 8,
        "produse in cos": 7,
        "am produse in cos": 8,
        "cos": 4,
        "cart": 4,
    },
    "last_order": {
        "ultima comanda": 8,
        "ultima mea comanda": 9,
        "comenzile mele": 8,
        "am comenzi": 7,
        "ce comenzi am": 8,
        "unde vad comenzile": 8,
        "unde vad comenzile mele": 9,
        "am vreo comanda": 8,
        "exista vreo comanda": 8,
        "am plasat ceva": 7,
        "am comandat ceva": 7,
        "istoric comenzi": 8,
    },
    "login_help": {
        "cum ma autentific": 9,
        "cum intru in cont": 8,
        "unde ma loghez": 8,
        "autentificare": 6,
        "login": 6,
        "logare": 6,
        "cum fac login": 9,
        "cum ma loghez": 8,
    },
    "ticket_help": {
        "cum deschid un tichet": 10,
        "cum fac un tichet": 9,
        "cum creez un tichet": 10,
        "vreau sa deschid un tichet": 10,
        "vreau sa creez un tichet": 10,
        "cum deschid ticket": 9,
        "am nevoie de suport": 6,
        "vreau suport": 6,
    },
    "ticket_status": {
        "am tichete": 6,
        "am tichete deschise": 9,
        "ce tichete am": 8,
        "tichetele mele": 8,
        "am vreun tichet deschis": 9,
        "ticketele mele": 8,
        "am ticket": 5,
    },
    "order_help": {
        "cum comand": 9,
        "cum pot comanda": 9,
        "cum plasez o comanda": 10,
        "cum fac o comanda": 9,
        "vreau sa comand": 7,
        "cum cumpar": 8,
    },
    "support_info": {
        "livrare": 5,
        "retur": 5,
        "plata": 5,
        "cum se livreaza": 8,
        "cum fac retur": 8,
        "metode de plata": 8,
        "cum platesc": 7,
    },
}


def detect_assistant_intent(
    message: str,
    context_products: list[AssistantContextProduct] | None = None,
    focused_product: AssistantContextProduct | None = None,
) -> str | None:
    context_products = context_products or []
    focused_product = focused_product
    scores: dict[str, int] = {}

    for intent_name, phrases in ASSISTANT_INTENT_SCORES.items():
        scores[intent_name] = score_intent(message, phrases)

    if detect_budget_from_text(message) is not None:
        scores["budget"] = scores.get("budget", 0) + 6

    category = detect_category_from_text(message)
    if category and is_category_browse_question(message):
        scores["products_by_category"] = scores.get("products_by_category", 0) + 6

    if is_product_comparison_question(message) and len(context_products) >= 2:
        scores["product_comparison"] = 12

    if is_product_detail_question(message) and len(context_products) >= 1:
        scores["product_detail_question"] = 12

    if is_followup_product_reference(message) and (focused_product is not None or len(context_products) >= 1):
        scores["product_detail_question"] = max(scores.get("product_detail_question", 0), 11)

    best_intent = None
    best_score = 0

    for intent_name, value in scores.items():
        if value > best_score:
            best_score = value
            best_intent = intent_name

    return best_intent if best_score >= 5 else None


def build_login_required_response(reply: str, intent: str, suggestions: list[str] | None = None) -> AssistantChatResponse:
    return AssistantChatResponse(
        reply=reply,
        intent=intent,
        requires_login=True,
        suggestions=suggestions or ["Arată-mi promoțiile", "Cum deschid un tichet?", "Cum mă autentific?"],
        products=[],
    )


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
    raw_message = payload.message.strip()
    message = normalize_text(raw_message)

    if not raw_message:
        raise HTTPException(status_code=400, detail="Mesajul nu poate fi gol")

    intent = detect_assistant_intent(
    message,
    payload.context_products,
    payload.focused_product,
    )

    if intent == "product_comparison":
        comparison_reply = compare_context_products(payload.context_products)
        return AssistantChatResponse(
            reply=comparison_reply,
            intent="product_comparison",
            suggestions=[
                "Ce recomanzi pentru începători?",
                "Ce recomanzi pentru pescuit la crap?",
                "Arată-mi promoțiile",
            ],
            products=[],
        )

    if intent == "thanks":
        return AssistantChatResponse(
            reply=(
                "Cu plăcere! Dacă mai ai nevoie, te pot ajuta în continuare cu promoții, "
                "recomandări de produse, coș, comenzi sau tichete."
            ),
            intent="thanks",
            suggestions=[
                "Arată-mi promoțiile",
                "Ce recomanzi pentru începători?",
                "Care este ultima mea comandă?",
                "Cum deschid un tichet?",
            ],
            products=[],
        )

    if intent == "product_detail_question":
        detail_reply = explain_context_product(
            message,
            payload.context_products,
            payload.focused_product,
            )
        return AssistantChatResponse(
            reply=detail_reply,
            intent="product_detail_question",
            suggestions=[
                "Ce recomanzi pentru începători?",
                "Ce recomanzi pentru pescuit la crap?",
                "Arată-mi promoțiile",
            ],
            products=[],
        )
    
    if is_product_comparison_question(message) and len(payload.context_products) >= 2:
        reply = compare_context_products(payload.context_products)

        return AssistantChatResponse(
            reply=reply,
            intent="product_comparison",
            suggestions=[]
        )

    if intent == "greeting":
        return AssistantChatResponse(
            reply=(
                "Salut! Eu sunt FishBot. Te pot ajuta cu promoții, recomandări pentru începători, "
                "recomandări pentru pescuit la crap, autentificare, coș, comenzi și tichete."
            ),
            intent="greeting",
            suggestions=[
                "Arată-mi promoțiile",
                "Ce recomanzi pentru începători?",
                "Ce recomanzi pentru pescuit la crap?",
                "Cum deschid un tichet?",
            ],
            products=[],
        )

    if intent == "promotions":
        products = get_top_promotions(db)
        if not products:
            return AssistantChatResponse(
                reply="În acest moment nu am găsit produse aflate la promoție.",
                intent="products_on_promotion",
                suggestions=[
                    "Cum comand?",
                    "Cum deschid un tichet?",
                    "Cum mă autentific?",
                ],
                products=[],
            )

        return AssistantChatResponse(
            reply="Acestea sunt câteva dintre produsele aflate acum la promoție.",
            intent="products_on_promotion",
            suggestions=[
                "Ce recomanzi pentru începători?",
                "Ce recomanzi pentru pescuit la crap?",
                "Cum deschid un tichet?",
            ],
            products=[serialize_assistant_product(product) for product in products],
        )

    if intent == "general_recommendation":
        recommended_products = (
            db.query(ProductDB)
            .filter(ProductDB.quantity > 0)
            .order_by(ProductDB.promotion.desc(), ProductDB.price.asc())
            .limit(4)
            .all()
        )

        return AssistantChatResponse(
            reply=(
                "Îți pot recomanda câteva produse populare și avantajoase ca preț. "
                "Dacă vrei o recomandare mai precisă, spune-mi dacă ești începător, "
                "dacă pescuiești la crap sau ce buget ai."
            ),
            intent="general_recommendation",
            suggestions=[
                "Ce recomanzi pentru începători?",
                "Ce recomanzi pentru pescuit la crap?",
                "Produse sub 200 lei",
            ],
            products=[serialize_assistant_product(product) for product in recommended_products],
        )

    if intent == "budget":
        budget = detect_budget_from_text(message)
        if budget is None:
            return AssistantChatResponse(
                reply="Spune-mi un buget, de exemplu «produse sub 200 lei», și îți arăt câteva variante.",
                intent="products_under_budget",
                suggestions=[
                    "Produse sub 200 lei",
                    "Arată-mi promoțiile",
                    "Cum deschid un tichet?",
                ],
                products=[],
            )

        products = get_products_under_budget(db, budget)
        if not products:
            return AssistantChatResponse(
                reply=f"Nu am găsit momentan produse disponibile sub {budget} lei.",
                intent="products_under_budget",
                suggestions=[
                    "Arată-mi promoțiile",
                    "Ce recomanzi pentru începători?",
                    "Cum deschid un tichet?",
                ],
                products=[],
            )

        return AssistantChatResponse(
            reply=f"Am găsit câteva produse disponibile sub {budget} lei.",
            intent="products_under_budget",
            suggestions=[
                "Arată-mi promoțiile",
                "Ce recomanzi pentru începători?",
                "Cum deschid un tichet?",
            ],
            products=[serialize_assistant_product(product) for product in products],
        )

    if intent == "carp_recommendation":
        products = get_products_for_style(db, "crap")
        return AssistantChatResponse(
            reply=(
                "Pentru pescuitul la crap, îți recomand în general lansete, mulinete, nade și momeli. "
                "Uite câteva produse care s-ar putea potrivi."
            ),
            intent="products_for_carp",
            suggestions=[
                "Arată-mi promoțiile",
                "Produse sub 200 lei",
                "Cum deschid un tichet?",
            ],
            products=[serialize_assistant_product(product) for product in products],
        )

    if intent == "beginner_recommendation":
        beginner_products = (
            db.query(ProductDB)
            .filter(ProductDB.quantity > 0)
            .order_by(ProductDB.price.asc())
            .limit(4)
            .all()
        )
        return AssistantChatResponse(
            reply=(
                "Pentru un începător, aș recomanda produse accesibile ca preț și ușor de folosit. "
                "Uite câteva variante bune pentru început."
            ),
            intent="beginner_recommendation",
            suggestions=[
                "Produse sub 150 lei",
                "Arată-mi promoțiile",
                "Cum deschid un tichet?",
            ],
            products=[serialize_assistant_product(product) for product in beginner_products],
        )

    if intent == "products_by_category":
        category = detect_category_from_text(message)
        if category:
            products = get_products_by_category(db, category)
            if not products:
                return AssistantChatResponse(
                    reply=f"Nu am găsit momentan produse disponibile în categoria {category}.",
                    intent="products_by_category",
                    suggestions=[
                        "Arată-mi promoțiile",
                        "Ce recomanzi pentru începători?",
                        "Cum deschid un tichet?",
                    ],
                    products=[],
                )

            return AssistantChatResponse(
                reply=f"Am găsit câteva produse din categoria {category}.",
                intent="products_by_category",
                suggestions=[
                    "Arată-mi promoțiile",
                    "Ce recomanzi pentru începători?",
                    "Cum deschid un tichet?",
                ],
                products=[serialize_assistant_product(product) for product in products],
            )

    if intent == "cart_summary":
        if not current_user:
            return build_login_required_response(
                "Pentru a vedea ce produse ai în coș, trebuie să fii autentificat.",
                "cart_summary",
                ["Arată-mi promoțiile", "Cum deschid un tichet?", "Cum mă autentific?"],
            )

        cart = build_cart_response(db, current_user)
        total_items = sum(item.quantity for item in cart.items)

        if total_items == 0:
            return AssistantChatResponse(
                reply="Coșul tău este gol în acest moment.",
                intent="cart_summary",
                suggestions=[
                    "Arată-mi promoțiile",
                    "Ce recomanzi pentru începători?",
                    "Cum deschid un tichet?",
                ],
                products=[],
            )

        names = ", ".join(item.product_name for item in cart.items[:3])
        extra = ""
        if len(cart.items) > 3:
            extra = f" și încă {len(cart.items) - 3} produse"

        return AssistantChatResponse(
            reply=(
                f"Ai {total_items} produse în coș, în valoare totală de {format_price(cart.total)}. "
                f"În coș se află: {names}{extra}."
            ),
            intent="cart_summary",
            suggestions=[
                "Care este ultima mea comandă?",
                "Arată-mi promoțiile",
                "Cum comand?",
            ],
            products=[],
        )

    if intent == "last_order":
        if not current_user:
            return build_login_required_response(
                "Pentru a verifica comenzile tale, trebuie să fii autentificat.",
                "last_order",
                ["Cum mă autentific?", "Cum comand?", "Cum deschid un tichet?"],
            )

        latest_order = (
            db.query(OrderDB)
            .options(joinedload(OrderDB.items))
            .filter(OrderDB.user_id == current_user.id)
            .order_by(OrderDB.created_at.desc(), OrderDB.id.desc())
            .first()
        )

        if not latest_order:
            return AssistantChatResponse(
                reply="Nu am găsit încă nicio comandă în contul tău.",
                intent="last_order",
                suggestions=[
                    "Arată-mi promoțiile",
                    "Ce recomanzi pentru începători?",
                    "Cum comand?",
                ],
                products=[],
            )

        item_count = sum(item.quantity for item in latest_order.items)
        return AssistantChatResponse(
            reply=(
                f"Ultima ta comandă este {latest_order.order_number}, are statusul "
                f"„{latest_order.status}”, conține {item_count} produse și are totalul de "
                f"{format_price(latest_order.total)}."
            ),
            intent="last_order",
            suggestions=[
                "Ce am în coș?",
                "Cum deschid un tichet?",
                "Arată-mi promoțiile",
            ],
            products=[],
        )

    if intent == "login_help":
        return AssistantChatResponse(
            reply=(
                "Pentru autentificare, apasă pe butonul de login din site și introdu datele contului tău. "
                "Dacă nu ai cont încă, poți să îți creezi unul din pagina de înregistrare."
            ),
            intent="faq_login_help",
            suggestions=[
                "Cum comand?",
                "Cum deschid un tichet?",
                "Arată-mi promoțiile",
            ],
            products=[],
        )

    if intent == "ticket_help":
        if not current_user:
            return build_login_required_response(
                "Ca să poți deschide un tichet, trebuie mai întâi să te autentifici. După autentificare, intri în secțiunea „Tichetele mele” și creezi un tichet nou.",
                "ticket_help",
                ["Arată-mi promoțiile", "Cum comand?", "Cum mă autentific?"],
            )

        availability = (
            db.query(TicketDB)
            .filter(TicketDB.user_id == current_user.id)
            .order_by(TicketDB.created_at.desc(), TicketDB.id.desc())
            .first()
        )

        if availability and availability.created_at:
            allowed_at = availability.created_at + timedelta(hours=TICKET_CREATE_COOLDOWN_HOURS)
            remaining = int((allowed_at - datetime.utcnow()).total_seconds())
            if remaining > 0:
                hours = remaining // 3600
                minutes = (remaining % 3600) // 60
                return AssistantChatResponse(
                    reply=(
                        f"Poți deschide un nou tichet din secțiunea „Tichetele mele”. "
                        f"Momentan mai trebuie să aștepți aproximativ {hours}h și {minutes}m."
                    ),
                    intent="ticket_help",
                    suggestions=[
                        "Am tichete deschise?",
                        "Ce am în coș?",
                        "Arată-mi promoțiile",
                    ],
                    products=[],
                )

        return AssistantChatResponse(
            reply=(
                "Poți deschide un tichet din secțiunea „Tichetele mele”. "
                "Alege categoria potrivită și descrie problema cât mai clar."
            ),
            intent="ticket_help",
            suggestions=[
                "Am tichete deschise?",
                "Arată-mi promoțiile",
                "Cum comand?",
            ],
            products=[],
        )

    if intent == "ticket_status":
        if not current_user:
            return build_login_required_response(
                "Pentru a verifica tichetele tale, trebuie să fii autentificat.",
                "ticket_status",
                ["Cum deschid un tichet?", "Arată-mi promoțiile", "Cum mă autentific?"],
            )

        open_tickets_count = (
            db.query(func.count(TicketDB.id))
            .filter(TicketDB.user_id == current_user.id, TicketDB.status == "open")
            .scalar()
        ) or 0

        if open_tickets_count == 0:
            return AssistantChatResponse(
                reply="Nu ai tichete deschise în acest moment.",
                intent="ticket_status",
                suggestions=[
                    "Cum deschid un tichet?",
                    "Arată-mi promoțiile",
                    "Ce am în coș?",
                ],
                products=[],
            )

        return AssistantChatResponse(
            reply=f"Ai {open_tickets_count} tichet(e) deschise în acest moment.",
            intent="ticket_status",
            suggestions=[
                "Cum deschid un tichet?",
                "Care este ultima mea comandă?",
                "Ce am în coș?",
            ],
            products=[],
        )

    if intent == "order_help":
        return AssistantChatResponse(
            reply=(
                "Pentru a plasa o comandă, intri pe produsul dorit sau îl adaugi direct din listă în coș, "
                "apoi accesezi coșul și finalizezi comanda."
            ),
            intent="faq_order_help",
            suggestions=[
                "Ce am în coș?",
                "Arată-mi promoțiile",
                "Cum deschid un tichet?",
            ],
            products=[],
        )

    if intent == "support_info":
        return AssistantChatResponse(
            reply=(
                "Pentru întrebări legate de livrare, retur sau plată, te pot ajuta cu informații generale. "
                "Dacă problema ta este specifică unei comenzi, îți recomand să deschizi un tichet din secțiunea „Tichetele mele”."
            ),
            intent="faq_support",
            suggestions=[
                "Cum deschid un tichet?",
                "Care este ultima mea comandă?",
                "Arată-mi promoțiile",
            ],
            products=[],
        )

    return AssistantChatResponse(
        reply=(
            "Nu sunt sigur că am înțeles corect întrebarea. Te pot ajuta cu promoții, recomandări pentru începători, "
            "recomandări pentru pescuit la crap, autentificare, coș, comenzi și tichete. Dacă ai o problemă specifică, te rog deschide un tichet."
        ),
        intent="fallback_to_ticket",
        suggestions=[
            "Arată-mi promoțiile",
            "Ce recomanzi pentru începători?",
            "Ce recomanzi pentru pescuit la crap?",
            "Cum deschid un tichet?",
        ],
        products=[],
    )