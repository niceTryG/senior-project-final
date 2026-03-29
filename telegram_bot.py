import logging
from typing import List, Callable, Optional
from functools import wraps
from datetime import datetime, date, timedelta

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    Updater,
    CommandHandler,
    CallbackContext,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    Filters,
)

from app import create_app, db
import app.telegram_config as telegram_config

from app.models import (
    Product,
    ShopStock,
    ShopOrder,
    ShopOrderItem,
    StockMovement,
    Sale,
    TelegramLink,
    TelegramLinkCode,
    CashRecord,
    Production,
    Movement,
)
from app.services.shop_service import ShopService


# ------------------------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = telegram_config.TELEGRAM_BOT_TOKEN

MANAGER_CHAT_IDS: List[int] = getattr(telegram_config, "MANAGER_CHAT_IDS", [])
DEFAULT_FACTORY_ID: int = getattr(telegram_config, "DEFAULT_FACTORY_ID", 1)
LOW_STOCK_THRESHOLD: int = getattr(telegram_config, "LOW_STOCK_THRESHOLD", 5)
DEFAULT_CASH_CURRENCY: str = getattr(telegram_config, "DEFAULT_CASH_CURRENCY", "UZS")
# ------------------------------------------------------------------------------
# CONVERSATION STATES
# ------------------------------------------------------------------------------
# ------------------------------------------------------------------------------
# CONVERSATION STATES
# ------------------------------------------------------------------------------
SALE_SEARCH, SALE_PICK, SALE_QTY, SALE_CONFIRM = range(4)
CASH_KIND, CASH_AMOUNT, CASH_NOTE, CASH_CONFIRM = range(4, 8)
PROD_SEARCH, PROD_PICK, PROD_QTY, PROD_CONFIRM = range(8, 12)
MOVE_SEARCH, MOVE_PICK, MOVE_QTY, MOVE_CONFIRM = range(12, 16)
# ------------------------------------------------------------------------------
# FLASK APP + LOGGING
# ------------------------------------------------------------------------------
flask_app = create_app()
shop_service = ShopService()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ------------------------------------------------------------------------------
# CONVERSATION STATES
# ------------------------------------------------------------------------------

# ------------------------------------------------------------------------------
# HELPERS
# ------------------------------------------------------------------------------

def with_flask_context(func: Callable) -> Callable:
    """Run handler inside Flask app_context so db/models work."""
    @wraps(func)
    def wrapper(update: Update, context: CallbackContext, *args, **kwargs):
        with flask_app.app_context():
            return func(update, context, *args, **kwargs)
    return wrapper


def is_manager(chat_id: int) -> bool:
    """
    Access control:
      - chat IDs in MANAGER_CHAT_IDS are always allowed
      - linked MiniModa users are also allowed
      - everyone else can only use /start, /help, /id and /link
    """
    if MANAGER_CHAT_IDS and chat_id in MANAGER_CHAT_IDS:
        return True
    return get_link(chat_id) is not None


def deny_if_not_manager_message(update: Update) -> bool:
    chat_id = update.effective_chat.id
    if not is_manager(chat_id):
        if update.message:
            update.message.reply_text(
                "Нет доступа.\n\n"
                "Войдите в MiniModa, откройте Профиль, сгенерируйте Telegram-код и отправьте сюда /link CODE."
            )
        return True
    return False


def deny_if_not_manager_callback(query, chat_id: int) -> bool:
    if not is_manager(chat_id):
        query.answer("Сначала привяжите аккаунт через /link CODE", show_alert=True)
        return True
    return False


def get_link(chat_id: int) -> Optional["TelegramLink"]:
    return TelegramLink.query.filter_by(telegram_chat_id=chat_id).first()


def resolve_factory_id(chat_id: int) -> int:
    """
    Prefer linked factory_id. If not linked, fallback to DEFAULT_FACTORY_ID.
    Read-only commands can still work with default factory.
    """
    link = get_link(chat_id)
    if link and getattr(link, "factory_id", None):
        return link.factory_id
    return DEFAULT_FACTORY_ID


def get_linked_user(chat_id: int):
    """
    We rely on TelegramLink.user relationship.
    This is needed so Telegram sales are recorded by a real MiniModa user.
    """
    link = get_link(chat_id)
    if not link:
        return None
    return getattr(link, "user", None)


def get_user_role(chat_id: int) -> Optional[str]:
    if MANAGER_CHAT_IDS and chat_id in MANAGER_CHAT_IDS:
        return "manager"

    user = get_linked_user(chat_id)
    role = getattr(user, "role", None) if user else None
    return str(role) if role else None


def is_shop_user(chat_id: int) -> bool:
    return get_user_role(chat_id) == "shop"


def resolve_shop_id(chat_id: int) -> Optional[int]:
    user = get_linked_user(chat_id)
    if not user:
        return None

    shop_id = getattr(user, "shop_id", None)
    try:
        return int(shop_id) if shop_id else None
    except (TypeError, ValueError):
        return None


def can_access_action(chat_id: int, action: str) -> bool:
    role = get_user_role(chat_id)
    if not role:
        return False

    if MANAGER_CHAT_IDS and chat_id in MANAGER_CHAT_IDS:
        return True

    allowed = {
        "general": {"admin", "manager", "shop", "accountant"},
        "sale": {"admin", "manager", "shop"},
        "cash": {"admin", "manager", "accountant"},
        "production": {"admin", "manager"},
        "move": {"admin", "manager"},
    }
    return role in allowed.get(action, allowed["general"])


def require_link_for_writes(update: Update, action: str = "general") -> bool:
    """
    For actions that change DB (sale/cash/etc), require linking,
    otherwise we might write into wrong factory/user context.
    """
    chat_id = update.effective_chat.id
    link = get_link(chat_id)
    if not (link and getattr(link, "factory_id", None)):
        if update.message:
            update.message.reply_text(
                "Bot is not linked to a MiniModa account yet.\n\n"
                "Open MiniModa -> Profile -> Telegram code\n"
                "Then send here:\n"
                "/link CODE"
            )
        elif update.callback_query:
            update.callback_query.answer("Use /link CODE first", show_alert=True)
        return False

    if not can_access_action(chat_id, action):
        if update.message:
            update.message.reply_text("This Telegram-linked user does not have permission for that action.")
        elif update.callback_query:
            update.callback_query.answer("No permission for this action", show_alert=True)
        return False

    return True

    if update.message:
        update.message.reply_text(
            "❗️Бот не привязан к аккаунту.\n\n"
            "Открой MiniModa → Профиль → Telegram код\n"
            "И отправь сюда:\n"
            "/link CODE\n\n"
            "После привязки будут доступны продажи и касса."
        )
    elif update.callback_query:
        update.callback_query.answer("Нужно /link CODE", show_alert=True)

    return False


def format_money(amount, currency: str = "UZS") -> str:
    try:
        value = float(amount or 0)
    except Exception:
        value = 0.0
    return f"{value:,.2f} {currency}".replace(",", " ")


def neo_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Dashboard", callback_data="m:dash")],
        [InlineKeyboardButton("🏭 Add production", callback_data="m:prod")],
        [InlineKeyboardButton("🚚 Move to shop", callback_data="m:move")],
        [InlineKeyboardButton("📦 Shop stock", callback_data="m:shop_stock"),
         InlineKeyboardButton("⚠️ Low stock", callback_data="m:shop_low")],
        [InlineKeyboardButton("📬 Pending orders", callback_data="m:pending")],
        [InlineKeyboardButton("🧾 Quick sale", callback_data="m:sale")],
        [InlineKeyboardButton("💵 Cash record", callback_data="m:cash")],
        [InlineKeyboardButton("📜 Last moves", callback_data="m:moves")],
        [InlineKeyboardButton("🔎 Products", callback_data="m:product")],
    ])


def shop_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Shop dashboard", callback_data="m:dash")],
        [InlineKeyboardButton("Quick sale", callback_data="m:sale")],
        [InlineKeyboardButton("Shop stock", callback_data="m:shop_stock"),
         InlineKeyboardButton("Low stock", callback_data="m:shop_low")],
        [InlineKeyboardButton("Sales today", callback_data="m:sales_today"),
         InlineKeyboardButton("Pending orders", callback_data="m:pending")],
        [InlineKeyboardButton("Last moves", callback_data="m:moves"),
         InlineKeyboardButton("Products", callback_data="m:product")],
    ])


def menu_kb_for_chat(chat_id: int) -> InlineKeyboardMarkup:
    return shop_menu_kb() if is_shop_user(chat_id) else neo_menu_kb()


def panel_title_for_chat(chat_id: int) -> str:
    return "MiniModa Shop Panel" if is_shop_user(chat_id) else "MiniModa Control Panel"


def manager_reply_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            ["/menu", "/alerts"],
            ["/sales_today", "/shop_low"],
            ["/shop_stock", "/pending"],
            ["/last_moves", "/product"],
            ["/link", "/id"],
        ],
        resize_keyboard=True,
    )


def shop_reply_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            ["/menu", "/sales_today"],
            ["/shop_stock", "/shop_low"],
            ["/pending", "/product"],
            ["/alerts", "/last_moves"],
            ["/link", "/id"],
        ],
        resize_keyboard=True,
    )


def back_to_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Back to menu", callback_data="m:menu")]
    ])


def _sale_amount(sale, product) -> float:
    """
    Same idea as shop_routes.py:
    prefer Sale.total_sell, otherwise qty * sell_price_per_item.
    """
    if hasattr(sale, "total_sell") and sale.total_sell is not None:
        try:
            return float(sale.total_sell or 0)
        except Exception:
            return 0.0

    qty = getattr(sale, "quantity", 0) or 0
    price = getattr(sale, "sell_price_per_item", None)
    if price is None:
        price = getattr(product, "sell_price_per_item", 0) or 0

    try:
        return float(qty) * float(price)
    except Exception:
        return 0.0


def _get_today_sales_summary(factory_id: int, shop_id: Optional[int] = None):
    """
    Returns:
      total_amount_uzs, tx_count
    Works with Sale.factory_id if exists, else via Product.factory_id.
    """
    today = date.today()

    q = db.session.query(Sale, Product).join(Product, Product.id == Sale.product_id)

    if shop_id is not None and hasattr(Sale, "shop_id"):
        q = q.filter(Sale.shop_id == shop_id)
    elif hasattr(Sale, "factory_id"):
        q = q.filter(Sale.factory_id == factory_id)
    else:
        q = q.filter(Product.factory_id == factory_id)

    rows = q.all()

    total_amount = 0.0
    tx_count = 0

    for sale, product in rows:
        s_date = None
        if hasattr(sale, "date") and sale.date:
            s_date = sale.date
        elif hasattr(sale, "created_at") and sale.created_at:
            try:
                s_date = sale.created_at.date()
            except Exception:
                s_date = None

        if s_date != today:
            continue

        total_amount += _sale_amount(sale, product)
        tx_count += 1

    return total_amount, tx_count


def _shop_stock_rows_query(chat_id: int):
    q = db.session.query(ShopStock).join(Product, Product.id == ShopStock.product_id)

    shop_id = resolve_shop_id(chat_id)
    if shop_id:
        return q.filter(ShopStock.shop_id == shop_id)

    return q.filter(Product.factory_id == resolve_factory_id(chat_id))


def _visible_products_query(chat_id: int):
    shop_id = resolve_shop_id(chat_id)
    if shop_id:
        return (
            Product.query
            .join(ShopStock, ShopStock.product_id == Product.id)
            .filter(ShopStock.shop_id == shop_id)
            .distinct()
        )

    return Product.query.filter_by(factory_id=resolve_factory_id(chat_id))


def _get_shop_qty(product_id: int, chat_id: Optional[int] = None) -> int:
    q = ShopStock.query.filter_by(product_id=product_id)

    if chat_id is not None:
        shop_id = resolve_shop_id(chat_id)
        if shop_id:
            q = q.filter(ShopStock.shop_id == shop_id)
        else:
            q = q.join(Product, Product.id == ShopStock.product_id).filter(
                Product.factory_id == resolve_factory_id(chat_id)
            )

    rows = q.all()
    return sum(int(row.quantity or 0) for row in rows)


def _get_linked_shop_stock_row(chat_id: int, product_id: int):
    shop_id = resolve_shop_id(chat_id)
    if not shop_id:
        return None

    return (
        ShopStock.query
        .filter_by(shop_id=shop_id, product_id=product_id)
        .order_by(ShopStock.quantity.desc(), ShopStock.id.asc())
        .first()
    )


def _safe_product_code(product_id: int) -> str:
    try:
        return f"MM-{int(product_id):05d}"
    except Exception:
        return str(product_id)


# ------------------------------------------------------------------------------
# BASIC COMMANDS: /start, /help, /id, /menu
# ------------------------------------------------------------------------------

@with_flask_context
def chat_id_cmd(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id
    logger.info("User requested /id, chat_id=%s", chat_id)

    text = (
        f"Ваш chat_id: <b>{chat_id}</b>\n\n"
        "Чтобы привязать аккаунт, откройте MiniModa → Профиль, "
        "сгенерируйте Telegram-код и отправьте сюда:\n"
        "<code>/link CODE</code>"
    )
    update.message.reply_html(text)


@with_flask_context
def start(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id
    logger.info("Received /start from chat_id=%s", chat_id)

    if is_manager(chat_id) and is_shop_user(chat_id):
        update.message.reply_text(
            "MiniModa Shop Bot\n\n"
            "Main commands:\n"
            "/menu - shop panel\n"
            "/sales_today - sales today\n"
            "/shop_stock - current shop stock\n"
            "/shop_low - low stock\n"
            "/pending - pending orders\n"
            "/last_moves - recent stock moves\n"
            "/product name - find products\n"
            "/link CODE - relink Telegram\n"
            "/id - your chat id",
            reply_markup=shop_reply_kb(),
        )
        return

    if is_manager(chat_id):
        keyboard = [
            ["/alerts", "/sales_today"],
            ["/shop_low", "/shop_stock"],
            ["/pending", "/last_moves"],
            ["/product", "/menu"],
            ["/link", "/id"],
        ]
        reply_kb = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

        update.message.reply_text(
            "Ассаламу алейкум!\n\n"
            "MiniModa Manager Bot (Neo).\n\n"
            "Команды:\n"
            "• /menu — красивое меню\n"
            "• /alerts — общий обзор\n"
            "• /sales_today — продажи за сегодня\n"
            "• /shop_low — низкий остаток в магазине\n"
            "• /shop_stock [слово] — остатки магазина\n"
            "• /pending — pending заказы\n"
            "• /last_moves — последние движения\n"
            "• /product [текст] — поиск моделей\n"
            "• /link CODE — перепривязать Telegram к аккаунту\n"
            "• /id — ваш chat_id\n",
            reply_markup=reply_kb,
        )
        return

    keyboard = [["/link", "/id"]]
    reply_kb = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    update.message.reply_text(
        "Ассаламу алейкум!\n\n"
        "Чтобы получить доступ к MiniModa Bot:\n"
        "1. Войдите в сайт MiniModa\n"
        "2. Откройте Профиль\n"
        "3. Сгенерируйте Telegram-код\n"
        "4. Отправьте сюда: /link CODE\n\n"
        "Пока доступны только:\n"
        "• /link CODE\n"
        "• /id\n",
        reply_markup=reply_kb,
    )


@with_flask_context
def help_cmd(update: Update, context: CallbackContext) -> None:
    return start(update, context)


@with_flask_context
def menu_cmd(update: Update, context: CallbackContext) -> None:
    if deny_if_not_manager_message(update):
        return
    chat_id = update.effective_chat.id
    update.message.reply_text(panel_title_for_chat(chat_id), reply_markup=menu_kb_for_chat(chat_id))


# ------------------------------------------------------------------------------
# /link CODE — account linking
# ------------------------------------------------------------------------------

@with_flask_context
def link_cmd(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id
    if not context.args:
        update.message.reply_text("Использование: /link CODE")
        return

    code_value = context.args[0].strip()
    code = TelegramLinkCode.query.filter_by(code=code_value).first()

    if not code:
        update.message.reply_text("❌ Код не найден.")
        return

    if getattr(code, "used_at", None):
        update.message.reply_text("❌ Этот код уже использован.")
        return

    if getattr(code, "expires_at", None) and code.expires_at < datetime.utcnow():
        update.message.reply_text("❌ Код истёк. Сгенерируй новый в MiniModa.")
        return

    TelegramLink.query.filter_by(telegram_chat_id=chat_id).delete()
    TelegramLink.query.filter_by(user_id=code.user_id).delete(synchronize_session=False)

    link = TelegramLink(
        telegram_chat_id=chat_id,
        user_id=code.user_id,
        factory_id=code.factory_id,
    )

    code.used_at = datetime.utcnow()
    db.session.add(link)
    db.session.commit()

    update.message.reply_text("✅ Telegram успешно привязан!")
    update.message.reply_text(panel_title_for_chat(chat_id), reply_markup=menu_kb_for_chat(chat_id))


# ------------------------------------------------------------------------------
# /alerts
# ------------------------------------------------------------------------------

@with_flask_context
def alerts(update: Update, context: CallbackContext) -> None:
    if deny_if_not_manager_message(update):
        return

    chat_id = update.effective_chat.id
    factory_id = resolve_factory_id(chat_id)
    shop_id = resolve_shop_id(chat_id)
    shop_id = resolve_shop_id(chat_id)

    low_count = _shop_stock_rows_query(chat_id).filter(
        ShopStock.quantity < LOW_STOCK_THRESHOLD
    ).count()

    pending_count = (
        ShopOrder.query
        .filter_by(factory_id=factory_id, status="pending")
        .count()
    )

    sales_today_total, sales_today_count = _get_today_sales_summary(factory_id, shop_id=shop_id)

    last_mv = (
        StockMovement.query
        .filter_by(factory_id=factory_id)
        .order_by(StockMovement.timestamp.desc())
        .first()
    )
    last_mv_str = (
        last_mv.timestamp.strftime("%d.%m %H:%M")
        if last_mv and last_mv.timestamp
        else "нет данных"
    )

    txt = (
        "📊 Краткий обзор\n\n"
        f"• Продажи сегодня: {sales_today_count} шт. записей\n"
        f"• Сумма сегодня: {format_money(sales_today_total, 'UZS')}\n"
        f"• Низкий остаток (<{LOW_STOCK_THRESHOLD}): {low_count}\n"
        f"• Pending заказы: {pending_count}\n"
        f"• Последнее движение: {last_mv_str}\n\n"
        "Подробнее:\n"
        "— /sales_today\n"
        "— /shop_low\n"
        "— /pending\n"
        "— /last_moves\n"
        "— /menu"
    )
    update.message.reply_text(txt)


# ------------------------------------------------------------------------------
# /sales_today
# ------------------------------------------------------------------------------

@with_flask_context
def sales_today_cmd(update: Update, context: CallbackContext) -> None:
    if deny_if_not_manager_message(update):
        return

    chat_id = update.effective_chat.id
    factory_id = resolve_factory_id(chat_id)
    total_amount, tx_count = _get_today_sales_summary(factory_id, shop_id=resolve_shop_id(chat_id))

    update.message.reply_text(
        "💸 Продажи за сегодня\n\n"
        f"• Кол-во записей: {tx_count}\n"
        f"• Общая сумма: {format_money(total_amount, 'UZS')}"
    )


# ------------------------------------------------------------------------------
# /shop_low
# ------------------------------------------------------------------------------

@with_flask_context
def shop_low(update: Update, context: CallbackContext) -> None:
    if deny_if_not_manager_message(update):
        return

    chat_id = update.effective_chat.id

    low_items = (
        _shop_stock_rows_query(chat_id)
        .filter(ShopStock.quantity < LOW_STOCK_THRESHOLD)
        .order_by(ShopStock.quantity.asc(), Product.name.asc())
        .all()
    )

    if not low_items:
        update.message.reply_text("В магазине нет товаров с низким остатком. 👍")
        return

    lines = [f"⚠️ Товары с остатком < {LOW_STOCK_THRESHOLD} в магазине:\n"]
    for row in low_items:
        p: Product = row.product
        lines.append(
            f"• {_safe_product_code(p.id)} | {p.name} ({p.category or '-'}) — "
            f"{row.quantity} шт. | {p.sell_price_per_item or 0} {p.currency}"
        )

    update.message.reply_text("\n".join(lines))


# ------------------------------------------------------------------------------
# /shop_stock [filter]
# ------------------------------------------------------------------------------

@with_flask_context
def shop_stock(update: Update, context: CallbackContext) -> None:
    if deny_if_not_manager_message(update):
        return

    chat_id = update.effective_chat.id

    args = context.args
    search = " ".join(args).strip().lower() if args else None

    query = (
        _shop_stock_rows_query(chat_id)
        .filter(ShopStock.quantity > 0)
        .order_by(ShopStock.quantity.desc(), Product.name.asc())
    )

    if search:
        query = query.filter(Product.name.ilike(f"%{search}%"))

    items = query.limit(25).all()

    if not items:
        update.message.reply_text(
            f"Ничего не найдено по запросу: “{search}”." if search else "В магазине нет товаров с остатком > 0."
        )
        return

    header = (
        f"📦 Остатки в магазине (поиск: “{search}”):\n"
        if search
        else "📦 Остатки в магазине (первые 25 позиций):\n"
    )

    lines = [header]
    for row in items:
        p: Product = row.product
        lines.append(
            f"• {_safe_product_code(p.id)} | {p.name} ({p.category or '-'}) — "
            f"{row.quantity} шт. | {p.sell_price_per_item or 0} {p.currency}"
        )

    update.message.reply_text("\n".join(lines))


# ------------------------------------------------------------------------------
# /pending
# ------------------------------------------------------------------------------

@with_flask_context
def pending(update: Update, context: CallbackContext) -> None:
    if deny_if_not_manager_message(update):
        return

    factory_id = resolve_factory_id(update.effective_chat.id)

    orders = (
        ShopOrder.query
        .filter_by(factory_id=factory_id, status="pending")
        .order_by(ShopOrder.created_at.asc())
        .limit(10)
        .all()
    )

    if not orders:
        update.message.reply_text("Нет заказов в статусе 'pending'. ✅")
        return

    lines = ["📬 Заказы магазина (pending):\n"]
    for o in orders:
        item_count = len(o.items) if hasattr(o, "items") and o.items else 0
        created = o.created_at.strftime("%d.%m %H:%M") if o.created_at else "?"
        customer = getattr(o, "customer_name", None) or "-"
        lines.append(f"• №{o.id}: {item_count} позиций, клиент: {customer}, создан {created}")

    update.message.reply_text("\n".join(lines))


# ------------------------------------------------------------------------------
# /last_moves
# ------------------------------------------------------------------------------

@with_flask_context
def last_moves(update: Update, context: CallbackContext) -> None:
    if deny_if_not_manager_message(update):
        return

    factory_id = resolve_factory_id(update.effective_chat.id)

    moves = (
        StockMovement.query
        .filter_by(factory_id=factory_id)
        .order_by(StockMovement.timestamp.desc())
        .limit(10)
        .all()
    )

    if not moves:
        update.message.reply_text("Пока нет движений по складу.")
        return

    lines = ["📜 Последние движения по складу:\n"]
    for mv in moves:
        ts = mv.timestamp.strftime("%d.%m %H:%M") if mv.timestamp else "?"
        product_name = mv.product.name if mv.product else "?"
        lines.append(
            f"• {ts} — {product_name}: {mv.qty_change:+} шт. "
            f"({mv.source or '-'} → {mv.destination or '-'})"
        )

    update.message.reply_text("\n".join(lines))


# ------------------------------------------------------------------------------
# /product [text]
# ------------------------------------------------------------------------------

@with_flask_context
def product_cmd(update: Update, context: CallbackContext) -> None:
    if deny_if_not_manager_message(update):
        return

    chat_id = update.effective_chat.id

    args = context.args
    search = " ".join(args).strip() if args else None

    base_q = _visible_products_query(chat_id)

    if search:
        products = (
            base_q.filter(Product.name.ilike(f"%{search}%"))
            .order_by(Product.name.asc())
            .limit(10)
            .all()
        )
    else:
        products = base_q.order_by(Product.name.asc()).limit(10).all()

    if not products:
        update.message.reply_text(
            f"Товары по запросу “{search}” не найдены." if search else "В базе нет товаров."
        )
        return

    header = (
        f"Найдено моделей (первые {len(products)}): “{search}”\n\nНажмите на нужную модель:"
        if search
        else f"Первые {len(products)} моделей:\n\nНажмите на нужную модель:"
    )

    buttons = []
    for p in products:
        btn_text = f"{p.name} ({p.category or '-'})"
        callback_data = f"prod:{p.id}"
        buttons.append([InlineKeyboardButton(btn_text, callback_data=callback_data)])

    keyboard = InlineKeyboardMarkup(buttons)
    update.message.reply_text(header, reply_markup=keyboard)


# ------------------------------------------------------------------------------
# Callback: product details
# ------------------------------------------------------------------------------

@with_flask_context
def product_detail_callback(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    data = query.data or ""
    chat_id = query.message.chat_id

    if deny_if_not_manager_callback(query, chat_id):
        return

    if not data.startswith("prod:"):
        query.answer()
        return

    try:
        product_id = int(data.split(":", 1)[1])
    except ValueError:
        query.answer("Ошибка ID товара", show_alert=True)
        return

    if is_shop_user(chat_id):
        product = _visible_products_query(chat_id).filter(Product.id == product_id).first()
    else:
        factory_id = resolve_factory_id(chat_id)
        product = (
            Product.query
            .filter_by(id=product_id, factory_id=factory_id)
            .first()
        )

    if not product:
        query.answer("Товар не найден", show_alert=True)
        return

    factory_qty = int(product.quantity or 0)
    shop_qty = _get_shop_qty(product.id, chat_id)
    total_qty = factory_qty + shop_qty

    text = (
        f"📦 <b>{product.name}</b>\n"
        f"Код: <code>{_safe_product_code(product.id)}</code>\n"
        f"Категория: {product.category or '-'}\n"
        f"Валюта: {product.currency}\n\n"
        f"На фабрике: <b>{factory_qty}</b> шт.\n"
        f"В магазине: <b>{shop_qty}</b> шт.\n"
        f"Итого: <b>{total_qty}</b> шт.\n\n"
        f"Себестоимость / 1: {product.cost_price_per_item or 0} {product.currency}\n"
        f"Цена продажи / 1: {product.sell_price_per_item or 0} {product.currency}\n"
    )

    query.answer()
    query.edit_message_text(text=text, parse_mode="HTML", reply_markup=back_to_menu_kb())


# ------------------------------------------------------------------------------
# NEO MENU CALLBACKS
# ------------------------------------------------------------------------------

@with_flask_context
def menu_callback(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    chat_id = query.message.chat_id
    data = query.data or ""

    if deny_if_not_manager_callback(query, chat_id):
        return

    if data == "m:menu":
        query.answer()
        query.edit_message_text(panel_title_for_chat(chat_id), reply_markup=menu_kb_for_chat(chat_id))
        return

    factory_id = resolve_factory_id(chat_id)

    if data == "m:dash":
        low_count = (
            _shop_stock_rows_query(chat_id)
            .filter(ShopStock.quantity < LOW_STOCK_THRESHOLD)
            .count()
        )

        pending_count = (
            ShopOrder.query
            .filter_by(factory_id=factory_id, status="pending")
            .count()
        )

        sales_today_total, sales_today_count = _get_today_sales_summary(factory_id, shop_id=shop_id)

        last_mv = (
            StockMovement.query
            .filter_by(factory_id=factory_id)
            .order_by(StockMovement.timestamp.desc())
            .first()
        )
        last_mv_str = last_mv.timestamp.strftime("%d.%m %H:%M") if last_mv and last_mv.timestamp else "нет данных"

        txt = (
            "📊 <b>Dashboard</b>\n\n"
            f"💸 Sales today: <b>{sales_today_count}</b>\n"
            f"💰 Amount today: <b>{format_money(sales_today_total, 'UZS')}</b>\n"
            f"⚠️ Low stock (&lt;{LOW_STOCK_THRESHOLD}): <b>{low_count}</b>\n"
            f"📬 Pending orders: <b>{pending_count}</b>\n"
            f"📜 Last movement: <b>{last_mv_str}</b>\n"
        )
        query.answer()
        query.edit_message_text(txt, parse_mode="HTML", reply_markup=back_to_menu_kb())
        return

    if data == "m:sales_today":
        total_amount, tx_count = _get_today_sales_summary(factory_id, shop_id=shop_id)
        txt = (
            "💸 <b>Sales today</b>\n\n"
            f"Записей: <b>{tx_count}</b>\n"
            f"Сумма: <b>{format_money(total_amount, 'UZS')}</b>"
        )
        query.answer()
        query.edit_message_text(txt, parse_mode="HTML", reply_markup=back_to_menu_kb())
        return

    if data == "m:shop_low":
        low_items = (
            _shop_stock_rows_query(chat_id)
            .filter(ShopStock.quantity < LOW_STOCK_THRESHOLD)
            .order_by(ShopStock.quantity.asc(), Product.name.asc())
            .limit(25)
            .all()
        )
        if not low_items:
            query.answer()
            query.edit_message_text("В магазине нет товаров с низким остатком. 👍", reply_markup=back_to_menu_kb())
            return

        lines = [f"⚠️ <b>Low stock</b> (&lt;{LOW_STOCK_THRESHOLD})\n"]
        for row in low_items:
            p: Product = row.product
            lines.append(f"• {_safe_product_code(p.id)} | {p.name} — <b>{row.quantity}</b> шт.")
        query.answer()
        query.edit_message_text("\n".join(lines), parse_mode="HTML", reply_markup=back_to_menu_kb())
        return

    if data == "m:pending":
        orders = (
            ShopOrder.query
            .filter_by(factory_id=factory_id, status="pending")
            .order_by(ShopOrder.created_at.asc())
            .limit(10)
            .all()
        )
        if not orders:
            query.answer()
            query.edit_message_text("Нет заказов в статусе 'pending'. ✅", reply_markup=back_to_menu_kb())
            return

        lines = ["📬 <b>Pending orders</b>\n"]
        for o in orders:
            created = o.created_at.strftime("%d.%m %H:%M") if o.created_at else "?"
            item_count = len(o.items) if getattr(o, "items", None) else 0
            customer = getattr(o, "customer_name", None) or "-"
            lines.append(f"• №{o.id} — {item_count} поз., {customer}, {created}")

        query.answer()
        query.edit_message_text("\n".join(lines), parse_mode="HTML", reply_markup=back_to_menu_kb())
        return

    if data == "m:moves":
        moves = (
            StockMovement.query
            .filter_by(factory_id=factory_id)
            .order_by(StockMovement.timestamp.desc())
            .limit(10)
            .all()
        )
        if not moves:
            query.answer()
            query.edit_message_text("Пока нет движений по складу.", reply_markup=back_to_menu_kb())
            return

        lines = ["📜 <b>Last moves</b>\n"]
        for mv in moves:
            ts = mv.timestamp.strftime("%d.%m %H:%M") if mv.timestamp else "?"
            product_name = mv.product.name if mv.product else "?"
            lines.append(
                f"• {ts} — {product_name}: {mv.qty_change:+} шт. "
                f"({mv.source or '-'} → {mv.destination or '-'})"
            )
        query.answer()
        query.edit_message_text("\n".join(lines), parse_mode="HTML", reply_markup=back_to_menu_kb())
        return

    if data == "m:shop_stock":
        items = (
            _shop_stock_rows_query(chat_id)
            .filter(ShopStock.quantity > 0)
            .order_by(ShopStock.quantity.desc(), Product.name.asc())
            .limit(25)
            .all()
        )
        if not items:
            query.answer()
            query.edit_message_text("В магазине нет товаров с остатком > 0.", reply_markup=back_to_menu_kb())
            return

        lines = ["📦 <b>Shop stock</b> (top 25)\n"]
        for row in items:
            p: Product = row.product
            lines.append(f"• {_safe_product_code(p.id)} | {p.name} — <b>{row.quantity}</b> шт.")
        query.answer()
        query.edit_message_text("\n".join(lines), parse_mode="HTML", reply_markup=back_to_menu_kb())
        return

    if data == "m:product":
        query.answer()
        query.edit_message_text(
            "🔎 Для поиска моделей напиши:\n\n"
            "/product bodik\n"
            "/product kofta\n\n"
            "Или просто /product для первых 10.",
            reply_markup=back_to_menu_kb(),
        )
        return

    query.answer()


# ------------------------------------------------------------------------------
# QUICK SALE WIZARD
# REAL MINI MODA SHOP LOGIC
# ------------------------------------------------------------------------------

@with_flask_context
def sale_entry_from_menu(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    chat_id = query.message.chat_id

    if deny_if_not_manager_callback(query, chat_id):
        return ConversationHandler.END

    if not require_link_for_writes(update, action="sale"):
        return ConversationHandler.END

    context.user_data.pop("sale_product_id", None)
    context.user_data.pop("sale_product_name", None)
    context.user_data.pop("sale_price", None)
    context.user_data.pop("sale_shop_qty", None)
    context.user_data.pop("sale_qty", None)

    query.answer()
    query.edit_message_text(
        "🧾 <b>Quick sale</b>\n\n"
        "Напиши название товара (например: bodik):",
        parse_mode="HTML"
    )
    return SALE_SEARCH


@with_flask_context
def sale_search_step(update: Update, context: CallbackContext) -> int:
    if deny_if_not_manager_message(update):
        return ConversationHandler.END

    if not require_link_for_writes(update, action="sale"):
        return ConversationHandler.END

    chat_id = update.effective_chat.id
    search = (update.message.text or "").strip()

    products = (
        _visible_products_query(chat_id)
        .filter(Product.name.ilike(f"%{search}%"))
        .order_by(Product.name.asc())
        .limit(10)
        .all()
    )

    if not products:
        update.message.reply_text("Ничего не найдено. Попробуй другое слово.")
        return SALE_SEARCH

    buttons = []
    for p in products:
        shop_qty = _get_shop_qty(p.id, chat_id)
        btn_label = f"{p.name} | shop: {shop_qty}"
        buttons.append([InlineKeyboardButton(btn_label, callback_data=f"sale_pick:{p.id}")])

    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="sale_cancel")])

    update.message.reply_text("Выбери товар:", reply_markup=InlineKeyboardMarkup(buttons))
    return SALE_PICK


@with_flask_context
def sale_pick_step(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    chat_id = query.message.chat_id

    if deny_if_not_manager_callback(query, chat_id):
        return ConversationHandler.END

    if query.data == "sale_cancel":
        query.answer()
        query.edit_message_text("Ок, отменено.", reply_markup=menu_kb_for_chat(chat_id))
        return ConversationHandler.END

    if not require_link_for_writes(update, action="sale"):
        return ConversationHandler.END

    try:
        product_id = int(query.data.split(":", 1)[1])
    except Exception:
        query.answer("Ошибка товара", show_alert=True)
        return ConversationHandler.END

    if is_shop_user(chat_id):
        product = _visible_products_query(chat_id).filter(Product.id == product_id).first()
    else:
        factory_id = resolve_factory_id(chat_id)
        product = Product.query.filter_by(id=product_id, factory_id=factory_id).first()
    if not product:
        query.answer("Товар не найден", show_alert=True)
        return ConversationHandler.END

    shop_qty = _get_shop_qty(product.id, chat_id)

    context.user_data["sale_product_id"] = product.id
    context.user_data["sale_product_name"] = product.name
    context.user_data["sale_price"] = float(product.sell_price_per_item or 0)
    context.user_data["sale_shop_qty"] = shop_qty
    context.user_data["sale_factory_id"] = int(product.factory_id or 0) or resolve_factory_id(chat_id)

    query.answer()
    query.edit_message_text(
        f"Товар: <b>{product.name}</b>\n"
        f"Код: <code>{_safe_product_code(product.id)}</code>\n"
        f"Цена: <b>{product.sell_price_per_item or 0}</b> {product.currency}\n"
        f"Сейчас в магазине: <b>{shop_qty}</b> шт.\n\n"
        "Теперь напиши количество (например: 3):\n\n"
        "Если введёшь больше, чем есть в магазине, бот оформит недостачу как заказ.",
        parse_mode="HTML"
    )
    return SALE_QTY


@with_flask_context
def sale_qty_step(update: Update, context: CallbackContext) -> int:
    if deny_if_not_manager_message(update):
        return ConversationHandler.END

    if not require_link_for_writes(update, action="sale"):
        return ConversationHandler.END

    txt = (update.message.text or "").strip()
    try:
        qty = int(txt)
        if qty <= 0:
            raise ValueError
    except ValueError:
        update.message.reply_text("Количество должно быть целым числом > 0. Попробуй ещё раз.")
        return SALE_QTY

    context.user_data["sale_qty"] = qty

    name = context.user_data.get("sale_product_name", "товар")
    price = context.user_data.get("sale_price", 0)
    shop_qty = context.user_data.get("sale_shop_qty", 0)

    total = float(price or 0) * qty

    extra_note = ""
    if qty > shop_qty:
        extra_note = (
            f"\n⚠️ В магазине сейчас только {shop_qty} шт.\n"
            f"Недостача будет оформлена как заказ."
        )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm sale", callback_data="sale_confirm")],
        [InlineKeyboardButton("❌ Cancel", callback_data="sale_cancel2")],
    ])

    update.message.reply_text(
        f"Подтверди продажу:\n\n"
        f"• Товар: {name}\n"
        f"• Кол-во: {qty}\n"
        f"• Цена: {price}\n"
        f"• Сумма: {total}\n"
        f"{extra_note}",
        reply_markup=kb
    )
    return SALE_CONFIRM


@with_flask_context
def sale_confirm_step(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    chat_id = query.message.chat_id

    if deny_if_not_manager_callback(query, chat_id):
        return ConversationHandler.END

    if query.data in ("sale_cancel2", "sale_cancel"):
        query.answer()
        query.edit_message_text("Ок, отменено.", reply_markup=menu_kb_for_chat(chat_id))
        return ConversationHandler.END

    if not require_link_for_writes(update, action="sale"):
        return ConversationHandler.END

    if query.data != "sale_confirm":
        query.answer()
        return SALE_CONFIRM

    factory_id = context.user_data.get("sale_factory_id") or resolve_factory_id(chat_id)
    product_id = context.user_data.get("sale_product_id")
    requested_qty = context.user_data.get("sale_qty")

    if not product_id or not requested_qty:
        query.answer("Нет данных продажи", show_alert=True)
        return ConversationHandler.END

    if is_shop_user(chat_id):
        product = Product.query.filter_by(id=product_id).first()
    else:
        product = Product.query.filter_by(id=product_id, factory_id=factory_id).first()
    if not product:
        query.answer("Товар не найден", show_alert=True)
        return ConversationHandler.END

    created_by = get_linked_user(chat_id)
    if not created_by or not getattr(created_by, "id", None):
        query.answer("Пользователь MiniModa не найден. Сделай /link заново.", show_alert=True)
        return ConversationHandler.END

    try:
        shop_stock = _get_linked_shop_stock_row(chat_id, product.id) if is_shop_user(chat_id) else None
        result = shop_service.sell_from_shop_or_create_order(
            factory_id=factory_id,
            product_id=product.id,
            requested_qty=requested_qty,
            customer_name="Telegram",
            customer_phone=None,
            note=f"Telegram bot chat_id={chat_id}",
            allow_partial_sale=True,
            created_by=created_by,
            shop_stock_id=getattr(shop_stock, "id", None),
        )
    except ValueError as e:
        query.answer(str(e), show_alert=True)
        return ConversationHandler.END
    except Exception as e:
        logger.exception("Telegram quick sale failed: %s", e)
        query.answer("Ошибка при продаже", show_alert=True)
        return ConversationHandler.END

    sale = result.get("sale")
    order = result.get("order")
    missing = result.get("missing", 0)
    sold_now = result.get("sold_now", 0)

    try:
        if sale:
            qty = sale.quantity or 0
            currency = getattr(sale, "currency", None) or getattr(product, "currency", "UZS")

            if getattr(sale, "total_sell", None) is not None:
                total_sell = sale.total_sell
            else:
                price = getattr(sale, "sell_price_per_item", None)
                if price is None:
                    price = getattr(product, "sell_price_per_item", 0) or 0
                total_sell = qty * price

            mv = StockMovement(
                factory_id=factory_id,
                product_id=product.id,
                qty_change=-qty,
                source="shop",
                destination="customer",
                movement_type="shop_sale",
                order_id=order.id if order else None,
                comment=f"Telegram sale {qty} pcs",
            )
            db.session.add(mv)

            sale_date = getattr(sale, "date", None) or date.today()

            cash_note = f"Продажа (telegram) #{sale.id}: {product.name} x{qty}"

            existing_cash = (
                CashRecord.query
                .filter_by(factory_id=factory_id, currency=currency)
                .filter(CashRecord.date == sale_date)
                .filter(CashRecord.amount == total_sell)
                .filter(CashRecord.note.ilike(f"%#{sale.id}%"))
                .first()
            )
            if not existing_cash:
                db.session.add(CashRecord(
                    factory_id=factory_id,
                    date=sale_date,
                    amount=total_sell,
                    currency=currency,
                    note=cash_note,
                ))

        db.session.commit()

    except Exception as e:
        db.session.rollback()
        logger.exception("Failed to finalize Telegram sale records: %s", e)
        query.answer("Продажа создана, но доп. записи не сохранились", show_alert=True)
        return ConversationHandler.END

    if sale and order:
        text = (
            "✅ Продажа записана.\n\n"
            f"Продано сейчас: {sold_now} шт.\n"
            f"Недостача: {missing} шт.\n"
            f"Создан заказ: #{order.id}"
        )
    elif sale:
        text = (
            "✅ Продажа записана.\n\n"
            f"Продано: {sold_now} шт.\n"
            f"Модель: {product.name}"
        )
    elif order:
        text = (
            "⚠️ На складе магазина не хватило товара.\n\n"
            f"Создан заказ #{order.id} на {missing} шт."
        )
    else:
        text = "Готово."

    query.answer("✅ Done")
    query.edit_message_text(text, reply_markup=menu_kb_for_chat(chat_id))

    context.user_data.pop("sale_product_id", None)
    context.user_data.pop("sale_product_name", None)
    context.user_data.pop("sale_price", None)
    context.user_data.pop("sale_shop_qty", None)
    context.user_data.pop("sale_qty", None)

    return ConversationHandler.END


# ------------------------------------------------------------------------------
# CASH RECORD WIZARD
# ------------------------------------------------------------------------------

@with_flask_context
def cash_entry_from_menu(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    chat_id = query.message.chat_id

    if deny_if_not_manager_callback(query, chat_id):
        return ConversationHandler.END

    if not require_link_for_writes(update, action="cash"):
        return ConversationHandler.END

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Income", callback_data="cash:income")],
        [InlineKeyboardButton("➖ Expense", callback_data="cash:expense")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cash:cancel")],
    ])
    query.answer()
    query.edit_message_text("💵 <b>Cash record</b>\n\nВыбери тип:", parse_mode="HTML", reply_markup=kb)
    return CASH_KIND


@with_flask_context
def cash_kind_step(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    chat_id = query.message.chat_id

    if deny_if_not_manager_callback(query, chat_id):
        return ConversationHandler.END

    if query.data == "cash:cancel":
        query.answer()
        query.edit_message_text("Ок, отменено.", reply_markup=neo_menu_kb())
        return ConversationHandler.END

    if not require_link_for_writes(update, action="cash"):
        return ConversationHandler.END

    kind = "income" if query.data == "cash:income" else "expense"
    context.user_data["cash_kind"] = kind

    query.answer()
    query.edit_message_text("Введи сумму (например: 120000):")
    return CASH_AMOUNT


@with_flask_context
def cash_amount_step(update: Update, context: CallbackContext) -> int:
    if deny_if_not_manager_message(update):
        return ConversationHandler.END

    if not require_link_for_writes(update, action="cash"):
        return ConversationHandler.END

    txt = (update.message.text or "").replace(",", ".").strip()
    try:
        amount = float(txt)
        if amount <= 0:
            raise ValueError
    except ValueError:
        update.message.reply_text("Сумма должна быть числом > 0. Попробуй ещё раз.")
        return CASH_AMOUNT

    context.user_data["cash_amount"] = amount
    update.message.reply_text("Комментарий (можно коротко):")
    return CASH_NOTE


@with_flask_context
def cash_note_step(update: Update, context: CallbackContext) -> int:
    if deny_if_not_manager_message(update):
        return ConversationHandler.END

    if not require_link_for_writes(update, action="cash"):
        return ConversationHandler.END

    note = (update.message.text or "").strip()
    context.user_data["cash_note"] = note

    kind = context.user_data.get("cash_kind")
    amount = context.user_data.get("cash_amount")

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm", callback_data="cash:confirm")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cash:cancel2")],
    ])

    update.message.reply_text(
        f"Подтверди запись:\n\n"
        f"• Тип: {kind}\n"
        f"• Сумма: {amount}\n"
        f"• Коммент: {note}\n",
        reply_markup=kb
    )
    return CASH_CONFIRM


@with_flask_context
def cash_confirm_step(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    chat_id = query.message.chat_id

    if deny_if_not_manager_callback(query, chat_id):
        return ConversationHandler.END

    if query.data in ("cash:cancel2", "cash:cancel"):
        query.answer()
        query.edit_message_text("Ок, отменено.", reply_markup=neo_menu_kb())
        return ConversationHandler.END

    if not require_link_for_writes(update, action="cash"):
        return ConversationHandler.END

    if query.data != "cash:confirm":
        query.answer()
        return CASH_CONFIRM

    factory_id = resolve_factory_id(chat_id)
    kind = context.user_data.get("cash_kind")
    amount = context.user_data.get("cash_amount")
    note = context.user_data.get("cash_note", "").strip()

    if not kind or amount is None:
        query.answer("Нет данных", show_alert=True)
        return ConversationHandler.END

    signed_amount = float(amount)
    if kind == "expense":
        signed_amount = -signed_amount

    try:
        rec = CashRecord(
            factory_id=factory_id,
            date=date.today(),
            amount=signed_amount,
            currency=DEFAULT_CASH_CURRENCY,
            note=f"Telegram {kind}: {note}" if note else f"Telegram {kind}",
        )
        db.session.add(rec)
        db.session.commit()

    except Exception as e:
        db.session.rollback()
        logger.exception("Cash record failed: %s", e)
        query.answer("Ошибка записи кассы", show_alert=True)
        return ConversationHandler.END

    query.answer("✅ Saved")
    query.edit_message_text(
        "✅ Запись добавлена в кассу.",
        reply_markup=neo_menu_kb()
    )

    context.user_data.pop("cash_kind", None)
    context.user_data.pop("cash_amount", None)
    context.user_data.pop("cash_note", None)

    return ConversationHandler.END

@with_flask_context
def prod_entry_from_menu(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    chat_id = query.message.chat_id

    if deny_if_not_manager_callback(query, chat_id):
        return ConversationHandler.END

    if not require_link_for_writes(update, action="production"):
        return ConversationHandler.END

    query.answer()
    query.edit_message_text(
        "🏭 <b>Добавить производство</b>\n\n"
        "Отправь название модели.\n"
        "Например: Traktor",
        parse_mode="HTML",
    )
    return PROD_SEARCH


@with_flask_context
def prod_search_step(update: Update, context: CallbackContext) -> int:
    if deny_if_not_manager_message(update):
        return ConversationHandler.END

    if not require_link_for_writes(update, action="production"):
        return ConversationHandler.END

    q = (update.message.text or "").strip()
    factory_id = resolve_factory_id(update.effective_chat.id)

    products = (
        Product.query
        .filter(Product.factory_id == factory_id)
        .filter(Product.name.ilike(f"%{q}%"))
        .order_by(Product.name.asc())
        .limit(10)
        .all()
    )

    if not products:
        update.message.reply_text("❌ Ничего не найдено. Попробуй другое название.")
        return PROD_SEARCH

    kb = []
    for p in products:
        kb.append([InlineKeyboardButton(
            f"{p.name} ({p.category or '-'})",
            callback_data=f"prod_pick:{p.id}"
        )])
    kb.append([InlineKeyboardButton("❌ Cancel", callback_data="prod_cancel")])

    update.message.reply_text(
        "Выбери модель:",
        reply_markup=InlineKeyboardMarkup(kb)
    )
    return PROD_PICK


@with_flask_context
def prod_pick_step(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    chat_id = query.message.chat_id

    if deny_if_not_manager_callback(query, chat_id):
        return ConversationHandler.END

    if not require_link_for_writes(update, action="production"):
        return ConversationHandler.END

    data = query.data or ""

    if data == "prod_cancel":
        query.answer()
        query.edit_message_text("Ок, отменено.", reply_markup=neo_menu_kb())
        return ConversationHandler.END

    try:
        product_id = int(data.split(":", 1)[1])
    except Exception:
        query.answer("Ошибка выбора", show_alert=True)
        return ConversationHandler.END

    factory_id = resolve_factory_id(chat_id)
    product = Product.query.filter_by(id=product_id, factory_id=factory_id).first()

    if not product:
        query.answer("Товар не найден", show_alert=True)
        return ConversationHandler.END

    context.user_data["prod_product_id"] = product.id
    context.user_data["prod_product_name"] = product.name

    query.answer()
    query.edit_message_text(
        f"🏭 Модель: <b>{product.name}</b>\n\n"
        f"Отправь количество, которое сегодня произведено.",
        parse_mode="HTML",
    )
    return PROD_QTY


@with_flask_context
def prod_qty_step(update: Update, context: CallbackContext) -> int:
    if deny_if_not_manager_message(update):
        return ConversationHandler.END

    if not require_link_for_writes(update, action="production"):
        return ConversationHandler.END

    try:
        qty = int((update.message.text or "").strip())
    except Exception:
        update.message.reply_text("Введите число.")
        return PROD_QTY

    if qty <= 0:
        update.message.reply_text("Количество должно быть больше нуля.")
        return PROD_QTY

    context.user_data["prod_qty"] = qty

    product_name = context.user_data.get("prod_product_name", "-")

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm", callback_data="prod_confirm")],
        [InlineKeyboardButton("❌ Cancel", callback_data="prod_cancel2")],
    ])

    update.message.reply_text(
        f"Подтверди производство:\n\n"
        f"• Модель: {product_name}\n"
        f"• Кол-во: {qty} шт.",
        reply_markup=kb
    )
    return PROD_CONFIRM


@with_flask_context
def prod_confirm_step(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    chat_id = query.message.chat_id

    if deny_if_not_manager_callback(query, chat_id):
        return ConversationHandler.END

    if query.data in ("prod_cancel2", "prod_cancel"):
        query.answer()
        query.edit_message_text("Ок, отменено.", reply_markup=neo_menu_kb())
        return ConversationHandler.END

    if not require_link_for_writes(update, action="production"):
        return ConversationHandler.END

    if query.data != "prod_confirm":
        query.answer()
        return PROD_CONFIRM

    factory_id = resolve_factory_id(chat_id)
    product_id = context.user_data.get("prod_product_id")
    qty = context.user_data.get("prod_qty")

    if not product_id or not qty:
        query.answer("Нет данных", show_alert=True)
        return ConversationHandler.END

    product = Product.query.filter_by(id=product_id, factory_id=factory_id).first()
    if not product:
        query.answer("Товар не найден", show_alert=True)
        return ConversationHandler.END

    try:
        db.session.add(
            Production(
                product_id=product.id,
                date=date.today(),
                quantity=qty,
                note="telegram production",
            )
        )

        product.quantity = int(product.quantity or 0) + int(qty)

        linked = get_link(chat_id)
        created_by_id = linked.user_id if linked else None

        db.session.add(
            Movement(
                factory_id=factory_id,
                product_id=product.id,
                source="production",
                destination="factory_stock",
                change=qty,
                note=f"Telegram production: {qty} шт.",
                created_by_id=created_by_id,
                timestamp=datetime.utcnow(),
            )
        )

        db.session.commit()

    except Exception as e:
        db.session.rollback()
        logger.exception("Telegram production failed: %s", e)
        query.answer("Ошибка сохранения", show_alert=True)
        return ConversationHandler.END

    query.answer("✅ Saved")
    query.edit_message_text(
        f"✅ Производство сохранено.\n\n"
        f"• {product.name}\n"
        f"• {qty} шт.\n\n"
        f"Теперь можно нажать «🚚 Move to shop».",
        reply_markup=neo_menu_kb()
    )

    context.user_data.pop("prod_product_id", None)
    context.user_data.pop("prod_product_name", None)
    context.user_data.pop("prod_qty", None)

    return ConversationHandler.END


@with_flask_context
def move_search_step(update: Update, context: CallbackContext) -> int:
    if deny_if_not_manager_message(update):
        return ConversationHandler.END

    if not require_link_for_writes(update, action="move"):
        return ConversationHandler.END

    q = (update.message.text or "").strip()
    factory_id = resolve_factory_id(update.effective_chat.id)

    products = (
        Product.query
        .filter(Product.factory_id == factory_id)
        .filter(Product.name.ilike(f"%{q}%"))
        .order_by(Product.name.asc())
        .limit(10)
        .all()
    )

    if not products:
        update.message.reply_text("❌ Ничего не найдено.")
        return MOVE_SEARCH

    kb = []
    for p in products:
        kb.append([InlineKeyboardButton(
            f"{p.name} — фабрика: {int(p.quantity or 0)} шт.",
            callback_data=f"move_pick:{p.id}"
        )])
    kb.append([InlineKeyboardButton("❌ Cancel", callback_data="move_cancel")])

    update.message.reply_text("Выбери модель:", reply_markup=InlineKeyboardMarkup(kb))
    return MOVE_PICK


@with_flask_context
def move_pick_step(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    chat_id = query.message.chat_id

    if deny_if_not_manager_callback(query, chat_id):
        return ConversationHandler.END

    if not require_link_for_writes(update, action="move"):
        return ConversationHandler.END

    data = query.data or ""

    if data == "move_cancel":
        query.answer()
        query.edit_message_text("Ок, отменено.", reply_markup=neo_menu_kb())
        return ConversationHandler.END

    try:
        product_id = int(data.split(":", 1)[1])
    except Exception:
        query.answer("Ошибка выбора", show_alert=True)
        return ConversationHandler.END

    factory_id = resolve_factory_id(chat_id)
    product = Product.query.filter_by(id=product_id, factory_id=factory_id).first()

    if not product:
        query.answer("Товар не найден", show_alert=True)
        return ConversationHandler.END

    context.user_data["move_product_id"] = product.id
    context.user_data["move_product_name"] = product.name

    query.answer()
    query.edit_message_text(
        f"🚚 Модель: <b>{product.name}</b>\n"
        f"На фабрике: <b>{int(product.quantity or 0)}</b> шт.\n\n"
        f"Отправь количество для магазина.",
        parse_mode="HTML",
    )
    return MOVE_QTY


@with_flask_context
def move_qty_step(update: Update, context: CallbackContext) -> int:
    if deny_if_not_manager_message(update):
        return ConversationHandler.END

    if not require_link_for_writes(update, action="move"):
        return ConversationHandler.END

    try:
        qty = int((update.message.text or "").strip())
    except Exception:
        update.message.reply_text("Введите число.")
        return MOVE_QTY

    if qty <= 0:
        update.message.reply_text("Количество должно быть больше нуля.")
        return MOVE_QTY

    context.user_data["move_qty"] = qty

    product_name = context.user_data.get("move_product_name", "-")

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm", callback_data="move_confirm")],
        [InlineKeyboardButton("❌ Cancel", callback_data="move_cancel2")],
    ])

    update.message.reply_text(
        f"Подтверди передачу:\n\n"
        f"• Модель: {product_name}\n"
        f"• Кол-во: {qty} шт.",
        reply_markup=kb
    )
    return MOVE_CONFIRM


@with_flask_context
def move_confirm_step(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    chat_id = query.message.chat_id

    if deny_if_not_manager_callback(query, chat_id):
        return ConversationHandler.END

    if query.data in ("move_cancel2", "move_cancel"):
        query.answer()
        query.edit_message_text("Ок, отменено.", reply_markup=neo_menu_kb())
        return ConversationHandler.END

    if not require_link_for_writes(update, action="move"):
        return ConversationHandler.END

    if query.data != "move_confirm":
        query.answer()
        return MOVE_CONFIRM

    factory_id = resolve_factory_id(chat_id)
    product_id = context.user_data.get("move_product_id")
    qty = context.user_data.get("move_qty")

    if not product_id or not qty:
        query.answer("Нет данных", show_alert=True)
        return ConversationHandler.END

    product = Product.query.filter_by(id=product_id, factory_id=factory_id).first()
    if not product:
        query.answer("Товар не найден", show_alert=True)
        return ConversationHandler.END

    try:
        qty = int(qty)

        shop_service.transfer_to_shop(
            factory_id=factory_id,
            product_id=product.id,
            quantity=qty,
            sell_price_per_item=None,
        )

        linked = get_link(chat_id)
        created_by_id = linked.user_id if linked else None

        db.session.add(
            Movement(
                factory_id=factory_id,
                product_id=product.id,
                source="factory",
                destination="shop",
                change=qty,
                note=f"Telegram move to shop: {qty} шт.",
                created_by_id=created_by_id,
                timestamp=datetime.utcnow(),
            )
        )

        # auto-fulfill pending orders for this product
        remaining_to_allocate = qty
        ready_order_ids = set()

        pending_items = (
            ShopOrderItem.query
            .join(ShopOrder, ShopOrder.id == ShopOrderItem.order_id)
            .filter(ShopOrderItem.product_id == product.id)
            .filter(ShopOrder.status == "pending")
            .filter(ShopOrderItem.qty_remaining > 0)
            .order_by(ShopOrder.created_at.asc(), ShopOrderItem.id.asc())
            .all()
        )

        for item in pending_items:
            if remaining_to_allocate <= 0:
                break

            need = int(item.qty_remaining or 0)
            if need <= 0:
                continue

            shipped = min(remaining_to_allocate, need)

            item.qty_from_shop_now = int(item.qty_from_shop_now or 0) + shipped
            item.qty_remaining = int(item.qty_remaining or 0) - shipped

            if item.order:
                item.order.recalc_status()
                if item.order.status == "ready":
                    ready_order_ids.add(item.order.id)

            remaining_to_allocate -= shipped

        db.session.commit()

    except Exception as e:
        db.session.rollback()
        logger.exception("Telegram move-to-shop failed: %s", e)
        query.answer("Ошибка передачи", show_alert=True)
        return ConversationHandler.END

    msg = (
        f"✅ Передано в магазин.\n\n"
        f"• {product.name}\n"
        f"• {qty} шт."
    )
    if ready_order_ids:
        msg += "\n\nГотовы заказы: " + ", ".join(f"#{x}" for x in sorted(ready_order_ids))

    query.answer("✅ Moved")
    query.edit_message_text(msg, reply_markup=neo_menu_kb())

    context.user_data.pop("move_product_id", None)
    context.user_data.pop("move_product_name", None)
    context.user_data.pop("move_qty", None)

    return ConversationHandler.END


@with_flask_context
def move_entry_from_menu(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    chat_id = query.message.chat_id

    if deny_if_not_manager_callback(query, chat_id):
        return ConversationHandler.END

    if not require_link_for_writes(update, action="move"):
        return ConversationHandler.END

    query.answer()
    query.edit_message_text(
        "🚚 <b>Передать в магазин</b>\n\n"
        "Отправь название модели.",
        parse_mode="HTML",
    )
    return MOVE_SEARCH


@with_flask_context
def move_search_step(update: Update, context: CallbackContext) -> int:
    if deny_if_not_manager_message(update):
        return ConversationHandler.END

    if not require_link_for_writes(update, action="move"):
        return ConversationHandler.END

    q = (update.message.text or "").strip()
    factory_id = resolve_factory_id(update.effective_chat.id)

    products = (
        Product.query
        .filter(Product.factory_id == factory_id)
        .filter(Product.name.ilike(f"%{q}%"))
        .order_by(Product.name.asc())
        .limit(10)
        .all()
    )

    if not products:
        update.message.reply_text("❌ Ничего не найдено.")
        return MOVE_SEARCH

    kb = []
    for p in products:
        kb.append([
            InlineKeyboardButton(
                f"{p.name} — фабрика: {int(p.quantity or 0)} шт.",
                callback_data=f"move_pick:{p.id}"
            )
        ])
    kb.append([InlineKeyboardButton("❌ Cancel", callback_data="move_cancel")])

    update.message.reply_text(
        "Выбери модель:",
        reply_markup=InlineKeyboardMarkup(kb)
    )
    return MOVE_PICK


@with_flask_context
def move_pick_step(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    chat_id = query.message.chat_id

    if deny_if_not_manager_callback(query, chat_id):
        return ConversationHandler.END

    if not require_link_for_writes(update, action="move"):
        return ConversationHandler.END

    data = query.data or ""

    if data == "move_cancel":
        query.answer()
        query.edit_message_text("Ок, отменено.", reply_markup=neo_menu_kb())
        return ConversationHandler.END

    try:
        product_id = int(data.split(":", 1)[1])
    except Exception:
        query.answer("Ошибка выбора", show_alert=True)
        return ConversationHandler.END

    factory_id = resolve_factory_id(chat_id)
    product = Product.query.filter_by(id=product_id, factory_id=factory_id).first()

    if not product:
        query.answer("Товар не найден", show_alert=True)
        return ConversationHandler.END

    context.user_data["move_product_id"] = product.id
    context.user_data["move_product_name"] = product.name

    query.answer()
    query.edit_message_text(
        f"🚚 Модель: <b>{product.name}</b>\n"
        f"На фабрике: <b>{int(product.quantity or 0)}</b> шт.\n\n"
        f"Отправь количество для магазина.",
        parse_mode="HTML",
    )
    return MOVE_QTY


@with_flask_context
def move_qty_step(update: Update, context: CallbackContext) -> int:
    if deny_if_not_manager_message(update):
        return ConversationHandler.END

    if not require_link_for_writes(update, action="move"):
        return ConversationHandler.END

    try:
        qty = int((update.message.text or "").strip())
    except Exception:
        update.message.reply_text("Введите число.")
        return MOVE_QTY

    if qty <= 0:
        update.message.reply_text("Количество должно быть больше нуля.")
        return MOVE_QTY

    context.user_data["move_qty"] = qty
    product_name = context.user_data.get("move_product_name", "-")

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm", callback_data="move_confirm")],
        [InlineKeyboardButton("❌ Cancel", callback_data="move_cancel2")],
    ])

    update.message.reply_text(
        f"Подтверди передачу:\n\n"
        f"• Модель: {product_name}\n"
        f"• Кол-во: {qty} шт.",
        reply_markup=kb
    )
    return MOVE_CONFIRM


@with_flask_context
def move_confirm_step(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    chat_id = query.message.chat_id

    if deny_if_not_manager_callback(query, chat_id):
        return ConversationHandler.END

    if query.data in ("move_cancel2", "move_cancel"):
        query.answer()
        query.edit_message_text("Ок, отменено.", reply_markup=neo_menu_kb())
        return ConversationHandler.END

    if not require_link_for_writes(update, action="move"):
        return ConversationHandler.END

    if query.data != "move_confirm":
        query.answer()
        return MOVE_CONFIRM

    factory_id = resolve_factory_id(chat_id)
    product_id = context.user_data.get("move_product_id")
    qty = context.user_data.get("move_qty")

    if not product_id or not qty:
        query.answer("Нет данных", show_alert=True)
        return ConversationHandler.END

    product = Product.query.filter_by(id=product_id, factory_id=factory_id).first()
    if not product:
        query.answer("Товар не найден", show_alert=True)
        return ConversationHandler.END

    try:
        shop_service.transfer_to_shop(
            factory_id=factory_id,
            product_id=product.id,
            quantity=int(qty),
            sell_price_per_item=None,
        )

        linked = get_link(chat_id)
        created_by_id = linked.user_id if linked else None

        db.session.add(
            Movement(
                factory_id=factory_id,
                product_id=product.id,
                source="factory",
                destination="shop",
                change=int(qty),
                note=f"Telegram move to shop: {qty} шт.",
                created_by_id=created_by_id,
                timestamp=datetime.utcnow(),
            )
        )
        db.session.commit()

    except Exception as e:
        db.session.rollback()
        logger.exception("Telegram move-to-shop failed: %s", e)
        query.answer("Ошибка передачи", show_alert=True)
        return ConversationHandler.END

    query.answer("✅ Moved")
    query.edit_message_text(
        f"✅ Передано в магазин.\n\n"
        f"• {product.name}\n"
        f"• {qty} шт.",
        reply_markup=neo_menu_kb()
    )

    context.user_data.pop("move_product_id", None)
    context.user_data.pop("move_product_name", None)
    context.user_data.pop("move_qty", None)

    return ConversationHandler.END
# ------------------------------------------------------------------------------
# MAIN
# ------------------------------------------------------------------------------
def main():
    print(">>> MAIN STARTED")

    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set. Add it to the environment or project .env file.")
    print(">>> TOKEN FOUND")

    logger.info("Starting Telegram bot...")
    updater = Updater(TELEGRAM_BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    # commands
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("help", help_cmd))
    dp.add_handler(CommandHandler("id", chat_id_cmd))
    dp.add_handler(CommandHandler("menu", menu_cmd))
    dp.add_handler(CommandHandler("link", link_cmd))

    dp.add_handler(CommandHandler("alerts", alerts))
    dp.add_handler(CommandHandler("sales_today", sales_today_cmd))
    dp.add_handler(CommandHandler("shop_low", shop_low))
    dp.add_handler(CommandHandler("shop_stock", shop_stock))
    dp.add_handler(CommandHandler("pending", pending))
    dp.add_handler(CommandHandler("last_moves", last_moves))
    dp.add_handler(CommandHandler("product", product_cmd))

    sale_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(sale_entry_from_menu, pattern=r"^m:sale$")],
        states={
            SALE_SEARCH: [MessageHandler(Filters.text & ~Filters.command, sale_search_step)],
            SALE_PICK: [CallbackQueryHandler(sale_pick_step, pattern=r"^(sale_pick:\d+|sale_cancel)$")],
            SALE_QTY: [MessageHandler(Filters.text & ~Filters.command, sale_qty_step)],
            SALE_CONFIRM: [CallbackQueryHandler(sale_confirm_step, pattern=r"^(sale_confirm|sale_cancel2|sale_cancel)$")],
        },
        fallbacks=[],
        allow_reentry=True,
    )
    dp.add_handler(sale_conv)

    cash_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cash_entry_from_menu, pattern=r"^m:cash$")],
        states={
            CASH_KIND: [CallbackQueryHandler(cash_kind_step, pattern=r"^cash:(income|expense|cancel)$")],
            CASH_AMOUNT: [MessageHandler(Filters.text & ~Filters.command, cash_amount_step)],
            CASH_NOTE: [MessageHandler(Filters.text & ~Filters.command, cash_note_step)],
            CASH_CONFIRM: [CallbackQueryHandler(cash_confirm_step, pattern=r"^cash:(confirm|cancel2|cancel)$")],
        },
        fallbacks=[],
        allow_reentry=True,
    )
    dp.add_handler(cash_conv)

    prod_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(prod_entry_from_menu, pattern=r"^m:prod$")],
        states={
            PROD_SEARCH: [MessageHandler(Filters.text & ~Filters.command, prod_search_step)],
            PROD_PICK: [CallbackQueryHandler(prod_pick_step, pattern=r"^(prod_pick:\d+|prod_cancel)$")],
            PROD_QTY: [MessageHandler(Filters.text & ~Filters.command, prod_qty_step)],
            PROD_CONFIRM: [CallbackQueryHandler(prod_confirm_step, pattern=r"^(prod_confirm|prod_cancel2|prod_cancel)$")],
        },
        fallbacks=[],
        allow_reentry=True,
    )
    dp.add_handler(prod_conv)

    move_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(move_entry_from_menu, pattern=r"^m:move$")],
        states={
            MOVE_SEARCH: [MessageHandler(Filters.text & ~Filters.command, move_search_step)],
            MOVE_PICK: [CallbackQueryHandler(move_pick_step, pattern=r"^(move_pick:\d+|move_cancel)$")],
            MOVE_QTY: [MessageHandler(Filters.text & ~Filters.command, move_qty_step)],
            MOVE_CONFIRM: [CallbackQueryHandler(move_confirm_step, pattern=r"^(move_confirm|move_cancel2|move_cancel)$")],
        },
        fallbacks=[],
        allow_reentry=True,
    )
    dp.add_handler(move_conv)

    dp.add_handler(CallbackQueryHandler(product_detail_callback, pattern=r"^prod:\d+$"))
    dp.add_handler(CallbackQueryHandler(menu_callback, pattern=r"^m:"))
    
    print(">>> HANDLERS REGISTERED")
    logger.info("Bot started. Waiting for updates...")
    print(">>> POLLING STARTED")
    updater.start_polling()
    updater.idle()
if __name__ == "__main__":
    main()
