import logging
from typing import List, Callable
from functools import wraps

from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Updater, CommandHandler, CallbackContext, CallbackQueryHandler


from app import create_app, db
import app.telegram_config as telegram_config
from app.models import Product, ShopStock, ShopOrder, StockMovement


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
# HELPERS
# ------------------------------------------------------------------------------

def is_manager(chat_id: int) -> bool:
    """
    Access control:
      - if MANAGER_CHAT_IDS is empty → allow everyone (debug mode)
      - else → only chat_ids from list
    """
    if not MANAGER_CHAT_IDS:
        return True
    return chat_id in MANAGER_CHAT_IDS


def with_flask_context(func: Callable) -> Callable:
    """
    Decorator: run handler inside Flask app_context
    so db/session/models/current_app all work.
    """
    @wraps(func)
    def wrapper(update: Update, context: CallbackContext, *args, **kwargs):
        with flask_app.app_context():
            return func(update, context, *args, **kwargs)
    return wrapper


def deny_if_not_manager(update: Update) -> bool:
    """Small helper to check access and send 'Нет доступа'."""
    chat_id = update.effective_chat.id
    if not is_manager(chat_id):
        update.message.reply_text("Нет доступа.")
        return True
    return False


# ------------------------------------------------------------------------------
# BASIC COMMANDS: /start, /help, /id
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

    if deny_if_not_manager(update):
        return

    keyboard = [
        ["/alerts", "/shop_low"],
        ["/shop_stock", "/pending"],
        ["/last_moves", "/product"],
        ["/id"],
    ]
    reply_kb = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    update.message.reply_text(
        "Ассаламу алейкум!\n\n"
        "Это мини-панель менеджера Mini Moda в Telegram.\n\n"
        "Главные команды:\n"
        "• /alerts — короткий обзор: низкий остаток + заказы\n"
        "• /shop_low — список товаров с низким остатком в магазине\n"
        "• /shop_stock [слово] — остатки по складу магазина\n"
        "• /pending — заказы магазина в статусе 'pending'\n"
        "• /last_moves — последние движения по складу\n"
        "• /product <id или название> — информация по модели\n"
        "• /id — показать ваш chat_id\n\n"
        "Можно просто нажимать кнопки внизу 👍",
        reply_markup=reply_kb,
    )


def help_cmd(update: Update, context: CallbackContext) -> None:
    # just reuse /start text
    return start(update, context)


# ------------------------------------------------------------------------------
# /alerts — short manager summary (no deep details)
# ------------------------------------------------------------------------------

@with_flask_context
def alerts(update: Update, context: CallbackContext) -> None:
    if deny_if_not_manager(update):
        return

    # 1) low stock count in shop
    low_count = (
        db.session.query(ShopStock)
        .join(Product)
        .filter(
            Product.factory_id == DEFAULT_FACTORY_ID,
            ShopStock.quantity < LOW_STOCK_THRESHOLD,
        )
        .count()
    )

    # 2) pending shop orders count
    pending_count = (
        ShopOrder.query
        .filter_by(factory_id=DEFAULT_FACTORY_ID, status="pending")
        .count()
    )

    # 3) last movement timestamp
    last_mv = (
        StockMovement.query
        .filter_by(factory_id=DEFAULT_FACTORY_ID)
        .order_by(StockMovement.timestamp.desc())
        .first()
    )
    if last_mv and last_mv.timestamp:
        last_mv_str = last_mv.timestamp.strftime("%d.%m %H:%M")
    else:
        last_mv_str = "нет данных"

    txt = (
        "📊 Краткий обзор\n\n"
        f"• Товаров с низким остатком в магазине (<{LOW_STOCK_THRESHOLD} шт.): {low_count}\n"
        f"• Заказов магазина в статусе 'pending': {pending_count}\n"
        f"• Последнее движение по складу: {last_mv_str}\n\n"
        "Подробнее:\n"
        "— /shop_low — детали по низкому остатку\n"
        "— /pending — список заказов\n"
        "— /last_moves — последние движения"
    )

    # IMPORTANT: plain text, no HTML parsing
    update.message.reply_text(txt)



# ------------------------------------------------------------------------------
# /shop_low — list low stock items in shop
# ------------------------------------------------------------------------------

@with_flask_context
def shop_low(update: Update, context: CallbackContext) -> None:
    if deny_if_not_manager(update):
        return

    low_items = (
        db.session.query(ShopStock)
        .join(Product)
        .filter(
            Product.factory_id == DEFAULT_FACTORY_ID,
            ShopStock.quantity < LOW_STOCK_THRESHOLD,
        )
        .order_by(ShopStock.quantity.asc())
        .all()
    )

    if not low_items:
        update.message.reply_text("В магазине нет товаров с низким остатком. 👍")
        return

    lines = [
        f"⚠️ Товары с остатком < {LOW_STOCK_THRESHOLD} в магазине:\n"
    ]
    for row in low_items:
        p: Product = row.product
        lines.append(
            f"• {p.name} ({p.category or '-'}) — "
            f"{row.quantity} шт., {p.sell_price_per_item or 0} {p.currency}"
        )

    update.message.reply_text("\n".join(lines))


# ------------------------------------------------------------------------------
# /shop_stock [filter] — show shop stock, optional text filter
# ------------------------------------------------------------------------------

@with_flask_context
def shop_stock(update: Update, context: CallbackContext) -> None:
    if deny_if_not_manager(update):
        return

    args = context.args
    search = None
    if args:
        search = " ".join(args).strip().lower()

    query = (
        db.session.query(ShopStock)
        .join(Product)
        .filter(
            Product.factory_id == DEFAULT_FACTORY_ID,
            ShopStock.quantity > 0,
        )
        .order_by(ShopStock.quantity.asc())
    )

    if search:
        query = query.filter(Product.name.ilike(f"%{search}%"))

    items = query.limit(25).all()

    if not items:
        if search:
            update.message.reply_text(f"Ничего не найдено по запросу: “{search}”.")
        else:
            update.message.reply_text("В магазине нет товаров с остатком > 0.")
        return

    if search:
        header = f"📊 Остатки в магазине (поиск: “{search}”):\n"
    else:
        header = "📊 Остатки в магазине (первые 25 позиций):\n"

    lines = [header]
    for row in items:
        p: Product = row.product
        lines.append(
            f"• {p.name} ({p.category or '-'}) — "
            f"{row.quantity} шт., {p.sell_price_per_item or 0} {p.currency}"
        )

    update.message.reply_text("\n".join(lines))


# ------------------------------------------------------------------------------
# /pending — pending shop orders (short list)
# ------------------------------------------------------------------------------

@with_flask_context
def pending(update: Update, context: CallbackContext) -> None:
    if deny_if_not_manager(update):
        return

    orders = (
        ShopOrder.query
        .filter_by(factory_id=DEFAULT_FACTORY_ID, status="pending")
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
        lines.append(
            f"• №{o.id}: {item_count} позиций, создан {created}"
        )

    update.message.reply_text("\n".join(lines))


# ------------------------------------------------------------------------------
# /last_moves — last stock movements
# ------------------------------------------------------------------------------

@with_flask_context
def last_moves(update: Update, context: CallbackContext) -> None:
    if deny_if_not_manager(update):
        return

    moves = (
        StockMovement.query
        .filter_by(factory_id=DEFAULT_FACTORY_ID)
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
# /product <id or name> — single product view (factory + shop)
# ------------------------------------------------------------------------------
@with_flask_context
def product_cmd(update: Update, context: CallbackContext) -> None:
    """
    /product [text]

    Примеры:
      /product        -> первые 10 моделей
      /product bodik  -> модели где в имени есть 'bodik'
    Показывает список с кнопками. Нажимаешь кнопку -> подробности по товару.
    """
    if deny_if_not_manager(update):
        return

    args = context.args
    if args:
        search = " ".join(args).strip()
    else:
        search = None

    base_q = Product.query.filter_by(factory_id=DEFAULT_FACTORY_ID)

    if search:
        products = (
            base_q.filter(Product.name.ilike(f"%{search}%"))
            .order_by(Product.name.asc())
            .limit(10)
            .all()
        )
    else:
        products = (
            base_q
            .order_by(Product.name.asc())
            .limit(10)
            .all()
        )

    if not products:
        if search:
            update.message.reply_text(f"Товары по запросу “{search}” не найдены.")
        else:
            update.message.reply_text("В базе нет товаров.")
        return

    # Текст заголовка
    if search:
        header = f"Найдено моделей (первые {len(products)}): “{search}”\n\nНажмите на нужную модель:"
    else:
        header = f"Первые {len(products)} моделей:\n\nНажмите на нужную модель:"

    # Кнопки по одной в строке
    buttons = []
    for p in products:
        btn_text = f"{p.name} ({p.category or '-'})"
        callback_data = f"prod:{p.id}"
        buttons.append([InlineKeyboardButton(btn_text, callback_data=callback_data)])

    keyboard = InlineKeyboardMarkup(buttons)

    update.message.reply_text(header, reply_markup=keyboard)



# ------------------------------------------------------------------------------
# MAIN
# ------------------------------------------------------------------------------

def main():
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set in app.telegram_config")

    logger.info("Starting Telegram bot...")
    updater = Updater(TELEGRAM_BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("help", help_cmd))
    dp.add_handler(CommandHandler("id", chat_id_cmd))

    dp.add_handler(CommandHandler("alerts", alerts))
    dp.add_handler(CommandHandler("shop_low", shop_low))
    dp.add_handler(CommandHandler("shop_stock", shop_stock))
    dp.add_handler(CommandHandler("pending", pending))
    dp.add_handler(CommandHandler("last_moves", last_moves))
    dp.add_handler(CommandHandler("product", product_cmd))

    logger.info("Bot started. Waiting for updates...")
    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
