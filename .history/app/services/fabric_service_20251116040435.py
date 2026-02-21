from difflib import SequenceMatcher
from sqlalchemy import or_
from datetime import date
from io import StringIO
import csv

from ..extensions import db
from ..models import Fabric, Cut
from .currency_service import get_usd_uzs_rate   # <-- NEW IMPORT


class FabricService:
    LOW_STOCK_THRESHOLD = 5

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

    # -------- LIST / SEARCH --------
    # -------- LIST / SEARCH --------
    def search_fabrics(
        self,
        query: str | None,
        sort: str = "name",
        category: str | None = None,
        page: int | None = None,
        per_page: int | None = None,
    ):
        q = Fabric.query
    
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

        if sort == "qty":
            q = q.order_by(Fabric.quantity.desc())
        elif sort == "price":
            q = q.order_by(Fabric.price_per_unit.desc().nullslast())
        else:
            q = q.order_by(Fabric.name.asc())

        # pagination mode
        if page is not None and per_page is not None:
            pagination = q.paginate(page=page, per_page=per_page, error_out=False)
            return pagination.items, pagination

        # fallback (no pagination)
        return q.all(), None

    def any_low_stock(self, fabrics) -> bool:
        return any(f.quantity < self.LOW_STOCK_THRESHOLD for f in fabrics)

    def recent_cuts(self, limit: int = 10):
        return (
            Cut.query.join(Fabric)
            .order_by(Cut.id.desc())
            .limit(limit)
            .all()
        )

    # -------- ADD / MERGE LOGIC --------
    def add_or_suggest_merge(
        self,
        name: str,
        color: str | None,
        unit: str,
        quantity: float,
        price_per_unit: float | None,
        price_currency: str,
        category: str | None,
    ):
        name_n = self._normalize(name)
        color_n = self._normalize(color)
        unit_n = self._normalize(unit)

        # candidates: same unit and currency
        candidates = (
            Fabric.query.filter(
                db.func.lower(Fabric.unit) == unit_n,
                Fabric.price_currency == price_currency,
            ).all()
        )

        exact = None
        best = None
        best_score = 0.0

        for f in candidates:
            f_name = self._normalize(f.name)
            f_color = self._normalize(f.color)

            if f_name == name_n and f_color == color_n:
                exact = f
                break

            name_score = self._similarity(name, f.name)
            color_score = self._similarity(color, f.color)
            score = 0.7 * name_score + 0.3 * color_score

            if score > best_score:
                best_score = score
                best = f

        # 1) exact match → just add quantity
        if exact is not None:
            exact.quantity += quantity
            if price_per_unit is not None:
                exact.price_per_unit = price_per_unit
            if category:
                exact.category = category
            db.session.commit()
            return "merged", exact

        # 2) no exact match, but very similar fabric → suggest merge
        if best is not None and best_score >= 0.8:
            new_data = {
                "name": name,
                "color": color,
                "unit": unit,
                "quantity": quantity,
                "price_per_unit": price_per_unit,
                "price_currency": price_currency,
                "category": category,
            }
            return "suggest_merge", (best, new_data)

        # 3) nothing similar → create new fabric
        new_fabric = Fabric(
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
    ):
        fabric = Fabric.query.get(existing_id)
        if not fabric:
            return False

        fabric.quantity += quantity
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
    ):
        fabric = Fabric(
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

    # -------- CATEGORIES / DASHBOARD / EXPORT --------
    def get_categories(self):
        rows = (
            db.session.query(Fabric.category)
            .filter(Fabric.category.isnot(None), Fabric.category != "")
            .distinct()
            .order_by(Fabric.category.asc())
            .all()
        )
        return [r[0] for r in rows]

    def get_dashboard_stats(self):
        """
        Returns aggregated stats for fabrics:
          - total_fabrics: count
          - low_stock_count
          - total_value_uzs: value of fabrics priced in UZS (native)
          - total_value_usd: value of fabrics priced in USD (native)
          - total_value_uzs_equiv: all fabrics converted to UZS
            (UZS-native + USD * current CBU rate), or None if rate unavailable
          - usd_uzs_rate: last CBU rate for 1 USD in UZS, or None
        """
        fabrics = Fabric.query.all()

        total_fabrics = len(fabrics)
        low_stock_count = sum(1 for f in fabrics if f.quantity < self.LOW_STOCK_THRESHOLD)

        total_value_uzs_native = 0.0
        total_value_usd = 0.0

        for f in fabrics:
            if f.price_per_unit is None:
                continue
            value = f.quantity * f.price_per_unit
            if f.price_currency == "UZS":
                total_value_uzs_native += value
            elif f.price_currency == "USD":
                total_value_usd += value

        usd_uzs_rate = get_usd_uzs_rate()
        total_value_uzs_equiv = None
        if usd_uzs_rate:
            total_value_uzs_equiv = total_value_uzs_native + total_value_usd * usd_uzs_rate

        return {
            "total_fabrics": total_fabrics,
            "low_stock_count": low_stock_count,
            # native totals
            "total_value_uzs": total_value_uzs_native,
            "total_value_usd": total_value_usd,
            # converted
            "total_value_uzs_equiv": total_value_uzs_equiv,
            "usd_uzs_rate": usd_uzs_rate,
        }

    def export_csv(self) -> bytes:
        output = StringIO()
        writer = csv.writer(output)

        writer.writerow(
            ["ID", "Name", "Color", "Unit", "Quantity", "PricePerUnit", "Currency", "Category"]
        )

        fabrics = Fabric.query.order_by(Fabric.name.asc()).all()
        for f in fabrics:
            writer.writerow([
                f.id,
                f.name,
                f.color or "",
                f.unit,
                f.quantity,
                f.price_per_unit if f.price_per_unit is not None else "",
                f.price_currency or "",
                f.category or "",
            ])

        csv_text = output.getvalue()
        return csv_text.encode("utf-8-sig")

    # -------- CUT LOGIC --------
    def cut_fabric(self, fabric_id: int, used_amount: float) -> bool:
        if used_amount <= 0:
            return False

        fabric = Fabric.query.get(fabric_id)
        if not fabric or used_amount > fabric.quantity:
            return False

        fabric.quantity -= used_amount
        cut = Cut(
            fabric_id=fabric.id,
            used_amount=used_amount,
            cut_date=date.today(),
        )
        db.session.add(cut)
        db.session.commit()
        return True

    def list_cuts(self, date_from=None, date_to=None):
        q = Cut.query.join(Fabric)

        if date_from:
            q = q.filter(Cut.cut_date >= date_from)
        if date_to:
            q = q.filter(Cut.cut_date <= date_to)

        return q.order_by(Cut.cut_date.desc(), Cut.id.desc()).all()

    def get_usage_summary(self, date_from=None, date_to=None):
        """
        Report on fabric usage for a period.
        Returns dict:
          - rows: list of {fabric: Fabric, total_used: float}
          - total_used: overall usage (sum, no unit normalization)
        """
        q = Cut.query.join(Fabric)

        if date_from:
            q = q.filter(Cut.cut_date >= date_from)
        if date_to:
            q = q.filter(Cut.cut_date <= date_to)

        cuts = q.all()

        stats = {}
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
    def latest_fabrics(self, limit: int = 5):
        q = Fabric.query
        # Prefer created_at if column exists, fallback to id
        if hasattr(Fabric, "created_at"):
            q = q.order_by(Fabric.created_at.desc(), Fabric.id.desc())
        else:
            q = q.order_by(Fabric.id.desc())
        return q.limit(limit).all()
