import logging

from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext

from app import create_app, db
from app.models import Product, ShopStock
from app.telegram_config import TELEGRAM_BOT_TOKEN, MANAGER_CHAT_IDS

# --------------------------------------------------------------------------------------
# Flask app context (so we can use models / DB inside Telegram handlers)
# --------------------------------------------------------------------------------------
flask_app = create_app()
flask_app.app_context().push()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def is_manager(chat_id: int) -> bool:
    """Only allow known manager chat_ids (you, dad, etc)."""
    return chat_id in MANAGER_CHAT_IDS


# --------------------------------------------------------------------------------------
# /start and /help
# --------------------------------------------------------------------------------------
def start(update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id
    if not is_manager(chat_id):
        update.message.reply_text("Нет доступа.")
        return

    update.message.reply_text(
        "Ассаламу алейкум!\n\n"
        "Доступные команды:\n"
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
    if not is_manager(chat_id):
        update.message.reply_text("Нет доступа.")
        return

    # Товары с остатком < 5 шт.
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
    if not is_manager(chat_id):
        update.message.reply_text("Нет доступа.")
        return

    args = context.args
    search = None
    if args:
        search = " ".join(args).strip().lower()

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

    updater = Updater(TELEGRAM_BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("help", help_cmd))
    dp.add_handler(CommandHandler("shop_low", shop_low))
    dp.add_handler(CommandHandler("shop_stock", shop_stock))

    logger.info("Telegram bot started. Listening for commands...")
    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
