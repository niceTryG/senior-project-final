import logging
from typing import List

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackContext

from app import create_app, db
import app.telegram_config as telegram_config
from app.models import Product, ShopStock, ShopOrder, ShopOrderItem, StockMovement

# ------------------------------------------------------------------------------
# CONFIG FROM telegram_config
# ------------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = telegram_config.TELEGRAM_BOT_TOKEN
MANAGER_CHAT_IDS: List[int] = getattr(telegram_config, "MANAGER_CHAT_IDS", [])
DEFAULT_FACTORY_ID: int = getattr(telegram_config, "DEFAULT_FACTORY_ID", 1)
LOW_STOCK_THRESHOLD: int = getattr(telegram_config, "LOW_STOCK_THRESHOLD", 5)

# ------------------------------------------------------------------------------
# FLASK APP
# ------------------------------------------------------------------------------
flask_app = create_app()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def is_manager(chat_id: int) -> bool:
    """
    Access control for bot commands.

    DEBUG:
      - If MANAGER_CHAT_IDS is empty → allow everyone.
      - Otherwise → only ids from list.
    """
    if not MANAGER_CHAT_IDS:
        return True
    return chat_id in MANAGER_CHAT_IDS


# ------------------------------------------------------------------------------
# /id — show chat id
# ------------------------------------------------------------------------------
def chat_id_cmd(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id
    text = (
        f"Ваш chat_id: <b>{chat_id}</b>\n"
        "Добавьте его в MANAGER_CHAT_IDS в app/telegram_config.py."
    )
    logger.info("User requested chat_id: %s", chat_id)
    update.message.reply_html(text)


# ------------------------------------------------------------------------------
# /start and /help — show menu + keyboard
# ------------------------------------------------------------------------------
def start(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id
    logger.info("Received /start from chat_id=%s", chat_id)

    if not is_manager(chat_id):
        update.message.reply_text("Нет доступа.")
        return

    keyboard = [
        ["/shop_low", "/shop_stock"],
        ["/pending", "/last_moves"],
        ["/id"],
    ]
    reply_kb = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    update.message.reply_text(
        "Ассаламу алейкум!\n\n"
        "Мини-панель менеджера (Telegram)\n\n"
        "Команды:\n"
        "• /shop_low — товары с низким остатком в магазине\n"
        "• /shop_stock [слово] — остатки по складу магазина\n"
        "• /pending — заказы магазина в статусе 'pending'\n"
        "• /last_moves — последние движения по складу\n"
        "• /id — показать ваш chat_id\n\n"
        "Можете нажимать кнопки внизу.",
        reply_markup=reply_kb,
    )


def help_cmd(update: Update, context: CallbackContext) -> None:
    return start(update, context)


# ------------------------------------------------------------------------------
# /shop_low — low stock in shop (quantity < LOW_STOCK_THRESHOLD)
# ------------------------------------------------------------------------------
def shop_low(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id
    logger.info("Received /shop_low from chat_id=%s", chat_id)

    if not is_manager(chat_id):
        update.message.reply_text("Нет доступа.")
        return

    with flask_app.app_context():
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
                f"• {p.name} ({p.category or '-'}): "
                f"{row.quantity} шт., {p.sell_price_per_item or 0} {p.currency}"
            )

    update.message.reply_text("\n".join(lines))


# ------------------------------------------------------------------------------
# /shop_stock [filter] — show shop stock, optional search
# ------------------------------------------------------------------------------
def shop_stock(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id
    logger.info("Received /shop_stock from chat_id=%s args=%s", chat_id, context.args)

    if not is_manager(chat_id):
        update.message.reply_text("Нет доступа.")
        return

    args = context.args
    search = None
    if args:
        search = " ".join(args).strip().lower()

    with flask_app.app_context():
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
# /pending — pending shop orders for factory (for dad)
# ------------------------------------------------------------------------------
def pending(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id
    logger.info("Received /pending from chat_id=%s", chat_id)

    if not is_manager(chat_id):
        update.message.reply_text("Нет доступа.")
        return

    with flask_app.app_context():
        orders = (
            ShopOrder.query
            .filter_by(factory_id=DEFAULT_FACTORY_ID, status="pending")
            .order_by(ShopOrder.created_at.asc())
            .limit(5)
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
# /last_moves — last stock movements (factory <-> shop <-> customer)
# ------------------------------------------------------------------------------
def last_moves(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id
    logger.info("Received /last_moves from chat_id=%s", chat_id)

    if not is_manager(chat_id):
        update.message.reply_text("Нет доступа.")
        return

    with flask_app.app_context():
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
    dp.add_handler(CommandHandler("shop_low", shop_low))
    dp.add_handler(CommandHandler("shop_stock", shop_stock))
    dp.add_handler(CommandHandler("pending", pending))
    dp.add_handler(CommandHandler("last_moves", last_moves))

    logger.info("Bot started. Waiting for updates...")
    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
