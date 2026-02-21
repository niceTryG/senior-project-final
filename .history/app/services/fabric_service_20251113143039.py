from difflib import SequenceMatcher
from sqlalchemy import or_
from datetime import date

from ..extensions import db
from ..models import Fabric, Cut


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
    def search_fabrics(self, query: str | None, sort: str = "name"):
        q = Fabric.query

        if query:
            q_lower = f"%{query.lower()}%"
            q = q.filter(
                or_(
                    db.func.lower(Fabric.name).like(q_lower),
                    db.func.lower(Fabric.color).like(q_lower),
                )
            )

        if sort == "qty":
            q = q.order_by(Fabric.quantity.desc())
        elif sort == "price":
            q = q.order_by(Fabric.price_per_unit.desc().nullslast())
        else:
            q = q.order_by(Fabric.name.asc())

        return q.all()

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

        # кандидаты: та же единица измерения и валюта
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

        # 1) точное совпадение → просто добавляем количество
        if exact is not None:
            exact.quantity += quantity
            if price_per_unit is not None:
                exact.price_per_unit = price_per_unit
            if category:
                exact.category = category
            db.session.commit()
            return "merged", exact

        # 2) нет точного, но есть очень похожая ткань → показать окно подтверждения
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

        # 3) ничего похожего → создаём новую ткань
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
