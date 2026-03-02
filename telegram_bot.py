import logging
from typing import List, Callable, Optional, Tuple
from functools import wraps
from datetime import datetime

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
    StockMovement,
)

# Optional models (new features)
# If you don't have them yet, create them and import:
from app.models import TelegramLink, TelegramLinkCode, CashRecord  # type: ignore


# ------------------------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = telegram_config.TELEGRAM_BOT_TOKEN

MANAGER_CHAT_IDS: List[int] = getattr(telegram_config, "MANAGER_CHAT_IDS", [])
DEFAULT_FACTORY_ID: int = getattr(telegram_config, "DEFAULT_FACTORY_ID", 1)
LOW_STOCK_THRESHOLD: int = getattr(telegram_config, "LOW_STOCK_THRESHOLD", 5)


# ------------------------------------------------------------------------------
# FLASK APP + LOGGING
# ------------------------------------------------------------------------------
flask_app = create_app()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ------------------------------------------------------------------------------
# CONVERSATION STATES (new)
# ------------------------------------------------------------------------------
SALE_SEARCH, SALE_PICK, SALE_QTY, SALE_CONFIRM = range(4)
CASH_KIND, CASH_AMOUNT, CASH_NOTE, CASH_CONFIRM = range(4, 8)


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
      - if MANAGER_CHAT_IDS is empty → allow everyone (debug mode)
      - else → only chat_ids from list
    """
    if not MANAGER_CHAT_IDS:
        return True
    return chat_id in MANAGER_CHAT_IDS


def deny_if_not_manager_message(update: Update) -> bool:
    """Check access for message updates and reply 'Нет доступа'."""
    chat_id = update.effective_chat.id
    if not is_manager(chat_id):
        if update.message:
            update.message.reply_text("Нет доступа.")
        return True
    return False


def deny_if_not_manager_callback(query, chat_id: int) -> bool:
    """Check access for callback updates and show alert."""
    if not is_manager(chat_id):
        query.answer("Нет доступа", show_alert=True)
        return True
    return False


def get_link(chat_id: int) -> Optional["TelegramLink"]:
    return TelegramLink.query.filter_by(telegram_chat_id=chat_id).first()


def resolve_factory_id(chat_id: int) -> int:
    """
    Prefer linked factory_id. If not linked, fallback to DEFAULT_FACTORY_ID.
    (Read-only commands will still work for your default factory.)
    """
    link = get_link(chat_id)
    if link and link.factory_id:
        return link.factory_id
    return DEFAULT_FACTORY_ID


def require_link_for_writes(update: Update) -> bool:
    """
    For actions that change DB (sale/cash/etc), we REQUIRE linking,
    otherwise user might write into DEFAULT_FACTORY_ID by mistake.
    """
    chat_id = update.effective_chat.id
    link = get_link(chat_id)
    if link:
        return True

    if update.message:
        update.message.reply_text(
            "❗️Бот не привязан к аккаунту.\n\n"
            "Открой MiniModa → Профиль → Telegram код\n"
            "И отправь сюда:\n"
            "/link CODE\n\n"
            "После привязки будут доступны продажи/касса."
        )
    else:
        update.callback_query.answer("Нужно /link CODE", show_alert=True)
    return False


def neo_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Dashboard", callback_data="m:dash")],
        [InlineKeyboardButton("📦 Shop stock", callback_data="m:shop_stock"),
         InlineKeyboardButton("⚠️ Low stock", callback_data="m:shop_low")],
        [InlineKeyboardButton("📬 Pending orders", callback_data="m:pending")],
        [InlineKeyboardButton("🧾 Quick sale", callback_data="m:sale")],
        [InlineKeyboardButton("💵 Cash record", callback_data="m:cash")],
        [InlineKeyboardButton("📜 Last moves", callback_data="m:moves")],
        [InlineKeyboardButton("🔎 Products", callback_data="m:product")],
    ])


def back_to_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Back to menu", callback_data="m:menu")]
    ])


# ------------------------------------------------------------------------------
# BASIC COMMANDS: /start, /help, /id, /menu
# ------------------------------------------------------------------------------

def chat_id_cmd(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id
    logger.info("User requested /id, chat_id=%s", chat_id)

    text = (
        f"Ваш chat_id: <b>{chat_id}</b>\n\n"
        "Добавьте его в MANAGER_CHAT_IDS в app/telegram_config.py, "
        "если хотите ограничить доступ только для себя и семьи."
    )
    update.message.reply_html(text)


def start(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id
    logger.info("Received /start from chat_id=%s", chat_id)

    if deny_if_not_manager_message(update):
        return

    # Keep your old ReplyKeyboard too (fast access)
    keyboard = [
        ["/alerts", "/shop_low"],
        ["/shop_stock", "/pending"],
        ["/last_moves", "/product"],
        ["/menu", "/link", "/id"],
    ]
    reply_kb = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    update.message.reply_text(
        "Ассаламу алейкум!\n\n"
        "MiniModa Manager Bot (Neo).\n\n"
        "Команды:\n"
        "• /menu — красивое меню (inline)\n"
        "• /alerts — обзор\n"
        "• /shop_low — низкий остаток в магазине\n"
        "• /shop_stock [слово] — остатки магазина\n"
        "• /pending — заказы pending\n"
        "• /last_moves — последние движения\n"
        "• /product [текст] — поиск моделей\n"
        "• /link CODE — привязать Telegram к аккаунту (для продаж/кассы)\n"
        "• /id — ваш chat_id\n",
        reply_markup=reply_kb,
    )


def help_cmd(update: Update, context: CallbackContext) -> None:
    return start(update, context)


def menu_cmd(update: Update, context: CallbackContext) -> None:
    if deny_if_not_manager_message(update):
        return
    update.message.reply_text("MiniModa Control Panel 🚀", reply_markup=neo_menu_kb())


# ------------------------------------------------------------------------------
# /link CODE — account linking (new)
# ------------------------------------------------------------------------------

@with_flask_context
def link_cmd(update: Update, context: CallbackContext) -> None:
    if deny_if_not_manager_message(update):
        return

    if not context.args:
        update.message.reply_text("Использование: /link CODE")
        return

    code_value = context.args[0].strip()
    code = TelegramLinkCode.query.filter_by(code=code_value).first()

    if not code:
        update.message.reply_text("❌ Код не найден.")
        return

    if code.used_at:
        update.message.reply_text("❌ Этот код уже использован.")
        return

    if code.expires_at and code.expires_at < datetime.utcnow():
        update.message.reply_text("❌ Код истёк. Сгенерируй новый в MiniModa.")
        return

    # replace any existing link for this chat
    TelegramLink.query.filter_by(telegram_chat_id=update.effective_chat.id).delete()

    link = TelegramLink(
        telegram_chat_id=update.effective_chat.id,
        user_id=code.user_id,
        factory_id=code.factory_id,
    )

    code.used_at = datetime.utcnow()
    db.session.add(link)
    db.session.commit()

    update.message.reply_text("✅ Telegram успешно привязан!")
    update.message.reply_text("MiniModa Control Panel 🚀", reply_markup=neo_menu_kb())


# ------------------------------------------------------------------------------
# /alerts — your original short summary (kept)
# ------------------------------------------------------------------------------

@with_flask_context
def alerts(update: Update, context: CallbackContext) -> None:
    if deny_if_not_manager_message(update):
        return

    factory_id = resolve_factory_id(update.effective_chat.id)

    low_count = (
        db.session.query(ShopStock)
        .join(Product)
        .filter(
            Product.factory_id == factory_id,
            ShopStock.quantity < LOW_STOCK_THRESHOLD,
        )
        .count()
    )

    pending_count = (
        ShopOrder.query
        .filter_by(factory_id=factory_id, status="pending")
        .count()
    )

    last_mv = (
        StockMovement.query
        .filter_by(factory_id=factory_id)
        .order_by(StockMovement.timestamp.desc())
        .first()
    )
    last_mv_str = last_mv.timestamp.strftime("%d.%m %H:%M") if last_mv and last_mv.timestamp else "нет данных"

    txt = (
        "📊 Краткий обзор\n\n"
        f"• Низкий остаток в магазине (<{LOW_STOCK_THRESHOLD}): {low_count}\n"
        f"• Pending заказы: {pending_count}\n"
        f"• Последнее движение: {last_mv_str}\n\n"
        "Подробнее:\n"
        "— /shop_low\n"
        "— /pending\n"
        "— /last_moves\n"
        "— /menu (neo)"
    )
    update.message.reply_text(txt)


# ------------------------------------------------------------------------------
# /shop_low — kept
# ------------------------------------------------------------------------------

@with_flask_context
def shop_low(update: Update, context: CallbackContext) -> None:
    if deny_if_not_manager_message(update):
        return

    factory_id = resolve_factory_id(update.effective_chat.id)

    low_items = (
        db.session.query(ShopStock)
        .join(Product)
        .filter(
            Product.factory_id == factory_id,
            ShopStock.quantity < LOW_STOCK_THRESHOLD,
        )
        .order_by(ShopStock.quantity.asc())
        .all()
    )

    if not low_items:
        update.message.reply_text("В магазине нет товаров с низким остатком. 👍")
        return

    lines = [f"⚠️ Товары с остатком < {LOW_STOCK_THRESHOLD} в магазине:\n"]
    for row in low_items:
        p: Product = row.product
        lines.append(
            f"• {p.name} ({p.category or '-'}) — "
            f"{row.quantity} шт., {p.sell_price_per_item or 0} {p.currency}"
        )

    update.message.reply_text("\n".join(lines))


# ------------------------------------------------------------------------------
# /shop_stock [filter] — kept
# ------------------------------------------------------------------------------

@with_flask_context
def shop_stock(update: Update, context: CallbackContext) -> None:
    if deny_if_not_manager_message(update):
        return

    factory_id = resolve_factory_id(update.effective_chat.id)

    args = context.args
    search = " ".join(args).strip().lower() if args else None

    query = (
        db.session.query(ShopStock)
        .join(Product)
        .filter(
            Product.factory_id == factory_id,
            ShopStock.quantity > 0,
        )
        .order_by(ShopStock.quantity.asc())
    )

    if search:
        query = query.filter(Product.name.ilike(f"%{search}%"))

    items = query.limit(25).all()

    if not items:
        update.message.reply_text(
            f"Ничего не найдено по запросу: “{search}”." if search else "В магазине нет товаров с остатком > 0."
        )
        return

    header = f"📊 Остатки в магазине (поиск: “{search}”):\n" if search else "📊 Остатки в магазине (первые 25 позиций):\n"
    lines = [header]
    for row in items:
        p: Product = row.product
        lines.append(
            f"• {p.name} ({p.category or '-'}) — "
            f"{row.quantity} шт., {p.sell_price_per_item or 0} {p.currency}"
        )

    update.message.reply_text("\n".join(lines))


# ------------------------------------------------------------------------------
# /pending — kept
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
        .limit(7)
        .all()
    )

    if not orders:
        update.message.reply_text("Нет заказов в статусе 'pending'. ✅")
        return

    lines = ["📬 Заказы магазина (pending):\n"]
    for o in orders:
        item_count = len(o.items) if hasattr(o, "items") and o.items else 0
        created = o.created_at.strftime("%d.%m %H:%M") if o.created_at else "?"
        lines.append(f"• №{o.id}: {item_count} позиций, создан {created}")

    update.message.reply_text("\n".join(lines))


# ------------------------------------------------------------------------------
# /last_moves — kept
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
# /product [text] — kept (inline list)
# ------------------------------------------------------------------------------

@with_flask_context
def product_cmd(update: Update, context: CallbackContext) -> None:
    if deny_if_not_manager_message(update):
        return

    factory_id = resolve_factory_id(update.effective_chat.id)

    args = context.args
    search = " ".join(args).strip() if args else None

    base_q = Product.query.filter_by(factory_id=factory_id)

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
# Callback: product details — kept
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

    factory_id = resolve_factory_id(chat_id)

    product = (
        Product.query
        .filter_by(id=product_id, factory_id=factory_id)
        .first()
    )

    if not product:
        query.answer("Товар не найден", show_alert=True)
        return

    factory_qty = product.quantity or 0
    shop_row = ShopStock.query.filter_by(product_id=product.id).first()
    shop_qty = shop_row.quantity if shop_row else 0
    total_qty = factory_qty + shop_qty

    text = (
        f"📦 <b>{product.name}</b>\n"
        f"Код: <code>MM-{product.id:05d}</code>\n"
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
# NEO MENU CALLBACKS (new)
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
        query.edit_message_text("MiniModa Control Panel 🚀", reply_markup=neo_menu_kb())
        return

    factory_id = resolve_factory_id(chat_id)

    if data == "m:dash":
        # dashboard = same spirit as /alerts but neo
        low_count = (
            db.session.query(ShopStock)
            .join(Product)
            .filter(Product.factory_id == factory_id,
                    ShopStock.quantity < LOW_STOCK_THRESHOLD)
            .count()
        )
        pending_count = (
            ShopOrder.query
            .filter_by(factory_id=factory_id, status="pending")
            .count()
        )
        last_mv = (
            StockMovement.query
            .filter_by(factory_id=factory_id)
            .order_by(StockMovement.timestamp.desc())
            .first()
        )
        last_mv_str = last_mv.timestamp.strftime("%d.%m %H:%M") if last_mv and last_mv.timestamp else "нет данных"

        txt = (
            "📊 <b>Dashboard</b>\n\n"
            f"⚠️ Low stock (&lt;{LOW_STOCK_THRESHOLD}): <b>{low_count}</b>\n"
            f"📬 Pending orders: <b>{pending_count}</b>\n"
            f"📜 Last movement: <b>{last_mv_str}</b>\n\n"
            "Хочешь действия? → Quick sale / Cash record"
        )
        query.answer()
        query.edit_message_text(txt, parse_mode="HTML", reply_markup=back_to_menu_kb())
        return

    if data == "m:shop_low":
        # show low stock inline
        low_items = (
            db.session.query(ShopStock)
            .join(Product)
            .filter(Product.factory_id == factory_id,
                    ShopStock.quantity < LOW_STOCK_THRESHOLD)
            .order_by(ShopStock.quantity.asc())
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
            lines.append(f"• {p.name} — <b>{row.quantity}</b> шт.")
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
            lines.append(f"• №{o.id} — {item_count} поз., {created}")

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
            lines.append(f"• {ts} — {product_name}: {mv.qty_change:+} шт.")
        query.answer()
        query.edit_message_text("\n".join(lines), parse_mode="HTML", reply_markup=back_to_menu_kb())
        return

    if data == "m:shop_stock":
        # show first 25 shop stock inline
        items = (
            db.session.query(ShopStock)
            .join(Product)
            .filter(Product.factory_id == factory_id, ShopStock.quantity > 0)
            .order_by(ShopStock.quantity.asc())
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
            lines.append(f"• {p.name} — <b>{row.quantity}</b> шт.")
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

    # Wizards entry points handled by ConversationHandlers (sale/cash).
    query.answer()


# ------------------------------------------------------------------------------
# QUICK SALE WIZARD (new)
# NOTE: This is BASIC. We'll later connect it to your real Sale/SaleItem logic.
# ------------------------------------------------------------------------------

@with_flask_context
def sale_entry_from_menu(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    chat_id = query.message.chat_id

    if deny_if_not_manager_callback(query, chat_id):
        return ConversationHandler.END

    if not require_link_for_writes(update):
        return ConversationHandler.END

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

    if not require_link_for_writes(update):
        return ConversationHandler.END

    factory_id = resolve_factory_id(update.effective_chat.id)
    search = (update.message.text or "").strip()

    products = (
        Product.query
        .filter_by(factory_id=factory_id)
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
        buttons.append([InlineKeyboardButton(f"{p.name}", callback_data=f"sale_pick:{p.id}")])
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
        query.edit_message_text("Ок, отменено.", reply_markup=neo_menu_kb())
        return ConversationHandler.END

    if not require_link_for_writes(update):
        return ConversationHandler.END

    try:
        product_id = int(query.data.split(":", 1)[1])
    except Exception:
        query.answer("Ошибка товара", show_alert=True)
        return ConversationHandler.END

    factory_id = resolve_factory_id(chat_id)
    product = Product.query.filter_by(id=product_id, factory_id=factory_id).first()
    if not product:
        query.answer("Товар не найден", show_alert=True)
        return ConversationHandler.END

    context.user_data["sale_product_id"] = product.id
    context.user_data["sale_product_name"] = product.name
    context.user_data["sale_price"] = float(product.sell_price_per_item or 0)

    query.answer()
    query.edit_message_text(
        f"Товар: <b>{product.name}</b>\n"
        f"Цена (по умолчанию): <b>{context.user_data['sale_price']}</b> {product.currency}\n\n"
        "Теперь напиши количество (например: 3):",
        parse_mode="HTML"
    )
    return SALE_QTY


@with_flask_context
def sale_qty_step(update: Update, context: CallbackContext) -> int:
    if deny_if_not_manager_message(update):
        return ConversationHandler.END

    if not require_link_for_writes(update):
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

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm sale", callback_data="sale_confirm")],
        [InlineKeyboardButton("❌ Cancel", callback_data="sale_cancel2")],
    ])

    update.message.reply_text(
        f"Подтверди продажу:\n\n"
        f"• Товар: {name}\n"
        f"• Кол-во: {qty}\n"
        f"• Цена: {price}\n",
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
        query.edit_message_text("Ок, отменено.", reply_markup=neo_menu_kb())
        return ConversationHandler.END

    if not require_link_for_writes(update):
        return ConversationHandler.END

    if query.data != "sale_confirm":
        query.answer()
        return SALE_CONFIRM

    factory_id = resolve_factory_id(chat_id)
    product_id = context.user_data.get("sale_product_id")
    qty = context.user_data.get("sale_qty")

    if not product_id or not qty:
        query.answer("Нет данных продажи", show_alert=True)
        return ConversationHandler.END

    product = Product.query.filter_by(id=product_id, factory_id=factory_id).first()
    if not product:
        query.answer("Товар не найден", show_alert=True)
        return ConversationHandler.END

    # BASIC stock deduction (factory stock)
    # Later we can connect this to your Sale/SaleItem + shop stock logic.
    current_qty = int(product.quantity or 0)
    if current_qty - qty < 0:
        query.answer("Недостаточно товара на фабрике", show_alert=True)
        return SALE_CONFIRM

    product.quantity = current_qty - qty
    db.session.commit()

    query.answer("✅ Done")
    query.edit_message_text(
        f"✅ Продажа записана.\n\n"
        f"{product.name}: -{qty} шт. (фабрика)\n"
        f"Осталось: {product.quantity}",
        reply_markup=neo_menu_kb()
    )
    return ConversationHandler.END


# ------------------------------------------------------------------------------
# CASH RECORD WIZARD (new)
# ------------------------------------------------------------------------------

@with_flask_context
def cash_entry_from_menu(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    chat_id = query.message.chat_id

    if deny_if_not_manager_callback(query, chat_id):
        return ConversationHandler.END

    if not require_link_for_writes(update):
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

    if not require_link_for_writes(update):
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

    if not require_link_for_writes(update):
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

    if not require_link_for_writes(update):
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

    if not require_link_for_writes(update):
        return ConversationHandler.END

    if query.data != "cash:confirm":
        query.answer()
        return CASH_CONFIRM

    factory_id = resolve_factory_id(chat_id)
    kind = context.user_data.get("cash_kind")
    amount = context.user_data.get("cash_amount")
    note = context.user_data.get("cash_note", "")

    if not kind or not amount:
        query.answer("Нет данных", show_alert=True)
        return ConversationHandler.END

    # Create cash record
    rec = CashRecord(
        factory_id=factory_id,
        type=kind,
        amount=amount,
        note=note,
        created_at=datetime.utcnow(),
    )
    db.session.add(rec)
    db.session.commit()

    query.answer("✅ Saved")
    query.edit_message_text(
        "✅ Запись добавлена в кассу.",
        reply_markup=neo_menu_kb()
    )
    return ConversationHandler.END


# ------------------------------------------------------------------------------
# MAIN
# ------------------------------------------------------------------------------

def main():
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set in app.telegram_config")

    logger.info("Starting Telegram bot...")
    updater = Updater(TELEGRAM_BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    # commands (keep old)
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("help", help_cmd))
    dp.add_handler(CommandHandler("id", chat_id_cmd))
    dp.add_handler(CommandHandler("menu", menu_cmd))
    dp.add_handler(CommandHandler("link", link_cmd))

    dp.add_handler(CommandHandler("alerts", alerts))
    dp.add_handler(CommandHandler("shop_low", shop_low))
    dp.add_handler(CommandHandler("shop_stock", shop_stock))
    dp.add_handler(CommandHandler("pending", pending))
    dp.add_handler(CommandHandler("last_moves", last_moves))
    dp.add_handler(CommandHandler("product", product_cmd))

    # conversation handlers MUST be added BEFORE generic menu callbacks
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

    # product details callback (kept)
    dp.add_handler(CallbackQueryHandler(product_detail_callback, pattern=r"^prod:\d+$"))

    # menu callback router (new)
    dp.add_handler(CallbackQueryHandler(menu_callback, pattern=r"^m:"))

    logger.info("Bot started. Waiting for updates...")
    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()