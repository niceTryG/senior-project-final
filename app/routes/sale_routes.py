from datetime import datetime, date, timedelta

import pandas as pd
from flask import Blueprint, render_template, request, flash, url_for, redirect
from flask_login import login_required, current_user

from app.telegram_notify import send_telegram_message

from ..auth_utils import roles_required
from ..extensions import db
from ..models import (
    Sale,
    Product,
    ShopStock,
    WholesaleSale,
    WholesaleSaleItem,
    Movement,
    ShopFactoryLink,
    RealizatsiyaSettlement,
)
from ..services.shop_service import ShopService
from ..translations import t

sales_bp = Blueprint("sales", __name__, url_prefix="/sales")

shop_service = ShopService()


def _role_flag(name: str) -> bool:
    return bool(getattr(current_user, name, False))


def _is_shop_only_user() -> bool:
    return _role_flag("is_shop") and not (
        _role_flag("is_manager") or _role_flag("is_admin")
    )


def _user_can_access_sales() -> bool:
    return any(
        [
            _role_flag("is_shop"),
            _role_flag("is_manager"),
            _role_flag("is_admin"),
            _role_flag("is_shop_manager"),
            _role_flag("is_shop_admin"),
            _role_flag("is_factory_manager"),
            _role_flag("is_accountant"),
        ]
    )


def _user_can_record_settlements() -> bool:
    return any(
        [
            _role_flag("is_shop"),
            _role_flag("is_admin"),
            _role_flag("is_accountant"),
            _role_flag("is_shop_manager"),
            _role_flag("is_shop_admin"),
        ]
    )


def _get_shop_for_sales():
    if _role_flag("is_shop") and getattr(current_user, "shop_id", None):
        return current_user.shop

    factory_id = getattr(current_user, "factory_id", None)
    if not factory_id:
        return None

    return shop_service._get_or_create_default_shop(factory_id)


def _get_shop_factory_ids(shop) -> set[int]:
    if not shop:
        return set()

    ids = set()

    link_rows = (
        ShopFactoryLink.query.filter(ShopFactoryLink.shop_id == shop.id)
        .with_entities(ShopFactoryLink.factory_id)
        .all()
    )
    ids.update(fid for (fid,) in link_rows if fid)

    stock_rows = (
        ShopStock.query.filter(
            ShopStock.shop_id == shop.id,
            ShopStock.source_factory_id.isnot(None),
        )
        .with_entities(ShopStock.source_factory_id)
        .distinct()
        .all()
    )
    ids.update(fid for (fid,) in stock_rows if fid)

    if not _role_flag("is_shop") and getattr(current_user, "factory_id", None):
        ids = {fid for fid in ids if fid == current_user.factory_id}

    return ids


def _get_available_wholesale_factories(shop):
    if not shop:
        return []

    query = (
        db.session.query(
            ShopStock.source_factory_id.label("factory_id"),
            db.func.sum(ShopStock.quantity).label("total_qty"),
            db.func.count(ShopStock.id).label("rows_count"),
        )
        .join(Product, Product.id == ShopStock.product_id)
        .filter(
            ShopStock.shop_id == shop.id,
            ShopStock.quantity > 0,
        )
        .group_by(ShopStock.source_factory_id)
        .order_by(ShopStock.source_factory_id.asc())
    )

    rows = query.all()
    if not rows:
        return []

    factory_ids = [r.factory_id for r in rows if r.factory_id]
    if not factory_ids:
        return []

    links = (
        ShopFactoryLink.query.filter(
            ShopFactoryLink.shop_id == shop.id,
            ShopFactoryLink.factory_id.in_(factory_ids),
        ).all()
    )
    linked_factory_ids = {x.factory_id for x in links}

    from ..models import Factory

    factories = Factory.query.filter(Factory.id.in_(factory_ids)).all()
    factory_map = {f.id: f for f in factories}

    result = []
    for row in rows:
        if row.factory_id not in factory_map:
            continue
        if linked_factory_ids and row.factory_id not in linked_factory_ids:
            continue

        if (_role_flag("is_manager") or _role_flag("is_admin")) and not _role_flag("is_shop"):
            if getattr(current_user, "factory_id", None) and row.factory_id != current_user.factory_id:
                continue

        result.append(
            {
                "factory_id": row.factory_id,
                "factory_name": factory_map[row.factory_id].name,
                "total_qty": int(row.total_qty or 0),
                "rows_count": int(row.rows_count or 0),
            }
        )

    return result


def _get_allowed_realizatsiya_factory_ids(shop) -> set[int]:
    if not shop:
        return set()

    ids = set()

    linked = ShopFactoryLink.query.filter_by(shop_id=shop.id).all()
    ids.update(x.factory_id for x in linked if x.factory_id)

    stock_ids = (
        db.session.query(ShopStock.source_factory_id)
        .filter(
            ShopStock.shop_id == shop.id,
            ShopStock.source_factory_id.isnot(None),
        )
        .distinct()
        .all()
    )
    ids.update(x[0] for x in stock_ids if x and x[0])

    sold_ids = (
        db.session.query(WholesaleSaleItem.source_factory_id)
        .join(WholesaleSale, WholesaleSale.id == WholesaleSaleItem.wholesale_sale_id)
        .filter(
            WholesaleSale.shop_id == shop.id,
            WholesaleSaleItem.source_factory_id.isnot(None),
        )
        .distinct()
        .all()
    )
    ids.update(x[0] for x in sold_ids if x and x[0])

    if not _role_flag("is_shop") and getattr(current_user, "factory_id", None):
        ids = {x for x in ids if x == current_user.factory_id}

    return ids


def _build_wholesale_scope_query(shop, q="", date_from=None, date_to=None):
    query = (
        WholesaleSale.query
        .join(WholesaleSaleItem, WholesaleSaleItem.wholesale_sale_id == WholesaleSale.id)
        .join(Product, Product.id == WholesaleSaleItem.product_id)
        .filter(WholesaleSale.shop_id == shop.id)
    )

    if not _role_flag("is_shop") and getattr(current_user, "factory_id", None):
        query = query.filter(WholesaleSaleItem.source_factory_id == current_user.factory_id)

    if q:
        like = f"%{q.lower()}%"
        query = query.filter(
            db.or_(
                db.func.lower(db.func.coalesce(WholesaleSale.customer_name, "")).like(like),
                db.func.lower(db.func.coalesce(WholesaleSale.customer_phone, "")).like(like),
                db.func.lower(db.func.coalesce(WholesaleSaleItem.product_name_snapshot, "")).like(like),
                db.func.lower(db.func.coalesce(Product.name, "")).like(like),
                db.func.lower(db.func.coalesce(Product.category, "")).like(like),
            )
        )

    if date_from:
        query = query.filter(db.func.date(WholesaleSale.created_at) >= date_from)
    if date_to:
        query = query.filter(db.func.date(WholesaleSale.created_at) <= date_to)

    return query


def _build_regular_sales_query(shop=None, q="", date_from=None, date_to=None):
    query = Sale.query.join(Product, Product.id == Sale.product_id)

    # Best-possible scoping:
    # 1) exact shop scoping if Sale.shop_id exists
    # 2) otherwise shop-only users fall back to linked factories
    if shop is not None:
        query = query.filter(Sale.shop_id == shop.id)
    else:
        if _is_shop_only_user():
            return query.filter(Sale.id == -1)

        factory_id = getattr(current_user, "factory_id", None)
        if factory_id:
            query = query.filter(Product.factory_id == factory_id)

    if q:
        like = f"%{q.lower()}%"
        query = query.filter(
            db.or_(
                db.func.lower(db.func.coalesce(Sale.customer_name, "")).like(like),
                db.func.lower(db.func.coalesce(Sale.customer_phone, "")).like(like),
                db.func.lower(db.func.coalesce(Product.name, "")).like(like),
                db.func.lower(db.func.coalesce(Product.category, "")).like(like),
            )
        )

    if date_from:
        query = query.filter(Sale.date >= date_from)
    if date_to:
        query = query.filter(Sale.date <= date_to)

    return query


def _build_realizatsiya_snapshot(shop):
    grouped = {}

    stock_rows = (
        ShopStock.query
        .join(Product, Product.id == ShopStock.product_id)
        .filter(
            ShopStock.shop_id == shop.id,
            ShopStock.quantity > 0,
        )
        .all()
    )

    for row in stock_rows:
        if not _role_flag("is_shop") and getattr(current_user, "factory_id", None):
            if row.source_factory_id != current_user.factory_id:
                continue

        factory_id = row.source_factory_id or getattr(row.product, "factory_id", 0) or 0
        factory_name = (
            getattr(row.source_factory, "name", None)
            or getattr(getattr(row.product, "factory", None), "name", None)
            or f"Factory #{factory_id}"
        )
        currency = getattr(row.product, "currency", None) or "UZS"
        qty = int(row.quantity or 0)
        base_price = float(getattr(row.product, "cost_price_per_item", 0) or 0)

        if factory_id not in grouped:
            grouped[factory_id] = {
                "factory_id": factory_id,
                "factory_name": factory_name,
                "qty_in_shop": 0,
                "value_in_shop": 0.0,
                "currency": currency,
            }

        grouped[factory_id]["qty_in_shop"] += qty
        grouped[factory_id]["value_in_shop"] += qty * base_price

    return grouped


def _build_settlement_map(shop, date_from=None, date_to=None):
    grouped = {}
    total_amount = 0.0
    currency = "UZS"

    query = RealizatsiyaSettlement.query.filter(
        RealizatsiyaSettlement.shop_id == shop.id
    )

    if not _role_flag("is_shop") and getattr(current_user, "factory_id", None):
        query = query.filter(RealizatsiyaSettlement.factory_id == current_user.factory_id)

    if date_from:
        query = query.filter(RealizatsiyaSettlement.settlement_date >= date_from)
    if date_to:
        query = query.filter(RealizatsiyaSettlement.settlement_date <= date_to)

    settlements = query.order_by(
        RealizatsiyaSettlement.settlement_date.desc(),
        RealizatsiyaSettlement.id.desc(),
    ).all()

    for row in settlements:
        factory_id = row.factory_id or 0
        factory_name = getattr(row.factory, "name", None) or f"Factory #{factory_id}"
        amount = float(row.amount or 0)
        cur = row.currency or "UZS"

        if factory_id not in grouped:
            grouped[factory_id] = {
                "factory_id": factory_id,
                "factory_name": factory_name,
                "settled_amount": 0.0,
                "currency": cur,
            }

        grouped[factory_id]["settled_amount"] += amount
        grouped[factory_id]["currency"] = cur
        total_amount += amount
        currency = cur

    return grouped, round(total_amount, 2), currency


@sales_bp.route("/realizatsiya/settlements/create", methods=["POST"])
@login_required
def create_realizatsiya_settlement():
    if not _user_can_record_settlements():
        flash("У вас нет доступа к записи выплат по реализации.", "danger")
        return redirect(url_for("main.dashboard"))

    shop = _get_shop_for_sales()
    if not shop:
        flash("Магазин не найден.", "danger")
        return redirect(url_for("main.dashboard"))

    try:
        factory_id = int(request.form.get("factory_id") or 0)
    except (TypeError, ValueError):
        factory_id = 0

    try:
        amount = float(request.form.get("amount") or 0)
    except (TypeError, ValueError):
        amount = 0.0

    settlement_date_raw = (request.form.get("settlement_date") or "").strip()
    note = (request.form.get("note") or "").strip() or None
    currency = (request.form.get("currency") or "UZS").strip() or "UZS"

    if factory_id <= 0:
        flash("Выберите фабрику.", "warning")
        return redirect(request.referrer or url_for("sales.shop_sales_overview"))

    if amount <= 0:
        flash("Сумма должна быть больше нуля.", "warning")
        return redirect(request.referrer or url_for("sales.shop_sales_overview"))

    allowed_factory_ids = _get_allowed_realizatsiya_factory_ids(shop)
    if allowed_factory_ids and factory_id not in allowed_factory_ids:
        flash("Эта фабрика недоступна для данной реализации.", "danger")
        return redirect(request.referrer or url_for("sales.shop_sales_overview"))

    settlement_date = date.today()
    if settlement_date_raw:
        try:
            settlement_date = datetime.strptime(settlement_date_raw, "%Y-%m-%d").date()
        except ValueError:
            flash("Неверная дата выплаты.", "warning")
            return redirect(request.referrer or url_for("sales.shop_sales_overview"))

    due_rows = (
        db.session.query(
            db.func.coalesce(
                db.func.sum(
                    WholesaleSaleItem.quantity * WholesaleSaleItem.cost_price_per_item
                ),
                0.0,
            )
        )
        .join(WholesaleSale, WholesaleSale.id == WholesaleSaleItem.wholesale_sale_id)
        .filter(
            WholesaleSale.shop_id == shop.id,
            WholesaleSaleItem.source_factory_id == factory_id,
        )
        .scalar()
    )
    total_due = float(due_rows or 0.0)

    settled_rows = (
        db.session.query(
            db.func.coalesce(db.func.sum(RealizatsiyaSettlement.amount), 0.0)
        )
        .filter(
            RealizatsiyaSettlement.shop_id == shop.id,
            RealizatsiyaSettlement.factory_id == factory_id,
        )
        .scalar()
    )
    total_settled = float(settled_rows or 0.0)

    remaining_before = round(total_due - total_settled, 2)

    if remaining_before <= 0:
        flash(
            "По этой фабрике уже нет непогашенного остатка. Новая выплата не нужна.",
            "warning",
        )
        return redirect(request.referrer or url_for("sales.shop_sales_overview"))

    if amount > remaining_before:
        flash(
            f"Сумма выплаты больше остатка по реализации. "
            f"Осталось погасить только {remaining_before:.2f} {currency}.",
            "danger",
        )
        return redirect(request.referrer or url_for("sales.shop_sales_overview"))

    settlement = RealizatsiyaSettlement(
        shop_id=shop.id,
        factory_id=factory_id,
        settlement_date=settlement_date,
        amount=amount,
        currency=currency,
        note=note,
        created_by_id=getattr(current_user, "id", None),
    )
    db.session.add(settlement)
    db.session.commit()

    try:
        factory_name = getattr(settlement.factory, "name", None) or f"Factory #{factory_id}"
        remaining_after = round(remaining_before - amount, 2)

        msg = (
            "💳 <b>Выплата по реализации</b>\n"
            f"Фабрика: <b>{factory_name}</b>\n"
            f"Сумма: <b>{amount:.2f} {currency}</b>\n"
            f"Дата: <b>{settlement_date.strftime('%Y-%m-%d')}</b>\n"
            f"Остаток после выплаты: <b>{remaining_after:.2f} {currency}</b>"
        )
        if note:
            msg += f"\nПримечание: {note}"
        send_telegram_message(
            msg,
            factory_id=factory_id,
            include_manager_chats=False,
        )
    except Exception:
        pass

    flash("Выплата по реализации сохранена.", "success")
    return redirect(request.referrer or url_for("sales.shop_sales_overview"))


@sales_bp.route("/realizatsiya/settlements/<int:settlement_id>/delete", methods=["POST"])
@login_required
def delete_realizatsiya_settlement(settlement_id: int):
    if not _user_can_record_settlements():
        flash("У вас нет доступа к удалению выплат по реализации.", "danger")
        return redirect(url_for("main.dashboard"))

    shop = _get_shop_for_sales()
    if not shop:
        flash("Магазин не найден.", "danger")
        return redirect(url_for("main.dashboard"))

    settlement = RealizatsiyaSettlement.query.filter(
        RealizatsiyaSettlement.id == settlement_id,
        RealizatsiyaSettlement.shop_id == shop.id,
    ).first_or_404()

    db.session.delete(settlement)
    db.session.commit()

    flash("Выплата по реализации удалена.", "success")
    return redirect(request.referrer or url_for("sales.shop_sales_overview"))


@sales_bp.route("/import-dad-excel", methods=["GET", "POST"])
@login_required
def import_dad_excel():
    if request.method == "GET":
        return render_template("sales/import_dad_excel.html")

    file = request.files.get("file")
    if not file:
        flash("Файл не выбран", "warning")
        return redirect(url_for("sales.import_dad_excel"))

    factory_id = getattr(current_user, "factory_id", None)
    if not factory_id:
        flash("Ошибка: у пользователя нет factory_id", "danger")
        return redirect(url_for("main.dashboard"))

    try:
        df = pd.read_excel(file, sheet_name=0, header=None)

        header_row = None
        for i in range(15):
            row = df.iloc[i].astype(str).str.lower()
            if "модель" in " ".join(row.values):
                header_row = i
                break

        if header_row is None:
            raise ValueError("Не найдена таблица 'Реализация'")

        df = pd.read_excel(file, sheet_name=0, header=header_row)
        df.columns = [str(c).strip().lower() for c in df.columns]

        created_sales = 0
        created_orders = 0

        for _, row in df.iterrows():
            model = str(row.get("модель", "")).strip()
            if not model or model.lower() == "nan":
                continue

            qty = int(row.get("сони", 0) or 0)
            price = int(row.get("нархи", 0) or 0)
            raw_date = row.get("число")

            if qty <= 0 or price <= 0:
                continue

            if isinstance(raw_date, datetime):
                sold_at = raw_date
            else:
                try:
                    sold_at = pd.to_datetime(raw_date, dayfirst=True)
                except Exception:
                    sold_at = datetime.utcnow()

            product = Product.query.filter_by(
                factory_id=factory_id,
                name=model,
            ).first()

            if not product:
                product = Product(
                    factory_id=factory_id,
                    name=model,
                    cost_price_per_item=price,
                    sell_price_per_item=price,
                    quantity=0,
                    currency="UZS",
                )
                db.session.add(product)
                db.session.flush()

            default_shop = shop_service._get_or_create_default_shop(product.factory_id)
            stock = ShopStock.query.filter_by(
                shop_id=default_shop.id,
                product_id=product.id,
            ).first()
            available = int(stock.quantity or 0) if stock else 0

            if available < qty:
                created_orders += 1
                sold_qty = available
            else:
                sold_qty = qty

            if sold_qty > 0:
                sale = Sale(
                    product_id=product.id,
                    date=sold_at.date()
                    if hasattr(sold_at, "date")
                    else datetime.utcnow().date(),
                    customer_name=None,
                    customer_phone=None,
                    quantity=sold_qty,
                    sell_price_per_item=price,
                    cost_price_per_item=product.cost_price_per_item or 0,
                    currency=product.currency or "UZS",
                )
                db.session.add(sale)

                if stock:
                    stock.quantity = max(0, int(stock.quantity or 0) - sold_qty)

                created_sales += 1

        db.session.commit()
        flash(
            f"Импорт завершён ✅ Продажи: {created_sales}, Заказы: {created_orders}",
            "success",
        )
        return redirect(url_for("sales.list_sales"))

    except Exception as e:
        db.session.rollback()
        flash(f"Ошибка импорта: {e}", "danger")
        return redirect(url_for("sales.import_dad_excel"))


@sales_bp.route("/", methods=["GET"])
@login_required
@roles_required("admin", "manager", "shop")
def list_sales():
    q = request.args.get("q", "").strip()
    date_from_str = request.args.get("from", "").strip()
    date_to_str = request.args.get("to", "").strip()
    period = request.args.get("period", "").strip().lower()

    date_from = None
    date_to = None
    date_fmt = "%Y-%m-%d"
    today = datetime.utcnow().date()

    if period == "today":
        date_from = today
        date_to = today
        date_from_str = today.strftime(date_fmt)
        date_to_str = today.strftime(date_fmt)

    elif period == "yesterday":
        yesterday = today.fromordinal(today.toordinal() - 1)
        date_from = yesterday
        date_to = yesterday
        date_from_str = yesterday.strftime(date_fmt)
        date_to_str = yesterday.strftime(date_fmt)

    elif period == "week":
        week_start = today.fromordinal(today.toordinal() - today.weekday())
        date_from = week_start
        date_to = today
        date_from_str = week_start.strftime(date_fmt)
        date_to_str = today.strftime(date_fmt)

    else:
        if date_from_str:
            try:
                date_from = datetime.strptime(date_from_str, date_fmt).date()
            except ValueError:
                date_from = None

        if date_to_str:
            try:
                date_to = datetime.strptime(date_to_str, date_fmt).date()
            except ValueError:
                date_to = None

    query = Sale.query.join(Product).filter(Product.factory_id == current_user.factory_id)

    if q:
        like = f"%{q.lower()}%"
        query = query.filter(
            db.or_(
                db.func.lower(db.func.coalesce(Sale.customer_name, "")).like(like),
                db.func.lower(db.func.coalesce(Sale.customer_phone, "")).like(like),
                db.func.lower(Product.name).like(like),
                db.func.lower(db.func.coalesce(Product.category, "")).like(like),
            )
        )

    if date_from:
        query = query.filter(Sale.date >= date_from)
    if date_to:
        query = query.filter(Sale.date <= date_to)

    sales = query.order_by(Sale.date.desc(), Sale.id.desc()).all()

    totals: dict[str, dict[str, float]] = {}
    for s in sales:
        cur = s.currency or "UZS"
        if cur not in totals:
            totals[cur] = {"sell": 0.0, "cost": 0.0, "profit": 0.0}
        totals[cur]["sell"] += float(s.total_sell or 0)
        totals[cur]["cost"] += float(s.total_cost or 0)
        totals[cur]["profit"] += float(s.profit or 0)

    return render_template(
        "sales/list.html",
        sales=sales,
        q=q,
        date_from=date_from_str,
        date_to=date_to_str,
        period=period,
        totals=totals,
    )


@sales_bp.route("/shop/sell", methods=["GET", "POST"])
@login_required
def shop_sell():
    if not _user_can_access_sales():
        flash("У вас нет доступа к этому разделу.", "danger")
        return redirect(url_for("main.dashboard"))

    shop = _get_shop_for_sales()
    if not shop:
        flash("Магазин для продажи не найден.", "danger")
        return redirect(url_for("main.dashboard"))

    factory_id = getattr(current_user, "factory_id", None)

    stock_query = (
        ShopStock.query
        .join(Product, Product.id == ShopStock.product_id)
        .filter(
            ShopStock.shop_id == shop.id,
            ShopStock.quantity > 0,
        )
    )

    if not _role_flag("is_shop") and factory_id:
        stock_query = stock_query.filter(ShopStock.source_factory_id == factory_id)

    shop_items = stock_query.order_by(Product.name.asc(), ShopStock.id.asc()).all()
    products = [row.product for row in shop_items]

    if request.method == "POST":
        try:
            shop_stock_id = int(request.form.get("shop_stock_id") or 0)
        except (TypeError, ValueError):
            shop_stock_id = 0

        try:
            qty = int(request.form.get("quantity") or 0)
        except (TypeError, ValueError):
            qty = 0

        customer_name = (request.form.get("customer_name") or "").strip() or None
        customer_phone = (request.form.get("customer_phone") or "").strip() or None
        note = (request.form.get("note") or "").strip() or None
        allow_partial = bool(request.form.get("allow_partial"))

        if qty <= 0:
            flash("Количество должно быть больше нуля.", "warning")
            return redirect(url_for("sales.shop_sell"))

        chosen_stock_query = (
            ShopStock.query
            .join(Product, Product.id == ShopStock.product_id)
            .filter(
                ShopStock.id == shop_stock_id,
                ShopStock.shop_id == shop.id,
                ShopStock.quantity >= 0,
            )
        )

        if not _role_flag("is_shop") and factory_id:
            chosen_stock_query = chosen_stock_query.filter(
                ShopStock.source_factory_id == factory_id
            )

        stock = chosen_stock_query.first()

        if not stock:
            flash("Товар в остатках магазина не найден.", "danger")
            return redirect(url_for("sales.shop_sell"))

        product = stock.product
        if not product:
            flash("Товар не найден.", "danger")
            return redirect(url_for("sales.shop_sell"))

        try:
            result = shop_service.sell_from_shop_or_create_order(
                factory_id=stock.source_factory_id or product.factory_id,
                product_id=product.id,
                requested_qty=qty,
                customer_name=customer_name,
                customer_phone=customer_phone,
                note=note,
                allow_partial_sale=allow_partial,
                created_by=current_user,
                shop_stock_id=stock.id,
            )
        except ValueError as e:
            flash(str(e), "danger")
            return redirect(url_for("sales.shop_sell"))

        sale = result["sale"]
        order = result["order"]
        missing = result["missing"]
        sold_now = result["sold_now"]

        if sale:
            qty_sold = sale.quantity or 0
            currency = getattr(sale, "currency", None) or getattr(product, "currency", "UZS")

            if getattr(sale, "total_sell", None) is not None:
                total_sell = sale.total_sell
            else:
                price = getattr(sale, "sell_price_per_item", None)
                if price is None:
                    price = getattr(product, "sell_price_per_item", 0) or 0
                total_sell = qty_sold * price

            try:
                msg = (
                    "💸 <b>Новая продажа (магазин)</b>\n"
                    f"Модель: <b>{product.name}</b>\n"
                    f"Категория: {product.category or '-'}\n"
                    f"Кол-во: <b>{qty_sold}</b> шт.\n"
                    f"Сумма: <b>{total_sell:.2f} {currency}</b>\n"
                    f"Клиент: {customer_name or '-'}\n"
                    f"Магазин: <b>{shop.name}</b>"
                )
                send_telegram_message(
                    msg,
                    factory_id=stock.source_factory_id or product.factory_id,
                    include_manager_chats=False,
                )
            except Exception:
                pass

        if order:
            try:
                msg = (
                    "🧾 <b>Новый заказ из магазина</b>\n"
                    f"Модель: <b>{product.name}</b>\n"
                    f"Нужно произвести: <b>{missing}</b> шт.\n"
                    f"Номер заказа: <b>{order.id}</b>\n"
                    f"Магазин: <b>{shop.name}</b>"
                )
                send_telegram_message(
                    msg,
                    factory_id=stock.source_factory_id or product.factory_id,
                    include_manager_chats=False,
                )
            except Exception:
                pass

        if sold_now > 0 and missing == 0:
            flash(f"Продано {sold_now} шт. из магазина (хватило остатка).", "success")
        elif sold_now > 0 and missing > 0:
            flash(
                f"Продано сейчас {sold_now} шт. из магазина. "
                f"Создан заказ на оставшиеся {missing} шт.",
                "info",
            )
        elif sold_now == 0 and missing > 0:
            flash(
                "В магазине нет достаточного количества. "
                f"Создан заказ на {missing} шт.",
                "info",
            )
        else:
            flash("Операция завершена.", "info")

        return redirect(url_for("sales.shop_sales_log"))

    return render_template(
        "sales/shop_sell.html",
        products=products,
        shop_items=shop_items,
    )


@sales_bp.route("/wholesale/create", methods=["GET", "POST"])
@login_required
def wholesale_create():
    if not _user_can_access_sales():
        flash("У вас нет доступа к этому разделу.", "danger")
        return redirect(url_for("main.dashboard"))

    shop = _get_shop_for_sales()
    if not shop:
        flash("Магазин для продажи не найден.", "danger")
        return redirect(url_for("main.dashboard"))

    try:
        factory_id = int(request.values.get("factory_id") or 0)
    except (TypeError, ValueError):
        factory_id = 0

    available_factories = _get_available_wholesale_factories(shop)
    available_factory_ids = {row["factory_id"] for row in available_factories}

    if factory_id and factory_id not in available_factory_ids:
        flash("Эта фабрика недоступна для Big Sale.", "danger")
        return redirect(url_for("sales.wholesale_create"))

    search_rows = (
        ShopStock.query.join(Product, Product.id == ShopStock.product_id)
        .filter(
            ShopStock.shop_id == shop.id,
            ShopStock.quantity > 0,
        )
        .order_by(
            ShopStock.source_factory_id.asc(),
            Product.name.asc(),
            ShopStock.id.asc(),
        )
        .all()
    )

    stock_rows = []
    if factory_id:
        stock_rows = [
            row for row in search_rows
            if (row.source_factory_id or 0) == factory_id
        ]

    if request.method == "POST":
        customer_name = (request.form.get("customer_name") or "").strip() or None
        customer_phone = (request.form.get("customer_phone") or "").strip() or None
        note = (request.form.get("note") or "").strip() or None
        payment_method = (request.form.get("payment_method") or "").strip() or None
        payment_status = (request.form.get("payment_status") or "paid").strip() or "paid"

        try:
            discount_amount = float(request.form.get("discount_amount") or 0)
        except (TypeError, ValueError):
            discount_amount = 0.0

        posted_stock_ids = request.form.getlist("shop_stock_id")
        posted_quantities = request.form.getlist("quantity")
        posted_unit_prices = request.form.getlist("unit_price")
        posted_source_factory_ids = request.form.getlist("source_factory_id")

        if not posted_stock_ids:
            flash("Добавьте хотя бы один товар.", "warning")
            return redirect(url_for("sales.wholesale_create", factory_id=factory_id or None))

        raw_lines = []
        for i in range(len(posted_stock_ids)):
            try:
                shop_stock_id = int(posted_stock_ids[i] or 0)
                quantity = int(posted_quantities[i] or 0)
                unit_price = float(posted_unit_prices[i] or 0)
            except (TypeError, ValueError):
                flash("Ошибка в строках продажи. Проверьте количество и цену.", "danger")
                return redirect(url_for("sales.wholesale_create", factory_id=factory_id or None))

            try:
                source_factory_id = int(posted_source_factory_ids[i] or 0) if i < len(posted_source_factory_ids) else 0
            except (TypeError, ValueError):
                source_factory_id = 0

            if shop_stock_id <= 0:
                continue
            if quantity <= 0:
                continue
            if unit_price < 0:
                flash("Цена не может быть отрицательной.", "danger")
                return redirect(url_for("sales.wholesale_create", factory_id=factory_id or None))

            raw_lines.append(
                {
                    "shop_stock_id": shop_stock_id,
                    "quantity": quantity,
                    "unit_price": unit_price,
                    "source_factory_id": source_factory_id or None,
                }
            )

        if not raw_lines:
            flash("Добавьте хотя бы одну корректную строку продажи.", "warning")
            return redirect(url_for("sales.wholesale_create", factory_id=factory_id or None))

        merged = {}
        for line in raw_lines:
            key = line["shop_stock_id"]
            if key not in merged:
                merged[key] = {
                    "shop_stock_id": key,
                    "quantity": 0,
                    "unit_price": line["unit_price"],
                    "source_factory_id": line["source_factory_id"],
                }
            merged[key]["quantity"] += line["quantity"]
            merged[key]["unit_price"] = line["unit_price"]
            if line["source_factory_id"]:
                merged[key]["source_factory_id"] = line["source_factory_id"]

        merged_lines = list(merged.values())
        stock_ids = [line["shop_stock_id"] for line in merged_lines]

        stock_list = (
            ShopStock.query.join(Product, Product.id == ShopStock.product_id)
            .filter(
                ShopStock.id.in_(stock_ids),
                ShopStock.shop_id == shop.id,
            )
            .all()
        )
        stock_map = {row.id: row for row in stock_list}

        if len(stock_map) != len(stock_ids):
            flash("Некоторые товары не найдены или недоступны в этом магазине.", "danger")
            return redirect(url_for("sales.wholesale_create", factory_id=factory_id or None))

        wholesale_sale = WholesaleSale(
            factory_id=None,
            shop_id=shop.id,
            created_by_id=current_user.id,
            customer_name=customer_name,
            customer_phone=customer_phone,
            note=note,
            discount_amount=discount_amount,
            currency="UZS",
            payment_method=payment_method,
            payment_status=payment_status,
        )
        db.session.add(wholesale_sale)
        db.session.flush()

        try:
            used_factory_ids = set()

            for line in merged_lines:
                stock = stock_map[line["shop_stock_id"]]
                product = stock.product

                if not product:
                    raise ValueError("Один из товаров не найден.")

                requested_qty = int(line["quantity"] or 0)
                available_qty = int(stock.quantity or 0)

                if requested_qty <= 0:
                    raise ValueError(f"Количество должно быть больше нуля для {product.name}.")
                if requested_qty > available_qty:
                    raise ValueError(
                        f"Недостаточно остатка для {product.name}. "
                        f"Доступно: {available_qty}, запрошено: {requested_qty}."
                    )

                source_factory_id = stock.source_factory_id or line.get("source_factory_id") or product.factory_id
                unit_price = float(line["unit_price"] or 0)
                line_total = requested_qty * unit_price

                item = WholesaleSaleItem(
                    wholesale_sale_id=wholesale_sale.id,
                    product_id=product.id,
                    shop_stock_id=stock.id,
                    source_factory_id=source_factory_id,
                    quantity=requested_qty,
                    unit_price=unit_price,
                    cost_price_per_item=float(product.cost_price_per_item or 0),
                    line_total=line_total,
                    product_name_snapshot=product.name,
                    currency=product.currency or "UZS",
                )
                db.session.add(item)

                stock.quantity = available_qty - requested_qty
                used_factory_ids.add(source_factory_id)

                movement = Movement(
                    factory_id=source_factory_id,
                    product_id=product.id,
                    source="shop",
                    destination="customer",
                    change=-requested_qty,
                    note=f"Wholesale sale #{wholesale_sale.id}",
                    created_by_id=current_user.id,
                )
                db.session.add(movement)

            db.session.flush()
            wholesale_sale.recalc_totals()
            db.session.commit()

        except ValueError as e:
            db.session.rollback()
            flash(str(e), "danger")
            return redirect(url_for("sales.wholesale_create", factory_id=factory_id or None))
        except Exception as e:
            db.session.rollback()
            flash(f"Ошибка при сохранении Big Sale: {e}", "danger")
            return redirect(url_for("sales.wholesale_create", factory_id=factory_id or None))

        try:
            distinct_factories = len({
                item.source_factory_id
                for item in wholesale_sale.items
                if item.source_factory_id
            })
            msg = (
                "📦 <b>Новая Big Sale продажа</b>\n"
                f"Фабрик: <b>{distinct_factories}</b>\n"
                f"SKU: <b>{wholesale_sale.total_skus}</b>\n"
                f"Кол-во: <b>{wholesale_sale.total_qty}</b> шт.\n"
                f"Сумма: <b>{wholesale_sale.total_amount:.2f} {wholesale_sale.currency}</b>\n"
                f"Клиент: {customer_name or '-'}\n"
                f"Магазин: <b>{shop.name}</b>"
            )
            send_telegram_message(
                msg,
                factory_ids=sorted(fid for fid in used_factory_ids if fid),
                include_manager_chats=False,
            )
        except Exception:
            pass

        flash(
            f"Big Sale сохранена: {wholesale_sale.total_skus} моделей, "
            f"{wholesale_sale.total_qty} шт., {wholesale_sale.total_amount:.2f} {wholesale_sale.currency}.",
            "success",
        )

        redirect_factory_id = factory_id or (next(iter(used_factory_ids)) if used_factory_ids else None)
        return redirect(
            url_for(
                "sales.wholesale_create",
                factory_id=redirect_factory_id,
                saved=1,
            )
        )

    return render_template(
        "sales/wholesale_create.html",
        shop=shop,
        factory_id=factory_id,
        available_factories=available_factories,
        stock_rows=stock_rows,
        search_rows=search_rows,
    )

@sales_bp.route("/shop/sales", methods=["GET"])
@login_required
def shop_sales_overview():
    if not _user_can_access_sales():
        flash("У вас нет доступа к этому разделу.", "danger")
        return redirect(url_for("main.dashboard"))

    shop = _get_shop_for_sales()
    if not shop:
        flash("Магазин для продажи не найден.", "danger")
        return redirect(url_for("main.dashboard"))

    today = date.today()
    yesterday = today - timedelta(days=1)
    week_start = today - timedelta(days=today.weekday())

    q = (request.args.get("q") or "").strip()
    date_from_str = (request.args.get("from") or "").strip()
    date_to_str = (request.args.get("to") or "").strip()

    date_from = None
    date_to = None
    date_fmt = "%Y-%m-%d"

    if date_from_str:
        try:
            date_from = datetime.strptime(date_from_str, date_fmt).date()
        except ValueError:
            date_from = None

    if date_to_str:
        try:
            date_to = datetime.strptime(date_to_str, date_fmt).date()
        except ValueError:
            date_to = None

    grouped = {}
    snapshot_map = _build_realizatsiya_snapshot(shop)
    settlement_map, total_settled, settlement_currency = _build_settlement_map(shop)

    settlement_query = RealizatsiyaSettlement.query.filter(
        RealizatsiyaSettlement.shop_id == shop.id
    )

    if not _role_flag("is_shop") and getattr(current_user, "factory_id", None):
        settlement_query = settlement_query.filter(
            RealizatsiyaSettlement.factory_id == current_user.factory_id
        )

    settlement_rows_raw = settlement_query.order_by(
        RealizatsiyaSettlement.settlement_date.desc(),
        RealizatsiyaSettlement.id.desc(),
    ).all()

    settlement_rows = []
    for row in settlement_rows_raw:
        settlement_rows.append(
            {
                "id": row.id,
                "factory_id": row.factory_id,
                "factory_name": getattr(row.factory, "name", None) or f"Factory #{row.factory_id}",
                "amount": round(float(row.amount or 0), 2),
                "currency": row.currency or "UZS",
                "settlement_date": row.settlement_date.strftime("%Y-%m-%d") if row.settlement_date else "-",
                "note": row.note or "",
                "created_by_name": getattr(row.created_by, "username", None) or "",
            }
        )

    summary = {
        "total_sales_amount": 0.0,
        "total_qty": 0,
        "total_skus": 0,
        "total_profit": 0.0,
        "today_sales_amount": 0.0,
        "today_qty": 0,
        "today_profit": 0.0,
        "yesterday_sales_amount": 0.0,
        "yesterday_qty": 0,
        "yesterday_profit": 0.0,
        "week_sales_amount": 0.0,
        "week_qty": 0,
        "week_profit": 0.0,
        "currency": "UZS",
    }

    realizatsiya_summary = {
        "sent_amount": 0.0,
        "collected_amount": total_settled,
        "remaining_amount": 0.0,
        "currency": settlement_currency or "UZS",
    }

    def ensure_factory_group(factory_id: int, factory_name: str, currency: str = "UZS"):
        if factory_id not in grouped:
            snapshot = snapshot_map.get(factory_id, {})
            settlement = settlement_map.get(factory_id, {})
            grouped[factory_id] = {
                "factory_id": factory_id,
                "factory_name": factory_name,
                "total_qty": 0,
                "total_sales_amount": 0.0,
                "total_profit": 0.0,
                "total_skus": 0,
                "today_sales_amount": 0.0,
                "yesterday_sales_amount": 0.0,
                "week_sales_amount": 0.0,
                "currency": currency or "UZS",
                "realizatsiya_due_amount": 0.0,
                "settled_amount": float(settlement.get("settled_amount", 0.0) or 0.0),
                "remaining_amount": 0.0,
                "qty_in_shop": int(snapshot.get("qty_in_shop", 0) or 0),
                "value_in_shop": float(snapshot.get("value_in_shop", 0.0) or 0.0),
            }
        return grouped[factory_id]

    wholesale_query = _build_wholesale_scope_query(
        shop=shop,
        q=q,
        date_from=date_from,
        date_to=date_to,
    )

    wholesale_sales = wholesale_query.distinct().order_by(
        WholesaleSale.created_at.desc(),
        WholesaleSale.id.desc(),
    ).all()

    for wholesale in wholesale_sales:
        sale_day = wholesale.created_at.date() if wholesale.created_at else None

        for item in wholesale.items:
            if not _role_flag("is_shop") and getattr(current_user, "factory_id", None):
                if item.source_factory_id != current_user.factory_id:
                    continue

            product = item.product
            factory_id = item.source_factory_id or getattr(product, "factory_id", 0) or 0
            factory_name = (
                getattr(item.source_factory, "name", None)
                or getattr(getattr(product, "factory", None), "name", None)
                or f"Factory #{factory_id}"
            )

            qty = int(item.quantity or 0)
            unit_price = float(item.unit_price or 0)
            cost_price = float(item.cost_price_per_item or 0)

            revenue = float(item.line_total or (qty * unit_price))
            due_to_factory = float(qty * cost_price)
            profit = float(revenue - due_to_factory)
            currency = item.currency or wholesale.currency or "UZS"

            group = ensure_factory_group(factory_id, factory_name, currency)
            group["total_qty"] += qty
            group["total_sales_amount"] += revenue
            group["total_profit"] += profit
            group["total_skus"] += 1
            group["realizatsiya_due_amount"] += due_to_factory

            if sale_day == today:
                group["today_sales_amount"] += revenue
                summary["today_sales_amount"] += revenue
                summary["today_qty"] += qty
                summary["today_profit"] += profit

            if sale_day == yesterday:
                group["yesterday_sales_amount"] += revenue
                summary["yesterday_sales_amount"] += revenue
                summary["yesterday_qty"] += qty
                summary["yesterday_profit"] += profit

            if sale_day and sale_day >= week_start:
                group["week_sales_amount"] += revenue
                summary["week_sales_amount"] += revenue
                summary["week_qty"] += qty
                summary["week_profit"] += profit

            summary["total_sales_amount"] += revenue
            summary["total_qty"] += qty
            summary["total_skus"] += 1
            summary["total_profit"] += profit
            summary["currency"] = currency

            realizatsiya_summary["sent_amount"] += due_to_factory
            realizatsiya_summary["currency"] = currency

    for factory_id, snap in snapshot_map.items():
        ensure_factory_group(
            factory_id=factory_id,
            factory_name=snap["factory_name"],
            currency=snap.get("currency", "UZS"),
        )

    for factory_id, sett in settlement_map.items():
        ensure_factory_group(
            factory_id=factory_id,
            factory_name=sett["factory_name"],
            currency=sett.get("currency", "UZS"),
        )

    for group in grouped.values():
        group["remaining_amount"] = round(
            float(group["realizatsiya_due_amount"] or 0.0) - float(group["settled_amount"] or 0.0),
            2,
        )

    realizatsiya_summary["remaining_amount"] = round(
        float(realizatsiya_summary["sent_amount"] or 0.0) - float(realizatsiya_summary["collected_amount"] or 0.0),
        2,
    )

    factory_groups = sorted(
        grouped.values(),
        key=lambda x: x["total_sales_amount"],
        reverse=True,
    )

    return render_template(
        "sales/shop_sales_overview.html",
        summary={
            "total_sales_amount": round(summary["total_sales_amount"], 2),
            "total_qty": summary["total_qty"],
            "total_skus": summary["total_skus"],
            "total_profit": round(summary["total_profit"], 2),
            "today_sales_amount": round(summary["today_sales_amount"], 2),
            "today_qty": summary["today_qty"],
            "today_profit": round(summary["today_profit"], 2),
            "yesterday_sales_amount": round(summary["yesterday_sales_amount"], 2),
            "yesterday_qty": summary["yesterday_qty"],
            "yesterday_profit": round(summary["yesterday_profit"], 2),
            "week_sales_amount": round(summary["week_sales_amount"], 2),
            "week_qty": summary["week_qty"],
            "week_profit": round(summary["week_profit"], 2),
            "currency": summary["currency"],
        },
        factory_groups=[
            {
                "factory_id": g["factory_id"],
                "factory_name": g["factory_name"],
                "total_qty": g["total_qty"],
                "total_sales_amount": round(g["total_sales_amount"], 2),
                "total_profit": round(g["total_profit"], 2),
                "total_skus": g["total_skus"],
                "today_sales_amount": round(g["today_sales_amount"], 2),
                "yesterday_sales_amount": round(g["yesterday_sales_amount"], 2),
                "week_sales_amount": round(g["week_sales_amount"], 2),
                "realizatsiya_due_amount": round(g["realizatsiya_due_amount"], 2),
                "settled_amount": round(g["settled_amount"], 2),
                "remaining_amount": round(g["remaining_amount"], 2),
                "qty_in_shop": g["qty_in_shop"],
                "value_in_shop": round(g["value_in_shop"], 2),
                "currency": g["currency"],
            }
            for g in factory_groups
        ],
        realizatsiya={
            "sent_amount": round(realizatsiya_summary["sent_amount"], 2),
            "collected_amount": round(realizatsiya_summary["collected_amount"], 2),
            "remaining_amount": round(realizatsiya_summary["remaining_amount"], 2),
            "currency": realizatsiya_summary["currency"],
        },
        settlement_rows=settlement_rows,
    )


@sales_bp.route("/shop/sales-log", methods=["GET"])
@login_required
def shop_sales_log():
    if not _user_can_access_sales():
        flash("У вас нет доступа к этому разделу.", "danger")
        return redirect(url_for("main.dashboard"))

    shop = _get_shop_for_sales()
    if not shop:
        flash("Магазин для продажи не найден.", "danger")
        return redirect(url_for("main.dashboard"))

    today = date.today()
    period = (request.args.get("period") or "today").strip().lower()
    q = (request.args.get("q") or "").strip()
    date_from_str = (request.args.get("from") or "").strip()
    date_to_str = (request.args.get("to") or "").strip()

    date_from = None
    date_to = None
    date_fmt = "%Y-%m-%d"

    if date_from_str:
        try:
            date_from = datetime.strptime(date_from_str, date_fmt).date()
        except ValueError:
            date_from = None

    if date_to_str:
        try:
            date_to = datetime.strptime(date_to_str, date_fmt).date()
        except ValueError:
            date_to = None

    if not date_from and not date_to:
        if period == "today":
            date_from = today
            date_to = today
        elif period == "yesterday":
            date_from = today - timedelta(days=1)
            date_to = today - timedelta(days=1)
        elif period == "week":
            date_from = today - timedelta(days=today.weekday())
            date_to = today
        elif period == "month":
            date_from = today.replace(day=1)
            date_to = today
        elif period == "all":
            date_from = None
            date_to = None
        else:
            period = "today"
            date_from = today
            date_to = today

    log_rows = []
    total_sales_amount = 0.0
    total_qty = 0
    total_profit = 0.0
    total_due_to_factory = 0.0
    currency = "UZS"

    # Regular sales
    regular_query = _build_regular_sales_query(
        shop=shop,
        q=q,
        date_from=date_from,
        date_to=date_to,
    )
    regular_sales = regular_query.order_by(Sale.date.desc(), Sale.id.desc()).all()

    for sale in regular_sales:
        product = sale.product
        if not product:
            continue

        qty = int(sale.quantity or 0)
        revenue = float(sale.total_sell or 0.0)
        due_to_factory = float(sale.total_cost or 0.0)
        profit = float(sale.profit or 0.0)
        currency = sale.currency or product.currency or "UZS"

        factory_name = (
            getattr(getattr(product, "factory", None), "name", None)
            or f"Factory #{getattr(product, 'factory_id', 0) or 0}"
        )

        sale_dt = datetime.combine(
            sale.date,
            datetime.min.time(),
        ) if sale.date else datetime.min

        log_rows.append(
            {
                "id": sale.id,
                "sale_type": "regular",
                "product_name": product.name or "-",
                "category_name": product.category or "",
                "factory_name": factory_name,
                "customer_name": sale.customer_name,
                "customer_phone": sale.customer_phone,
                "qty": qty,
                "sell_price": round(float(sale.sell_price_per_item or 0), 2),
                "sales_total": round(revenue, 2),
                "profit": round(profit, 2),
                "due_to_factory": round(due_to_factory, 2),
                "currency": currency,
                "date": sale.date.strftime("%Y-%m-%d") if sale.date else "-",
                "time_label": sale.date.strftime("%Y-%m-%d") if sale.date else "-",
                "sort_dt": sale_dt,
            }
        )

        total_sales_amount += revenue
        total_qty += qty
        total_profit += profit
        total_due_to_factory += due_to_factory

    # Wholesale sales
    wholesale_query = _build_wholesale_scope_query(
        shop=shop,
        q=q,
        date_from=date_from,
        date_to=date_to,
    )

    wholesale_sales = wholesale_query.distinct().order_by(
        WholesaleSale.created_at.desc(),
        WholesaleSale.id.desc(),
    ).all()

    for wholesale in wholesale_sales:
        for item in wholesale.items:
            if not _role_flag("is_shop") and getattr(current_user, "factory_id", None):
                if item.source_factory_id != current_user.factory_id:
                    continue

            product = item.product
            qty = int(item.quantity or 0)
            unit_price = float(item.unit_price or 0)
            cost_price = float(item.cost_price_per_item or 0)

            revenue = float(item.line_total or (qty * unit_price))
            due_to_factory = float(qty * cost_price)
            profit = float(revenue - due_to_factory)
            currency = item.currency or wholesale.currency or "UZS"

            factory_name = (
                getattr(item.source_factory, "name", None)
                or getattr(getattr(product, "factory", None), "name", None)
                or f"Factory #{item.source_factory_id or getattr(product, 'factory_id', 0) or 0}"
            )

            created_at = wholesale.created_at or datetime.min

            log_rows.append(
                {
                    "id": wholesale.id,
                    "sale_type": "wholesale",
                    "product_name": item.product_name_snapshot or (product.name if product else "-"),
                    "category_name": product.category if product else "",
                    "factory_name": factory_name,
                    "customer_name": wholesale.customer_name,
                    "customer_phone": wholesale.customer_phone,
                    "qty": qty,
                    "sell_price": round(unit_price, 2),
                    "sales_total": round(revenue, 2),
                    "profit": round(profit, 2),
                    "due_to_factory": round(due_to_factory, 2),
                    "currency": currency,
                    "date": created_at.strftime("%Y-%m-%d") if wholesale.created_at else "-",
                    "time_label": created_at.strftime("%Y-%m-%d %H:%M") if wholesale.created_at else "-",
                    "sort_dt": created_at,
                }
            )

            total_sales_amount += revenue
            total_qty += qty
            total_profit += profit
            total_due_to_factory += due_to_factory

    log_rows.sort(key=lambda x: (x["sort_dt"], x["id"]), reverse=True)

    for row in log_rows:
        row.pop("sort_dt", None)

    return render_template(
        "sales/shop_sales_log.html",
        log_rows=log_rows,
        log_summary={
            "total_rows": len(log_rows),
            "total_sales_amount": round(total_sales_amount, 2),
            "total_qty": total_qty,
            "total_profit": round(total_profit, 2),
            "total_due_to_factory": round(total_due_to_factory, 2),
            "currency": currency,
        },
        period=period,
        q=q,
        date_from=date_from_str,
        date_to=date_to_str,
    )
@sales_bp.route("/shop/sales/factory/<int:factory_id>")
@login_required
def shop_sales_factory_detail(factory_id):
    current_factory_id = getattr(current_user, "factory_id", None)
    if not current_factory_id:
        flash("Factory is not selected.", "warning")
        return redirect(url_for("sales.shop_sales_overview"))

    summary, factory_groups, realizatsiya, settlement_rows = build_shop_sales_overview_data(
        current_factory_id=current_factory_id
    )

    group = next((x for x in factory_groups if x.get("factory_id") == factory_id), None)
    if not group:
        flash("Factory sales detail was not found.", "warning")
        return redirect(url_for("sales.shop_sales_overview"))

    factory_settlement_rows = [
        row for row in settlement_rows
        if row.get("factory_id") == factory_id
    ]

    return render_template(
        "sales/shop_sales_factory_detail.html",
        group=group,
        settlement_rows=factory_settlement_rows,
    )
def build_shop_sales_overview_data(current_factory_id, q="", date_from=None, date_to=None):
    if not current_factory_id:
        return ({}, [], {}, [])

    shop = _get_shop_for_sales()
    if not shop:
        return ({}, [], {}, [])

    today = date.today()
    yesterday = today - timedelta(days=1)
    week_start = today - timedelta(days=today.weekday())

    grouped = {}
    snapshot_map = _build_realizatsiya_snapshot(shop)
    settlement_map, total_settled, settlement_currency = _build_settlement_map(
        shop, date_from=date_from, date_to=date_to
    )

    settlement_query = RealizatsiyaSettlement.query.filter(
        RealizatsiyaSettlement.shop_id == shop.id
    )
    if not _role_flag("is_shop") and current_factory_id:
        settlement_query = settlement_query.filter(
            RealizatsiyaSettlement.factory_id == current_factory_id
        )

    settlement_rows_raw = settlement_query.order_by(
        RealizatsiyaSettlement.settlement_date.desc(),
        RealizatsiyaSettlement.id.desc(),
    ).all()

    settlement_rows = [
        {
            "id": row.id,
            "factory_id": row.factory_id,
            "factory_name": getattr(row.factory, "name", None) or f"Factory #{row.factory_id}",
            "amount": round(float(row.amount or 0), 2),
            "currency": row.currency or "UZS",
            "settlement_date": row.settlement_date.strftime("%Y-%m-%d") if row.settlement_date else "-",
            "note": row.note or "",
            "created_by_name": getattr(row.created_by, "username", None) or "",
        }
        for row in settlement_rows_raw
    ]

    summary = {
        "total_sales_amount": 0.0,
        "total_qty": 0,
        "total_skus": 0,
        "total_profit": 0.0,
        "today_sales_amount": 0.0,
        "today_qty": 0,
        "today_profit": 0.0,
        "yesterday_sales_amount": 0.0,
        "yesterday_qty": 0,
        "yesterday_profit": 0.0,
        "week_sales_amount": 0.0,
        "week_qty": 0,
        "week_profit": 0.0,
        "currency": "UZS",
    }

    realizatsiya_summary = {
        "sent_amount": 0.0,
        "collected_amount": total_settled,
        "remaining_amount": 0.0,
        "currency": settlement_currency or "UZS",
    }

    def ensure_factory_group(factory_id: int, factory_name: str, currency: str = "UZS"):
        if factory_id not in grouped:
            snapshot = snapshot_map.get(factory_id, {})
            settlement = settlement_map.get(factory_id, {})
            grouped[factory_id] = {
                "factory_id": factory_id,
                "factory_name": factory_name,
                "total_qty": 0,
                "total_sales_amount": 0.0,
                "total_profit": 0.0,
                "total_skus": 0,
                "today_sales_amount": 0.0,
                "yesterday_sales_amount": 0.0,
                "week_sales_amount": 0.0,
                "currency": currency or "UZS",
                "realizatsiya_due_amount": 0.0,
                "settled_amount": float(settlement.get("settled_amount", 0.0) or 0.0),
                "remaining_amount": 0.0,
                "qty_in_shop": int(snapshot.get("qty_in_shop", 0) or 0),
                "value_in_shop": float(snapshot.get("value_in_shop", 0.0) or 0.0),
            }
        return grouped[factory_id]

    wholesale_query = _build_wholesale_scope_query(
        shop=shop,
        q=q,
        date_from=date_from,
        date_to=date_to,
    )

    wholesale_sales = wholesale_query.distinct().order_by(
        WholesaleSale.created_at.desc(),
        WholesaleSale.id.desc(),
    ).all()

    for wholesale in wholesale_sales:
        sale_day = wholesale.created_at.date() if wholesale.created_at else None
        for item in wholesale.items:
            if not _role_flag("is_shop") and current_factory_id:
                if item.source_factory_id != current_factory_id:
                    continue

            product = item.product
            factory_id = item.source_factory_id or getattr(product, "factory_id", 0) or 0
            factory_name = (
                getattr(item.source_factory, "name", None)
                or getattr(getattr(product, "factory", None), "name", None)
                or f"Factory #{factory_id}"
            )

            qty = int(item.quantity or 0)
            unit_price = float(item.unit_price or 0)
            cost_price = float(item.cost_price_per_item or 0)

            revenue = float(item.line_total or (qty * unit_price))
            profit = float(revenue - (qty * cost_price))
            currency = item.currency or wholesale.currency or "UZS"

            group = ensure_factory_group(factory_id, factory_name, currency)
            group["total_qty"] += qty
            group["total_sales_amount"] += revenue
            group["total_profit"] += profit
            group["total_skus"] += 1
            group["realizatsiya_due_amount"] += float(qty * cost_price)

            if sale_day == today:
                group["today_sales_amount"] += revenue
                summary["today_sales_amount"] += revenue
                summary["today_qty"] += qty
                summary["today_profit"] += profit

            if sale_day == yesterday:
                group["yesterday_sales_amount"] += revenue
                summary["yesterday_sales_amount"] += revenue
                summary["yesterday_qty"] += qty
                summary["yesterday_profit"] += profit

            if sale_day and sale_day >= week_start:
                group["week_sales_amount"] += revenue
                summary["week_sales_amount"] += revenue
                summary["week_qty"] += qty
                summary["week_profit"] += profit

            summary["total_sales_amount"] += revenue
            summary["total_qty"] += qty
            summary["total_skus"] += 1
            summary["total_profit"] += profit
            summary["currency"] = currency

            realizatsiya_summary["sent_amount"] += float(qty * cost_price)
            realizatsiya_summary["currency"] = currency

    for factory_id, snap in snapshot_map.items():
        ensure_factory_group(
            factory_id=factory_id,
            factory_name=snap["factory_name"],
            currency=snap.get("currency", "UZS"),
        )
    for factory_id, sett in settlement_map.items():
        ensure_factory_group(
            factory_id=factory_id,
            factory_name=sett["factory_name"],
            currency=sett.get("currency", "UZS"),
        )

    for g in grouped.values():
        g["remaining_amount"] = round(
            float(g["realizatsiya_due_amount"] or 0.0)
            - float(g["settled_amount"] or 0.0),
            2,
        )

    realizatsiya_summary["remaining_amount"] = round(
        float(realizatsiya_summary["sent_amount"] or 0.0)
        - float(realizatsiya_summary["collected_amount"] or 0.0),
        2,
    )

    factory_groups = sorted(
        grouped.values(), key=lambda x: x["total_sales_amount"], reverse=True
    )

    return (
        {
            "total_sales_amount": round(summary["total_sales_amount"], 2),
            "total_qty": summary["total_qty"],
            "total_skus": summary["total_skus"],
            "total_profit": round(summary["total_profit"], 2),
            "today_sales_amount": round(summary["today_sales_amount"], 2),
            "today_qty": summary["today_qty"],
            "today_profit": round(summary["today_profit"], 2),
            "yesterday_sales_amount": round(summary["yesterday_sales_amount"], 2),
            "yesterday_qty": summary["yesterday_qty"],
            "yesterday_profit": round(summary["yesterday_profit"], 2),
            "week_sales_amount": round(summary["week_sales_amount"], 2),
            "week_qty": summary["week_qty"],
            "week_profit": round(summary["week_profit"], 2),
            "currency": summary["currency"],
        },
        [
            {
                "factory_id": g["factory_id"],
                "factory_name": g["factory_name"],
                "total_qty": g["total_qty"],
                "total_sales_amount": round(g["total_sales_amount"], 2),
                "total_profit": round(g["total_profit"], 2),
                "total_skus": g["total_skus"],
                "today_sales_amount": round(g["today_sales_amount"], 2),
                "yesterday_sales_amount": round(g["yesterday_sales_amount"], 2),
                "week_sales_amount": round(g["week_sales_amount"], 2),
                "realizatsiya_due_amount": round(g["realizatsiya_due_amount"], 2),
                "settled_amount": round(g["settled_amount"], 2),
                "remaining_amount": round(g["remaining_amount"], 2),
                "qty_in_shop": g["qty_in_shop"],
                "value_in_shop": round(g["value_in_shop"], 2),
                "currency": g["currency"],
            }
            for g in factory_groups
        ],
        {
            "sent_amount": round(realizatsiya_summary["sent_amount"], 2),
            "collected_amount": round(realizatsiya_summary["collected_amount"], 2),
            "remaining_amount": round(realizatsiya_summary["remaining_amount"], 2),
            "currency": realizatsiya_summary["currency"],
        },
        settlement_rows,
    )
@sales_bp.route("/shop/realizatsiya", methods=["GET"])
@login_required
def shop_realizatsiya():
    current_factory_id = getattr(current_user, "factory_id", None)
    if not current_factory_id:
        flash("Factory is not selected.", "warning")
        return redirect(url_for("sales.shop_sales_overview"))

    summary, factory_groups, realizatsiya, settlement_rows = build_shop_sales_overview_data(
        current_factory_id=current_factory_id
    )

    return render_template(
        "sales/shop_realizatsiya.html",
        summary=summary,
        factory_groups=factory_groups,
        realizatsiya=realizatsiya,
        settlement_rows=settlement_rows,
    )
