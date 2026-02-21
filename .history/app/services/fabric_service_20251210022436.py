from difflib import SequenceMatcher
from sqlalchemy import or_
from datetime import date
from io import StringIO
import csv

from ..extensions import db
from ..models import Fabric, Cut
from .currency_service import get_usd_uzs_rate


class FabricService:
    LOW_STOCK_THRESHOLD = 5

    # ---------- HELPERS ----------

    @staticmethod
    def _normalize(s: str | None) -> str:
        return (s or "").strip().lower()

    @staticmethod
    def _similarity(a: str | None, b: str | None) -> float:
        a = FabricService._normalize(a)
        b = FabricService._normalize(b)
        if not a and not b:
            return 1.0
        if not a or not b:
            return 0.0
        return SequenceMatcher(None, a, b).ratio()

    # ---------- LIST / SEARCH ----------

    def search_fabrics(
        self,
        query: str | None,
        sort: str = "name",
        category: str | None = None,
        page: int | None = None,
        per_page: int | None = None,
        factory_id: int | None = None,
    ):
        """
        Return fabrics (optionally paginated) for given factory,
        with search, category filter and sorting.
        """
        q = Fabric.query

        if factory_id is not None:
            q = q.filter(Fabric.factory_id == factory_id)

        # text search by name / color
        if query:
            q_lower = f"%{query.lower()}%"
            q = q.filter(
                or_(
                    db.func.lower(Fabric.name).like(q_lower),
                    db.func.lower(Fabric.color).like(q_lower),
                )
            )

        if category:
            q = q.filter(db.func.lower(Fabric.category) == category.lower())

        # sorting
        if sort == "qty":
            q = q.order_by(Fabric.quantity.desc().nullslast())
        elif sort == "price":
            q = q.order_by(Fabric.price_per_unit.desc().nullslast())
        else:
            q = q.order_by(Fabric.name.asc())

        # pagination mode
        if page is not None and per_page is not None:
            pagination = q.paginate(page=page, per_page=per_page, error_out=False)
            return pagination.items, pagination

        # no pagination
        return q.all(), None

    def any_low_stock(self, fabrics) -> bool:
        """Return True if any fabric is below LOW_STOCK_THRESHOLD."""
        for f in fabrics:
            qty = f.quantity or 0
            if qty < self.LOW_STOCK_THRESHOLD:
                return True
        return False

    def recent_cuts(self, limit: int = 10, factory_id: int | None = None):
        """
        Last N cuts, joined with Fabric, scoped by factory.
        """
        q = Cut.query.join(Fabric)
        if factory_id is not None:
            q = q.filter(Fabric.factory_id == factory_id)

        return (
            q.order_by(Cut.id.desc())
            .limit(limit)
            .all()
        )

    # ---------- ADD / MERGE LOGIC ----------

    def add_or_suggest_merge(
        self,
        name: str,
        color: str | None,
        unit: str,
        quantity: float,
        price_per_unit: float | None,
        price_currency: str,
        category: str | None,
        factory_id: int,
    ):
        """
        Try to find same/similar fabric for this factory and currency:
          1) exact match by normalized name+color → merge
          2) best similar with score >= 0.8        → suggest merge
          3) else                                  → create new fabric
        """
        name_n = self._normalize(name)
        color_n = self._normalize(color)
        unit_n = self._normalize(unit)

        # candidates: same unit, currency, factory
        candidates = Fabric.query.filter(
            Fabric.factory_id == factory_id,
            db.func.lower(Fabric.unit) == unit_n,
            Fabric.price_currency == price_currency,
        ).all()

        exact = None
        best = None
        best_score = 0.0

        for f in candidates:
            f_name = self._normalize(f.name)
            f_color = self._normalize(f.color)

            # exact match name+color
            if f_name == name_n and f_color == color_n:
                exact = f
                break

            name_score = self._similarity(name, f.name)
            color_score = self._similarity(color, f.color)
            score = 0.7 * name_score + 0.3 * color_score

            if score > best_score:
                best_score = score
                best = f

        # 1) exact match → just add quantity / update price & category
        if exact is not None:
            exact.quantity = (exact.quantity or 0.0) + quantity
            if price_per_unit is not None:
                exact.price_per_unit = price_per_unit
            if category:
                exact.category = category
            db.session.commit()
            return "merged", exact

        # 2) very similar → suggest merge
        if best is not None and best_score >= 0.8:
            new_data = {
                "name": name,
                "color": color,
                "unit": unit,
                "quantity": quantity,
                "price_per_unit": price_per_unit,
                "price_currency": price_currency,
                "category": category,
                "factory_id": factory_id,
            }
            return "suggest_merge", (best, new_data)

        # 3) no similar → create new
        new_fabric = Fabric(
            factory_id=factory_id,
            name=name,
            color=color,
            unit=unit,
            quantity=quantity,
            price_per_unit=price_per_unit,
            price_currency=price_currency,
            category=category,
        )
        db.session.add(new_fabric)
        db.session.commit()
        return "created", new_fabric

    def confirm_merge(
        self,
        existing_id: int,
        quantity: float,
        price_per_unit: float | None,
        price_currency: str,
        category: str | None,
        factory_id: int,
    ):
        """
        Actually merge new delivery into existing fabric.
        """
        fabric = (
            Fabric.query
            .filter_by(id=existing_id, factory_id=factory_id)
            .first()
        )
        if not fabric:
            return False

        fabric.quantity = (fabric.quantity or 0.0) + quantity
        fabric.price_currency = price_currency

        if price_per_unit is not None:
            fabric.price_per_unit = price_per_unit
        if category:
            fabric.category = category

        db.session.commit()
        return True

    def create_new(
        self,
        name: str,
        color: str | None,
        unit: str,
        quantity: float,
        price_per_unit: float | None,
        price_currency: str,
        category: str | None,
        factory_id: int,
    ):
        """
        Force-create a new fabric (when user clicks 'create new' instead of merge).
        """
        fabric = Fabric(
            factory_id=factory_id,
            name=name,
            color=color,
            unit=unit,
            quantity=quantity,
            price_per_unit=price_per_unit,
            price_currency=price_currency,
            category=category,
        )
        db.session.add(fabric)
        db.session.commit()
        return fabric

    # ---------- CATEGORIES / DASHBOARD / EXPORT ----------

    def get_categories(self, factory_id: int | None = None):
        """
        Return distinct fabric categories for this factory.
        """
        q = db.session.query(Fabric.category).filter(
            Fabric.category.isnot(None),
            Fabric.category != "",
        )
        if factory_id is not None:
            q = q.filter(Fabric.factory_id == factory_id)

        rows = (
            q.distinct()
            .order_by(Fabric.category.asc())
            .all()
        )
        return [r[0] for r in rows]

    def get_dashboard_stats(self, factory_id: int | None = None):
        """
        Aggregated stats for fabrics:
          - total_fabrics: count
          - low_stock_count
          - total_value_uzs: value of fabrics priced in UZS
          - total_value_usd: value of fabrics priced in USD
          - total_value_uzs_equiv: all fabrics converted to UZS
          - usd_uzs_rate: last CBU rate for 1 USD in UZS, or None
        """
        q = Fabric.query
        if factory_id is not None:
            q = q.filter(Fabric.factory_id == factory_id)
        fabrics = q.all()

        total_fabrics = len(fabrics)
        low_stock_count = sum(
            1 for f in fabrics if (f.quantity or 0) < self.LOW_STOCK_THRESHOLD
        )

        total_value_uzs_native = 0.0
        total_value_usd = 0.0

        for f in fabrics:
            if f.price_per_unit is None:
                continue

            qty = f.quantity or 0.0
            value = qty * float(f.price_per_unit)

            if f.price_currency == "UZS":
                total_value_uzs_native += value
            elif f.price_currency == "USD":
                total_value_usd += value

        usd_uzs_rate = None
        try:
            usd_uzs_rate = get_usd_uzs_rate()
        except Exception:
            usd_uzs_rate = None

        total_value_uzs_equiv = None
        if usd_uzs_rate:
            total_value_uzs_equiv = (
                total_value_uzs_native + total_value_usd * usd_uzs_rate
            )

        return {
            "total_fabrics": total_fabrics,
            "low_stock_count": low_stock_count,
            "total_value_uzs": total_value_uzs_native,
            "total_value_usd": total_value_usd,
            "total_value_uzs_equiv": total_value_uzs_equiv,
            "usd_uzs_rate": usd_uzs_rate,
        }

    def export_csv(self, factory_id: int | None = None) -> bytes:
        """
        Export fabrics as UTF-8-SIG CSV for Excel.
        """
        output = StringIO()
        writer = csv.writer(output)

        writer.writerow(
            ["ID", "Name", "Color", "Unit", "Quantity", "PricePerUnit", "Currency", "Category"]
        )

        q = Fabric.query
        if factory_id is not None:
            q = q.filter(Fabric.factory_id == factory_id)

        fabrics = q.order_by(Fabric.name.asc()).all()
        for f in fabrics:
            writer.writerow([
                f.id,
                f.name,
                f.color or "",
                f.unit,
                f.quantity or 0,
                f.price_per_unit if f.price_per_unit is not None else "",
                f.price_currency or "",
                f.category or "",
            ])

        csv_text = output.getvalue()
        return csv_text.encode("utf-8-sig")

    # ---------- CUT LOGIC ----------

    def cut_fabric(self, fabric_id: int, used_amount: float, factory_id: int) -> bool:
        """
        Reduce fabric quantity by used_amount and create Cut row.
        Returns True if cut is successful.
        """
        if used_amount <= 0:
            return False

        fabric = (
            Fabric.query
            .filter_by(id=fabric_id, factory_id=factory_id)
            .first()
        )
        if not fabric:
            return False

        current_qty = fabric.quantity or 0.0
        if used_amount > current_qty:
            return False

        fabric.quantity = current_qty - used_amount

        cut = Cut(
            fabric_id=fabric.id,
            used_amount=used_amount,
            cut_date=date.today(),
        )
        db.session.add(cut)
        db.session.commit()
        return True

    def list_cuts(
        self,
        date_from=None,
        date_to=None,
        factory_id: int | None = None,
        fabric_id: int | None = None,
        q: str | None = None,
        sort: str = "date_desc",
        page: int | None = None,
        per_page: int | None = None,
    ):
        """
        Returns (cuts, pagination) where:
          - cuts: list of Cut objects
          - pagination: flask-sqlalchemy Pagination or None (if page/per_page not provided)
        Supports:
          - date_from / date_to (by cut_date)
          - filter by fabric_id
          - search by fabric name (q)
          - sort: date_desc / date_asc / amount_desc / amount_asc
        """
        qy = Cut.query.join(Fabric)

        if factory_id is not None:
            qy = qy.filter(Fabric.factory_id == factory_id)

        if date_from:
            qy = qy.filter(Cut.cut_date >= date_from)
        if date_to:
            qy = qy.filter(Cut.cut_date <= date_to)

        if fabric_id:
            qy = qy.filter(Cut.fabric_id == fabric_id)

        if q:
            pattern = f"%{q.lower()}%"
            qy = qy.filter(db.func.lower(Fabric.name).like(pattern))

        # sorting
        if sort == "date_asc":
            qy = qy.order_by(Cut.cut_date.asc(), Cut.id.asc())
        elif sort == "amount_desc":
            qy = qy.order_by(Cut.used_amount.desc().nullslast(), Cut.id.desc())
        elif sort == "amount_asc":
            qy = qy.order_by(Cut.used_amount.asc().nullslast(), Cut.id.asc())
        else:  # default: date_desc
            qy = qy.order_by(Cut.cut_date.desc(), Cut.id.desc())

        if page is not None and per_page is not None:
            pagination = qy.paginate(page=page, per_page=per_page, error_out=False)
            return pagination.items, pagination

        cuts = qy.all()
        return cuts, None


    def get_usage_summary(
        self,
        date_from=None,
        date_to=None,
        factory_id: int | None = None,
    ):
        """
        Report on fabric usage for a period.
        Returns dict:
          - rows: list of {fabric: Fabric, total_used: float}
          - total_used: overall usage (sum, no unit normalization)
        """
        q = Cut.query.join(Fabric)
        if factory_id is not None:
            q = q.filter(Fabric.factory_id == factory_id)

        if date_from:
            q = q.filter(Cut.cut_date >= date_from)
        if date_to:
            q = q.filter(Cut.cut_date <= date_to)

        cuts = q.all()

        stats: dict[int, dict] = {}
        for c in cuts:
            f = c.fabric
            if not f:
                continue
            key = f.id
            if key not in stats:
                stats[key] = {
                    "fabric": f,
                    "total_used": 0.0,
                }
            stats[key]["total_used"] += c.used_amount

        total_used = sum(r["total_used"] for r in stats.values())

        return {
            "rows": list(stats.values()),
            "total_used": total_used,
        }

    def latest_fabrics(self, limit: int = 5, factory_id: int | None = None):
        """
        Last added fabrics (by created_at if present, otherwise by id).
        Used for 'Последние 5' view.
        """
        q = Fabric.query
        if factory_id is not None:
            q = q.filter(Fabric.factory_id == factory_id)

        if hasattr(Fabric, "created_at"):
            q = q.order_by(Fabric.created_at.desc(), Fabric.id.desc())
        else:
            q = q.order_by(Fabric.id.desc())

        return q.limit(limit).all()
