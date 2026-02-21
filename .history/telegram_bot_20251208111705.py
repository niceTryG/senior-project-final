import logging

from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext

# assuming telegram_bot.py is in project root next to run.py
from app import create_app, db
from app.models import Product, ShopStock
from app.telegram_config import TELEGRAM_BOT_TOKEN, MANAGER_CHAT_IDS

# --------------------------------------------------------------------------------------
# Flask app
# --------------------------------------------------------------------------------------
flask_app = create_app()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def is_manager(chat_id: int) -> bool:
    """
    Access control for bot commands.

    DEBUG MODE:
      - If MANAGER_CHAT_IDS is empty → allow everyone.
      - Otherwise → check membership.
    """
    if not MANAGER_CHAT_IDS:
        return True
    return chat_id in MANAGER_CHAT_IDS


# --------------------------------------------------------------------------------------
# /id — show your chat id (for config)
# --------------------------------------------------------------------------------------
def chat_id_cmd(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id
    text = (
        f"Ваш chat_id: <b>{chat_id}</b>\n"
        "Добавьте его в MANAGER_CHAT_IDS в app/telegram_config.py."
    )
    logger.info("User requested chat_id: %s", chat_id)
    update.message.reply_html(text)


# --------------------------------------------------------------------------------------
# /start and /help
# --------------------------------------------------------------------------------------
def start(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id
    logger.info("Received /start from chat_id=%s", chat_id)

    if not is_manager(chat_id):
        update.message.reply_text("Нет доступа.")
        return

    update.message.reply_text(
        "Ассаламу алейкум!\n\n"
        "Доступные команды:\n"
        "/id — показать ваш chat_id\n"
        "/shop_low — товары в магазине с низким остатком\n"
        "/shop_stock [поиск] — остатки в магазине (можно добавить слово для поиска)\n\n"
        "Примеры:\n"
        "/shop_low\n"
        "/shop_stock bodik\n"
    )


def help_cmd(update: Update, context: CallbackContext) -> None:
    return start(update, context)


# --------------------------------------------------------------------------------------
# /shop_low — low stock in shop (quantity < 5)
# --------------------------------------------------------------------------------------
def shop_low(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id
    logger.info("Received /shop_low from chat_id=%s", chat_id)

    if not is_manager(chat_id):
        update.message.reply_text("Нет доступа.")
        return

    # ✅ app context for DB
    with flask_app.app_context():
        low_items = (
            db.session.query(ShopStock)
            .join(Product)
            .filter(ShopStock.quantity < 5)
            .order_by(ShopStock.quantity.asc())
            .all()
        )

    if not low_items:
        update.message.reply_text("В магазине нет товаров с низким остатком. 👍")
        return

    lines = ["⚠️ Товары с низким остатком в магазине:\n"]
    for row in low_items:
        p: Product = row.product
        lines.append(
            f"• {p.name} ({p.category or '-'}): "
            f"{row.quantity} шт. "
            f"цена {p.sell_price_per_item or 0} {p.currency}"
        )

    update.message.reply_text("\n".join(lines))


# --------------------------------------------------------------------------------------
# /shop_stock [filter] — show stock, optional search word
# --------------------------------------------------------------------------------------
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

    # ✅ app context for DB
    with flask_app.app_context():
        query = (
            db.session.query(ShopStock)
            .join(Product)
            .filter(ShopStock.quantity > 0)
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


# --------------------------------------------------------------------------------------
# main() — run long polling
# --------------------------------------------------------------------------------------
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

    logger.info("Bot started. Waiting for updates...")
    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
