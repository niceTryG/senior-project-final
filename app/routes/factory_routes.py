from __future__ import annotations
from app.telegram_notify import send_telegram_message
from datetime import date, datetime
from difflib import SequenceMatcher

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    jsonify,
)
from flask_login import login_required, current_user
from sqlalchemy import func, or_

from app.extensions import db
from app.models import Product, Production, Movement, ShopOrder, ShopOrderItem
from app.services.shop_service import ShopService


factory_bp = Blueprint("factory", __name__, url_prefix="/factory")
shop_service = ShopService()


# =========================
# "AI-ish" smart search helpers
# =========================

def _norm(s: str) -> str:
    return (s or "").strip().lower()


_CYR_TO_LAT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "j", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    "қ": "q", "ў": "o", "ғ": "g", "ҳ": "h",
}

_LAT_TO_CYR = {
    "a": "а", "b": "б", "v": "в", "g": "г", "d": "д", "e": "е",
    "j": "ж", "z": "з", "i": "и", "y": "й", "k": "к", "l": "л",
    "m": "м", "n": "н", "o": "о", "p": "п", "r": "р", "s": "с",
    "t": "т", "u": "у", "f": "ф", "h": "х", "q": "қ",
}


def _to_lat(s: str) -> str:
    s = _norm(s)
    out: list[str] = []
    for ch in s:
        out.append(_CYR_TO_LAT.get(ch, ch))
    return "".join(out)


def _to_cyr(s: str) -> str:
    s = _norm(s)
    s = (
        s.replace("sh", "ш")
         .replace("ch", "ч")
         .replace("yo", "ё")
         .replace("yu", "ю")
         .replace("ya", "я")
         .replace("ts", "ц")
    )

    out: list[str] = []
    for ch in s:
        out.append(_LAT_TO_CYR.get(ch, ch))
    return "".join(out)


def _q_variants(q: str) -> list[str]:
    q0 = _norm(q)
    if not q0:
        return []

    v = {q0}
    v.add(_to_lat(q0))
    v.add(_to_cyr(q0))
    v.add(q0.replace(" ", "").replace("-", ""))
    v.add(" ".join(q0.split()))

    return [x for x in v if x]


def _sim(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


# =========================
# Helpers
# =========================

def _get_categories_for_factory(factory_id: int) -> list[str]:
    rows = (
        db.session.query(Product.category)
        .filter(Product.factory_id == factory_id)
        .filter(Product.category.isnot(None))
        .filter(func.trim(Product.category) != "")
        .distinct()
        .order_by(Product.category.asc())
        .all()
    )
    return [r[0] for r in rows if r and r[0]]


def _build_today_map(factory_id: int):
    rows = (
        db.session.query(
            Production.product_id,
            func.coalesce(func.sum(Production.quantity), 0).label("qty"),
        )
        .join(Product, Product.id == Production.product_id)
        .filter(Product.factory_id == factory_id)
        .filter(Production.date == date.today())
        .group_by(Production.product_id)
        .all()
    )
    today_map = {pid: int(qty or 0) for (pid, qty) in rows}
    today_total = sum(today_map.values())
    return today_map, today_total


def _pending_order_rows_for_factory(factory_id: int, limit: int = 20):
    """
    Returns pending shop order items that belong to this factory's products.
    This is the missing bridge between shop -> factory production.
    """
    rows = (
        ShopOrderItem.query
        .join(Product, Product.id == ShopOrderItem.product_id)
        .join(ShopOrder, ShopOrder.id == ShopOrderItem.order_id)
        .filter(Product.factory_id == factory_id)
        .filter(ShopOrder.status == "pending")
        .filter(ShopOrderItem.qty_remaining > 0)
        .order_by(ShopOrder.created_at.asc(), ShopOrderItem.id.asc())
        .limit(limit)
        .all()
    )

    result = []
    for item in rows:
        result.append({
            "item_id": item.id,
            "order_id": item.order_id,
            "product_id": item.product_id,
            "product_name": item.product.name if item.product else f"#{item.product_id}",
            "category": item.product.category if item.product else "",
            "qty_requested": int(item.qty_requested or 0),
            "qty_from_shop_now": int(item.qty_from_shop_now or 0),
            "qty_remaining": int(item.qty_remaining or 0),
            "customer_name": item.order.customer_name if item.order else None,
            "created_at": item.order.created_at if item.order else None,
        })
    return result


# =========================
# Routes
# =========================

@factory_bp.route("/produce", methods=["GET"])
@login_required
def produce_today():
    factory_id = current_user.factory_id

    q = (request.args.get("q") or "").strip()
    selected_category = (request.args.get("category") or "").strip()

    preselect_product_id = request.args.get("product_id", type=int)
    preselect_order_id = request.args.get("order_id", type=int)
    preselect_qty = request.args.get("suggest_qty", type=int)

    query = Product.query.filter(Product.factory_id == factory_id)

    if selected_category:
        query = query.filter(Product.category == selected_category)

    if q:
        variants = _q_variants(q)
        like_filters = []
        for v in variants:
            if not v:
                continue
            like_filters.append(func.lower(Product.name).ilike(f"%{v}%"))
            like_filters.append(func.lower(func.coalesce(Product.category, "")).ilike(f"%{v}%"))
        if like_filters:
            query = query.filter(or_(*like_filters))

    products = query.order_by(Product.category.asc().nullslast(), Product.name.asc()).all()

    categories = _get_categories_for_factory(factory_id)
    today_map, today_total = _build_today_map(factory_id)
    pending_order_rows = _pending_order_rows_for_factory(factory_id=factory_id, limit=12)

    return render_template(
        "factory/produce_today.html",
        products=products,
        categories=categories,
        q=q,
        selected_category=selected_category,
        today_map=today_map,
        today_total=today_total,
        today=date.today().strftime("%d.%m.%Y"),
        pending_order_rows=pending_order_rows,
        preselect_product_id=preselect_product_id,
        preselect_order_id=preselect_order_id,
        preselect_qty=preselect_qty,
    )


@factory_bp.route("/orders/produce/<int:item_id>", methods=["GET"])
@login_required
def produce_for_order(item_id: int):
    """
    Open produce page with suggested product/qty for a pending shop order item.
    """
    factory_id = current_user.factory_id

    item = (
        ShopOrderItem.query
        .join(Product, Product.id == ShopOrderItem.product_id)
        .join(ShopOrder, ShopOrder.id == ShopOrderItem.order_id)
        .filter(ShopOrderItem.id == item_id)
        .filter(Product.factory_id == factory_id)
        .filter(ShopOrder.status == "pending")
        .first_or_404()
    )

    if int(item.qty_remaining or 0) <= 0:
        flash("Для этого заказа уже ничего не осталось производить.", "info")
        return redirect(url_for("factory.produce_today"))

    flash(
        f"Открыт режим производства для заказа #{item.order_id}: "
        f"{item.product.name} — нужно {item.qty_remaining} шт.",
        "info",
    )

    return redirect(url_for(
        "factory.produce_today",
        product_id=item.product_id,
        order_id=item.order_id,
        suggest_qty=int(item.qty_remaining or 0),
        q=item.product.name,
    ))


@factory_bp.route("/produce/save", methods=["POST"])
@login_required
def produce_today_save():
    """
    Save today's production counts from the form.
    Expected fields: qty_<product_id> = 5
    Saves only values > 0 as Production rows
    AND increases Product.quantity (factory stock).
    Then asks: Transfer to shop now?
    """
    factory_id = current_user.factory_id

    products = (
        Product.query
        .filter(Product.factory_id == factory_id)
        .all()
    )
    products_by_id = {p.id: p for p in products}
    allowed_ids = set(products_by_id.keys())

    created_rows = 0
    saved_map: dict[int, int] = {}
    produced_lines: list[str] = []

    for key, val in request.form.items():
        if not key.startswith("qty_"):
            continue

        try:
            product_id = int(key.replace("qty_", "").strip())
        except ValueError:
            continue

        if product_id not in allowed_ids:
            continue

        try:
            qty = int((val or "0").strip())
        except ValueError:
            qty = 0

        if qty <= 0:
            continue

        product = products_by_id.get(product_id)
        if not product:
            continue

        db.session.add(
            Production(
                product_id=product_id,
                date=date.today(),
                quantity=qty,
                note="manual count",
            )
        )

        product.quantity = int(product.quantity or 0) + qty

        db.session.add(
            Movement(
                factory_id=factory_id,
                product_id=product_id,
                source="production",
                destination="factory_stock",
                change=qty,
                note=f"Произведено и добавлено на склад фабрики: {qty} шт.",
                created_by_id=current_user.id,
                timestamp=datetime.utcnow(),
            )
        )

        created_rows += 1
        saved_map[product_id] = saved_map.get(product_id, 0) + qty
        produced_lines.append(f"• {product.name}: {qty} шт.")

    if created_rows <= 0:
        flash("⚠️ Ничего не сохранено (введите количество)", "warning")
        return redirect(url_for("factory.produce_today"))

    db.session.commit()

    session["mm_last_production_map"] = {str(k): int(v) for k, v in saved_map.items()}
    session["mm_last_production_date"] = date.today().isoformat()

    try:
        msg = (
            "🏭 <b>Производство сохранено</b>\n"
            f"Пользователь: <b>{current_user.username}</b>\n"
            f"Позиций: <b>{created_rows}</b>\n\n"
            + "\n".join(produced_lines[:10])
        )
        send_telegram_message(
            msg,
            factory_id=current_user.factory_id,
            include_manager_chats=False,
        )
    except Exception:
        pass

    flash(f"✅ Сохранено позиций: {created_rows}", "success")
    return redirect(url_for("factory.produce_transfer_confirm"))
@factory_bp.route("/produce/transfer-confirm", methods=["GET"])
@login_required
def produce_transfer_confirm():
    """
    Confirmation screen:
    'Production saved. Transfer these items to shop now?'
    """
    factory_id = current_user.factory_id

    prod_date = session.get("mm_last_production_date")
    mp = session.get("mm_last_production_map") or {}

    if not prod_date or prod_date != date.today().isoformat() or not mp:
        flash("ℹ️ Нет свежего списка производства для передачи.", "info")
        return redirect(url_for("factory.produce_today"))

    ids: list[int] = []
    for k in mp.keys():
        try:
            ids.append(int(k))
        except ValueError:
            pass

    products = (
        Product.query
        .filter(Product.factory_id == factory_id, Product.id.in_(ids))
        .all()
    )
    prod_by_id = {p.id: p for p in products}

    rows = []
    total = 0
    for k, qty in mp.items():
        try:
            pid = int(k)
        except ValueError:
            continue

        p = prod_by_id.get(pid)
        if not p:
            continue

        q = int(qty or 0)
        if q <= 0:
            continue

        rows.append({"product": p, "qty": q})
        total += q

    if not rows:
        flash("ℹ️ Нет товаров для передачи.", "info")
        return redirect(url_for("factory.produce_today"))

    return render_template(
        "factory/produce_transfer_confirm.html",
        rows=rows,
        total_qty=total,
        today=date.today().strftime("%d.%m.%Y"),
    )


@factory_bp.route("/produce/transfer-now", methods=["POST"])
@login_required
def produce_transfer_now():
    """
    Transfers “last saved production list” to shop in one click.
    Also auto-fulfills pending shop orders for transferred products.
    """
    factory_id = current_user.factory_id

    prod_date = session.get("mm_last_production_date")
    mp = session.get("mm_last_production_map") or {}

    if not prod_date or prod_date != date.today().isoformat() or not mp:
        flash("⚠️ Нет списка для передачи. Сначала сохраните производство.", "warning")
        return redirect(url_for("factory.produce_today"))

    transferred = 0
    errors = 0
    error_msgs: list[str] = []
    transferred_lines: list[str] = []
    ready_order_ids: set[int] = set()

    for k, qty in mp.items():
        try:
            product_id = int(k)
            quantity = int(qty or 0)
        except ValueError:
            continue

        if quantity <= 0:
            continue

        product = Product.query.filter_by(id=product_id, factory_id=factory_id).first()
        if not product:
            errors += 1
            error_msgs.append(f"Товар #{product_id} не найден")
            continue

        try:
            shop_service.transfer_to_shop(
                factory_id=factory_id,
                product_id=product.id,
                quantity=quantity,
                sell_price_per_item=None,
            )

            mv = Movement(
                factory_id=factory_id,
                product_id=product.id,
                source="factory",
                destination="shop",
                change=quantity,
                note=f"Авто-передача после производства: {quantity} шт.",
                created_by_id=current_user.id,
                timestamp=datetime.utcnow(),
            )
            db.session.add(mv)

            remaining_to_allocate = quantity

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

            transferred += 1
            transferred_lines.append(f"• {product.name}: {quantity} шт.")

        except Exception as e:
            errors += 1
            error_msgs.append(f"{product.name}: {str(e)[:80]}")

    db.session.commit()

    session.pop("mm_last_production_map", None)
    session.pop("mm_last_production_date", None)

    try:
        msg = (
            "🚚 <b>Авто-передача в магазин</b>\n"
            f"Пользователь: <b>{current_user.username}</b>\n"
            f"Позиций: <b>{transferred}</b>\n\n"
            + "\n".join(transferred_lines[:10])
        )
        if ready_order_ids:
            msg += "\n\n✅ Готовы заказы: " + ", ".join(f"#{x}" for x in sorted(ready_order_ids))
        send_telegram_message(
            msg,
            factory_id=current_user.factory_id,
            include_manager_chats=False,
        )
    except Exception:
        pass

    if transferred > 0 and errors == 0:
        flash(f"✅ Передано в магазин позиций: {transferred}", "success")
    elif transferred > 0:
        flash(f"✅ Передано: {transferred}. ⚠️ Ошибки: {errors}.", "warning")
        if error_msgs:
            flash(" • " + " • ".join(error_msgs[:3]), "warning")
    else:
        flash("⚠️ Ничего не передано. Проверьте остатки и товары.", "danger")
        if error_msgs:
            flash(" • " + " • ".join(error_msgs[:3]), "danger")

    return redirect(url_for("shop.list_shop"))

@factory_bp.route("/produce/transfer-skip", methods=["POST"])
@login_required
def produce_transfer_skip():
    session.pop("mm_last_production_map", None)
    session.pop("mm_last_production_date", None)
    flash("Ок 👍 Передачу можно сделать позже через 'Передать в магазин'.", "info")
    return redirect(url_for("factory.produce_today"))


# =========================
# AI Suggestions API (kept)
# =========================

@factory_bp.route("/api/product-suggest", methods=["GET"])
@login_required
def api_product_suggest():
    factory_id = current_user.factory_id
    q = (request.args.get("q") or "").strip()

    if not q or len(q) < 1:
        return jsonify({"items": []})

    variants = _q_variants(q)

    like_filters = []
    for v in variants:
        if not v:
            continue
        like_filters.append(func.lower(Product.name).ilike(f"%{v}%"))
        like_filters.append(func.lower(func.coalesce(Product.category, "")).ilike(f"%{v}%"))

    base_query = Product.query.filter(Product.factory_id == factory_id)
    if like_filters:
        base_query = base_query.filter(or_(*like_filters))

    candidates = base_query.order_by(Product.name.asc()).limit(600).all()

    qn = _norm(q)
    q_lat = _to_lat(q)
    q_cyr = _to_cyr(q)

    scored = []
    for p in candidates:
        name = p.name or ""
        cat = p.category or ""

        n_norm = _norm(name)
        c_norm = _norm(cat)

        n_lat = _to_lat(name)
        n_cyr = _to_cyr(name)

        score = max(
            _sim(qn, n_norm),
            _sim(q_lat, n_lat),
            _sim(q_cyr, n_cyr),
        )

        if qn and qn in c_norm:
            score += 0.08

        if qn and qn in n_norm:
            score += 0.18

        q_comp = qn.replace(" ", "").replace("-", "")
        n_comp = n_norm.replace(" ", "").replace("-", "")
        if q_comp and q_comp in n_comp:
            score += 0.10

        scored.append((score, p))

    scored.sort(key=lambda x: x[0], reverse=True)

    items = []
    for score, p in scored[:25]:
        items.append({
            "id": p.id,
            "name": p.name,
            "category": p.category or "",
            "score": round(float(score), 3),
        })

    return jsonify({"items": items})
