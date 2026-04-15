from difflib import SequenceMatcher
from sqlalchemy import or_
from datetime import date, datetime, timedelta
from io import StringIO
import csv

from ..extensions import db
from ..models import Fabric, Material, Cut, Product, Production, FabricConsumption, SupplierReceipt, SupplierProfile
from .currency_service import get_usd_uzs_rate


class FabricService:
    LOW_STOCK_THRESHOLD = 5
    DEFAULT_MATERIAL_TYPE = "fabric"

    @staticmethod
    def _generate_supplier_invoice_number(*, receipt_id: int, received_at) -> str:
        date_part = received_at.strftime("%Y%m%d") if received_at else date.today().strftime("%Y%m%d")
        return f"ADR-SR-{date_part}-{int(receipt_id):04d}"

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

    @staticmethod
    def effective_low_stock_threshold(fabric: Fabric) -> float:
        try:
            threshold = float(getattr(fabric, "min_stock_quantity", 0) or 0)
        except (TypeError, ValueError):
            threshold = 0.0
        return threshold if threshold > 0 else float(FabricService.LOW_STOCK_THRESHOLD)

    # ---------- LIST / SEARCH ----------

    def search_fabrics(
        self,
        query: str | None,
        sort: str = "name",
        category: str | None = None,
        material_type: str | None = None,
        stock_state: str | None = None,
        supplier_name: str | None = None,
        page: int | None = None,
        per_page: int | None = None,
        factory_id: int | None = None,
    ):
        return self.search_materials(
            query=query,
            sort=sort,
            category=category,
            material_type=material_type,
            stock_state=stock_state,
            supplier_name=supplier_name,
            page=page,
            per_page=per_page,
            factory_id=factory_id,
        )

    def search_materials(
        self,
        query: str | None,
        sort: str = "name",
        category: str | None = None,
        material_type: str | None = None,
        stock_state: str | None = None,
        supplier_name: str | None = None,
        page: int | None = None,
        per_page: int | None = None,
        factory_id: int | None = None,
    ):
        """
        Return materials (optionally paginated) for given factory,
        with search, category filter and sorting.
        """
        q = Material.query

        if factory_id is not None:
            q = q.filter(Material.factory_id == factory_id)

        # text search by name / color
        if query:
            q_lower = f"%{query.lower()}%"
            q = q.filter(
                or_(
                    db.func.lower(Material.name).like(q_lower),
                    db.func.lower(Material.color).like(q_lower),
                    db.func.lower(Material.supplier_name).like(q_lower),
                )
            )

        if category:
            q = q.filter(db.func.lower(Material.category) == category.lower())

        if material_type:
            q = q.filter(db.func.lower(Material.material_type) == material_type.lower())

        if supplier_name:
            q = q.filter(db.func.lower(db.func.coalesce(Material.supplier_name, "")).like(f"%{supplier_name.lower()}%"))

        normalized_stock_state = (stock_state or "").strip().lower()
        if normalized_stock_state == "out":
            q = q.filter(Material.quantity <= 0)
        elif normalized_stock_state == "low":
            q = q.filter(Material.quantity < db.func.coalesce(Material.min_stock_quantity, self.LOW_STOCK_THRESHOLD))
        elif normalized_stock_state == "healthy":
            q = q.filter(Material.quantity >= db.func.coalesce(Material.min_stock_quantity, self.LOW_STOCK_THRESHOLD))

        # sorting
        if sort == "qty":
            q = q.order_by(Material.quantity.desc().nullslast())
        elif sort == "price":
            q = q.order_by(Material.price_per_unit.desc().nullslast())
        else:
            q = q.order_by(Material.name.asc())

        # pagination mode
        if page is not None and per_page is not None:
            pagination = q.paginate(page=page, per_page=per_page, error_out=False)
            return pagination.items, pagination

        # no pagination
        return q.all(), None

    def get_material_types(self, factory_id: int | None = None):
        q = db.session.query(Fabric.material_type)
        if factory_id is not None:
            q = q.filter(Fabric.factory_id == factory_id)

        rows = (
            q.filter(Fabric.material_type.isnot(None))
            .distinct()
            .order_by(Fabric.material_type.asc())
            .all()
        )
        return [str(material_type or "").strip() for (material_type,) in rows if str(material_type or "").strip()]

    def get_suppliers(self, factory_id: int | None = None):
        q = db.session.query(Fabric.supplier_name)
        if factory_id is not None:
            q = q.filter(Fabric.factory_id == factory_id)

        rows = (
            q.filter(Fabric.supplier_name.isnot(None), Fabric.supplier_name != "")
            .distinct()
            .order_by(Fabric.supplier_name.asc())
            .all()
        )
        return [str(supplier_name or "").strip() for (supplier_name,) in rows if str(supplier_name or "").strip()]

    def summarize_material_mix(self, materials):
        counts_by_type: dict[str, int] = {}
        low_count = 0
        out_count = 0

        for material in materials:
            material_type = str(getattr(material, "material_type", None) or self.DEFAULT_MATERIAL_TYPE).strip().lower()
            counts_by_type[material_type] = counts_by_type.get(material_type, 0) + 1

            qty = float(getattr(material, "quantity", 0) or 0)
            threshold = self.effective_low_stock_threshold(material)
            if qty <= 0:
                out_count += 1
            if qty < threshold:
                low_count += 1

        return {
            "counts_by_type": counts_by_type,
            "low_count": low_count,
            "out_count": out_count,
        }

    def get_supplier_snapshot(
        self,
        *,
        supplier_name: str,
        factory_id: int,
        recent_cut_limit: int = 10,
    ) -> dict:
        materials, _ = self.search_fabrics(
            query=None,
            sort="name",
            supplier_name=supplier_name,
            factory_id=factory_id,
        )

        totals_by_unit: dict[str, float] = {}
        total_value_usd = 0.0
        total_value_uzs = 0.0
        low_stock_items = []
        out_of_stock_items = []

        for material in materials:
            qty = float(getattr(material, "quantity", 0) or 0)
            unit = str(getattr(material, "unit", "") or "").strip() or "unit"
            totals_by_unit[unit] = totals_by_unit.get(unit, 0.0) + qty

            threshold = self.effective_low_stock_threshold(material)
            if qty <= 0:
                out_of_stock_items.append(material)
            if qty < threshold:
                low_stock_items.append(material)

            value = material.total_value()
            if (material.price_currency or "").upper() == "USD":
                total_value_usd += value
            elif (material.price_currency or "").upper() == "UZS":
                total_value_uzs += value

        recent_cuts = (
            Cut.query.join(Fabric)
            .filter(
                Fabric.factory_id == factory_id,
                db.func.lower(db.func.coalesce(Fabric.supplier_name, "")) == supplier_name.strip().lower(),
            )
            .order_by(Cut.cut_date.desc(), Cut.id.desc())
            .limit(recent_cut_limit)
            .all()
        )

        recent_usage_by_unit: dict[str, float] = {}
        for cut in recent_cuts:
            unit = cut.fabric.unit if cut.fabric and cut.fabric.unit else "unit"
            recent_usage_by_unit[unit] = recent_usage_by_unit.get(unit, 0.0) + float(cut.used_amount or 0)

        recent_receipts = (
            SupplierReceipt.query
            .filter(
                SupplierReceipt.factory_id == factory_id,
                db.func.lower(SupplierReceipt.supplier_name) == supplier_name.strip().lower(),
            )
            .order_by(SupplierReceipt.received_at.desc(), SupplierReceipt.id.desc())
            .limit(10)
            .all()
        )

        receipt_totals_by_unit: dict[str, float] = {}
        spend_by_currency: dict[str, float] = {}
        unpaid_by_currency: dict[str, float] = {}
        unpaid_count = 0
        profile = (
            SupplierProfile.query
            .filter(
                SupplierProfile.factory_id == factory_id,
                db.func.lower(SupplierProfile.supplier_name) == supplier_name.strip().lower(),
            )
            .first()
        )
        for receipt in recent_receipts:
            unit = str(receipt.unit or "unit").strip() or "unit"
            receipt_totals_by_unit[unit] = receipt_totals_by_unit.get(unit, 0.0) + float(receipt.quantity_received or 0)
            line_total = receipt.line_total
            currency = str(receipt.currency or "UZS").strip() or "UZS"
            if line_total is not None:
                spend_by_currency[currency] = spend_by_currency.get(currency, 0.0) + float(line_total)
                if (receipt.payment_status or "unpaid").lower() != "paid":
                    unpaid_by_currency[currency] = unpaid_by_currency.get(currency, 0.0) + float(line_total)
            if (receipt.payment_status or "unpaid").lower() != "paid":
                unpaid_count += 1

        material_mix = self.summarize_material_mix(materials)

        return {
            "materials": materials,
            "material_mix": material_mix,
            "totals_by_unit": totals_by_unit,
            "total_value_usd": total_value_usd,
            "total_value_uzs": total_value_uzs,
            "low_stock_items": low_stock_items,
            "out_of_stock_items": out_of_stock_items,
            "recent_cuts": recent_cuts,
            "recent_usage_by_unit": recent_usage_by_unit,
            "recent_receipts": recent_receipts,
            "receipt_totals_by_unit": receipt_totals_by_unit,
            "spend_by_currency": spend_by_currency,
            "unpaid_by_currency": unpaid_by_currency,
            "unpaid_count": unpaid_count,
            "profile": profile,
        }

    def get_supplier_statement(
        self,
        *,
        supplier_name: str,
        factory_id: int,
    ) -> dict:
        snapshot = self.get_supplier_snapshot(
            supplier_name=supplier_name,
            factory_id=factory_id,
        )

        receipts = (
            SupplierReceipt.query
            .filter(
                SupplierReceipt.factory_id == factory_id,
                db.func.lower(SupplierReceipt.supplier_name) == supplier_name.strip().lower(),
            )
            .order_by(SupplierReceipt.received_at.desc(), SupplierReceipt.id.desc())
            .all()
        )

        paid_by_currency: dict[str, float] = {}
        unpaid_by_currency: dict[str, float] = {}
        receipt_count_by_status = {"paid": 0, "unpaid": 0}

        for receipt in receipts:
            status = (receipt.payment_status or "unpaid").lower()
            if status not in receipt_count_by_status:
                status = "unpaid"
            receipt_count_by_status[status] += 1

            line_total = receipt.line_total
            if line_total is None:
                continue
            currency = str(receipt.currency or "UZS").strip() or "UZS"
            if status == "paid":
                paid_by_currency[currency] = paid_by_currency.get(currency, 0.0) + float(line_total)
            else:
                unpaid_by_currency[currency] = unpaid_by_currency.get(currency, 0.0) + float(line_total)

        return {
            "snapshot": snapshot,
            "receipts": receipts,
            "paid_by_currency": paid_by_currency,
            "unpaid_by_currency": unpaid_by_currency,
            "receipt_count_by_status": receipt_count_by_status,
        }

    def list_supplier_receipts(
        self,
        *,
        factory_id: int,
        supplier_name: str | None = None,
        payment_status: str | None = None,
        invoice_number: str | None = None,
        date_from=None,
        date_to=None,
        q: str | None = None,
        limit: int = 200,
    ) -> list[SupplierReceipt]:
        query = SupplierReceipt.query.filter(SupplierReceipt.factory_id == factory_id)

        if supplier_name:
            query = query.filter(
                db.func.lower(db.func.coalesce(SupplierReceipt.supplier_name, "")).like(f"%{supplier_name.strip().lower()}%")
            )

        normalized_status = (payment_status or "").strip().lower()
        if normalized_status in {"paid", "unpaid"}:
            query = query.filter(db.func.lower(db.func.coalesce(SupplierReceipt.payment_status, "unpaid")) == normalized_status)

        if invoice_number:
            query = query.filter(
                db.func.lower(db.func.coalesce(SupplierReceipt.invoice_number, "")).like(f"%{invoice_number.strip().lower()}%")
            )

        if date_from:
            query = query.filter(SupplierReceipt.received_at >= date_from)

        if date_to:
            query = query.filter(SupplierReceipt.received_at < date_to)

        if q:
            q_like = f"%{q.strip().lower()}%"
            query = query.filter(
                or_(
                    db.func.lower(db.func.coalesce(SupplierReceipt.supplier_name, "")).like(q_like),
                    db.func.lower(db.func.coalesce(SupplierReceipt.material_name, "")).like(q_like),
                    db.func.lower(db.func.coalesce(SupplierReceipt.note, "")).like(q_like),
                    db.func.lower(db.func.coalesce(SupplierReceipt.invoice_number, "")).like(q_like),
                )
            )

        return (
            query
            .order_by(SupplierReceipt.received_at.desc(), SupplierReceipt.id.desc())
            .limit(limit)
            .all()
        )

    def supplier_receipt_overview(
        self,
        *,
        factory_id: int,
        supplier_name: str | None = None,
        payment_status: str | None = None,
        invoice_number: str | None = None,
        date_from=None,
        date_to=None,
        q: str | None = None,
    ) -> dict:
        receipts = self.list_supplier_receipts(
            factory_id=factory_id,
            supplier_name=supplier_name,
            payment_status=payment_status,
            invoice_number=invoice_number,
            date_from=date_from,
            date_to=date_to,
            q=q,
        )

        totals_by_currency: dict[str, float] = {}
        unpaid_by_currency: dict[str, float] = {}
        counts = {"paid": 0, "unpaid": 0}
        suppliers: set[str] = set()

        for receipt in receipts:
            suppliers.add((receipt.supplier_name or "").strip())
            status = (receipt.payment_status or "unpaid").strip().lower()
            if status not in counts:
                status = "unpaid"
            counts[status] += 1

            if receipt.line_total is not None:
                currency = (receipt.currency or "UZS").strip() or "UZS"
                totals_by_currency[currency] = totals_by_currency.get(currency, 0.0) + float(receipt.line_total)
                if status != "paid":
                    unpaid_by_currency[currency] = unpaid_by_currency.get(currency, 0.0) + float(receipt.line_total)

        available_suppliers = [
            row[0] for row in (
                db.session.query(SupplierReceipt.supplier_name)
                .filter(SupplierReceipt.factory_id == factory_id)
                .filter(SupplierReceipt.supplier_name.isnot(None))
                .distinct()
                .order_by(SupplierReceipt.supplier_name.asc())
                .all()
            ) if row[0]
        ]

        return {
            "receipts": receipts,
            "counts": counts,
            "totals_by_currency": totals_by_currency,
            "unpaid_by_currency": unpaid_by_currency,
            "supplier_count": len([name for name in suppliers if name]),
            "available_suppliers": available_suppliers,
        }

    def upsert_supplier_profile(
        self,
        *,
        factory_id: int,
        supplier_name: str,
        contact_person: str | None = None,
        phone: str | None = None,
        telegram_handle: str | None = None,
        note: str | None = None,
    ) -> SupplierProfile:
        normalized_supplier = (supplier_name or "").strip()
        profile = (
            SupplierProfile.query
            .filter(
                SupplierProfile.factory_id == factory_id,
                db.func.lower(SupplierProfile.supplier_name) == normalized_supplier.lower(),
            )
            .first()
        )

        if not profile:
            profile = SupplierProfile(
                factory_id=factory_id,
                supplier_name=normalized_supplier,
            )
            db.session.add(profile)

        profile.supplier_name = normalized_supplier
        profile.contact_person = (contact_person or "").strip() or None
        profile.phone = (phone or "").strip() or None
        profile.telegram_handle = (telegram_handle or "").strip() or None
        profile.note = (note or "").strip() or None
        db.session.commit()
        return profile

    def export_supplier_statement_csv(
        self,
        *,
        supplier_name: str,
        factory_id: int,
    ) -> bytes:
        statement = self.get_supplier_statement(
            supplier_name=supplier_name,
            factory_id=factory_id,
        )

        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "Supplier",
                "ReceivedAt",
                "Material",
                "Quantity",
                "Unit",
                "UnitCost",
                "Currency",
                "LineTotal",
                "InvoiceNumber",
                "PaymentStatus",
                "Note",
            ]
        )

        for receipt in statement["receipts"]:
            writer.writerow(
                [
                    receipt.supplier_name,
                    receipt.received_at,
                    receipt.material_name,
                    receipt.quantity_received,
                    receipt.unit,
                    receipt.unit_cost if receipt.unit_cost is not None else "",
                    receipt.currency or "",
                    receipt.line_total if receipt.line_total is not None else "",
                    receipt.invoice_number or "",
                    receipt.payment_status or "unpaid",
                    receipt.note or "",
                ]
            )

        return output.getvalue().encode("utf-8-sig")

    def get_supplier_receipt(
        self,
        *,
        receipt_id: int,
        factory_id: int,
    ) -> SupplierReceipt | None:
        return SupplierReceipt.query.filter_by(id=receipt_id, factory_id=factory_id).first()

    def receive_supplier_material(
        self,
        *,
        factory_id: int,
        fabric_id: int,
        supplier_name: str,
        quantity_received: float,
        received_at,
        created_by_id: int | None = None,
        unit_cost: float | None = None,
        currency: str | None = None,
        invoice_number: str | None = None,
        payment_status: str | None = None,
        note: str | None = None,
    ) -> tuple[bool, str, SupplierReceipt | None]:
        if quantity_received <= 0:
            return False, "Quantity must be greater than zero", None

        fabric = Fabric.query.filter_by(id=fabric_id, factory_id=factory_id).first()
        if not fabric:
            return False, "Material not found", None

        normalized_supplier = (supplier_name or "").strip()
        if not normalized_supplier:
            normalized_supplier = (fabric.supplier_name or "").strip()
        if not normalized_supplier:
            return False, "Supplier name is required", None

        try:
            fabric.quantity = float(fabric.quantity or 0) + float(quantity_received)
            fabric.supplier_name = normalized_supplier

            receipt = SupplierReceipt(
                factory_id=factory_id,
                fabric_id=fabric.id,
                created_by_id=created_by_id,
                supplier_name=normalized_supplier,
                material_name=fabric.name,
                quantity_received=float(quantity_received),
                unit=fabric.unit or "pcs",
                unit_cost=unit_cost,
                currency=(currency or fabric.price_currency or "UZS"),
                invoice_number=(invoice_number or "").strip() or None,
                payment_status=((payment_status or "unpaid").strip().lower() or "unpaid"),
                note=(note or "").strip() or None,
                received_at=received_at,
            )
            db.session.add(receipt)
            db.session.flush()
            if not receipt.invoice_number:
                receipt.invoice_number = self._generate_supplier_invoice_number(
                    receipt_id=receipt.id,
                    received_at=received_at,
                )
            db.session.commit()
            return True, "Material receipt saved", receipt
        except Exception:
            db.session.rollback()
            raise

    def update_supplier_receipt(
        self,
        *,
        receipt_id: int,
        factory_id: int,
        quantity_received: float,
        received_at,
        unit_cost: float | None = None,
        currency: str | None = None,
        invoice_number: str | None = None,
        payment_status: str | None = None,
        note: str | None = None,
    ) -> tuple[bool, str, SupplierReceipt | None]:
        receipt = SupplierReceipt.query.filter_by(id=receipt_id, factory_id=factory_id).first()
        if not receipt:
            return False, "Receipt not found", None

        if quantity_received <= 0:
            return False, "Quantity must be greater than zero", receipt

        fabric = Fabric.query.filter_by(id=receipt.fabric_id, factory_id=factory_id).first()
        if not fabric:
            return False, "Material not found", receipt

        normalized_status = (payment_status or receipt.payment_status or "unpaid").strip().lower()
        if normalized_status not in {"paid", "unpaid"}:
            normalized_status = "unpaid"

        try:
            old_qty = float(receipt.quantity_received or 0)
            new_qty = float(quantity_received or 0)
            fabric.quantity = float(fabric.quantity or 0) - old_qty + new_qty
            if fabric.quantity < 0:
                return False, "This correction would make material stock negative", receipt

            receipt.quantity_received = new_qty
            receipt.received_at = received_at or receipt.received_at
            receipt.unit_cost = unit_cost
            receipt.currency = (currency or receipt.currency or "UZS").strip() or "UZS"
            receipt.invoice_number = (invoice_number or "").strip() or self._generate_supplier_invoice_number(
                receipt_id=receipt.id,
                received_at=receipt.received_at,
            )
            receipt.payment_status = normalized_status
            receipt.note = (note or "").strip() or None
            receipt.material_name = fabric.name
            receipt.unit = fabric.unit or receipt.unit or "pcs"
            db.session.commit()
            return True, "Receipt updated", receipt
        except Exception:
            db.session.rollback()
            raise

    def update_supplier_receipt_status(
        self,
        *,
        receipt_id: int,
        factory_id: int,
        payment_status: str,
    ) -> tuple[bool, str, SupplierReceipt | None]:
        receipt = SupplierReceipt.query.filter_by(id=receipt_id, factory_id=factory_id).first()
        if not receipt:
            return False, "Receipt not found", None

        normalized_status = (payment_status or "").strip().lower()
        if normalized_status not in {"paid", "unpaid"}:
            normalized_status = "unpaid"

        receipt.payment_status = normalized_status
        db.session.commit()
        return True, "Receipt updated", receipt

    def any_low_stock(self, fabrics) -> bool:
        """Return True if any fabric is below LOW_STOCK_THRESHOLD."""
        for f in fabrics:
            qty = f.quantity or 0
            if qty < self.effective_low_stock_threshold(f):
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
        material_type: str | None,
        min_stock_quantity: float | None,
        supplier_name: str | None,
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
        material_type_n = self._normalize(material_type) or self.DEFAULT_MATERIAL_TYPE

        # candidates: same unit, currency, factory
        candidates = Fabric.query.filter(
            Fabric.factory_id == factory_id,
            db.func.lower(Fabric.unit) == unit_n,
            Fabric.price_currency == price_currency,
            db.func.lower(Fabric.material_type) == material_type_n,
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
            exact.material_type = material_type_n
            if price_per_unit is not None:
                exact.price_per_unit = price_per_unit
            if category:
                exact.category = category
            if min_stock_quantity is not None:
                exact.min_stock_quantity = min_stock_quantity
            if supplier_name:
                exact.supplier_name = supplier_name
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
                "material_type": material_type_n,
                "min_stock_quantity": min_stock_quantity,
                "supplier_name": supplier_name,
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
            material_type=material_type_n,
            min_stock_quantity=min_stock_quantity if min_stock_quantity is not None else self.LOW_STOCK_THRESHOLD,
            supplier_name=supplier_name,
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
        material_type: str | None,
        min_stock_quantity: float | None,
        supplier_name: str | None,
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
        fabric.material_type = self._normalize(material_type) or self.DEFAULT_MATERIAL_TYPE

        if price_per_unit is not None:
            fabric.price_per_unit = price_per_unit
        if category:
            fabric.category = category
        if min_stock_quantity is not None:
            fabric.min_stock_quantity = min_stock_quantity
        if supplier_name:
            fabric.supplier_name = supplier_name

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
        material_type: str | None,
        min_stock_quantity: float | None,
        supplier_name: str | None,
        factory_id: int,
    ):
        """
        Force-create a new fabric (when user clicks 'create new' instead of merge).
        """
        return self.create_material(
            name=name,
            color=color,
            unit=unit,
            quantity=quantity,
            price_per_unit=price_per_unit,
            price_currency=price_currency,
            category=category,
            material_type=material_type,
            min_stock_quantity=min_stock_quantity,
            supplier_name=supplier_name,
            factory_id=factory_id,
        )

    def create_material(
        self,
        name: str,
        color: str | None,
        unit: str,
        quantity: float,
        price_per_unit: float | None,
        price_currency: str,
        category: str | None,
        material_type: str | None,
        min_stock_quantity: float | None,
        supplier_name: str | None,
        factory_id: int,
    ):
        material = Material(
            factory_id=factory_id,
            name=name,
            color=color,
            unit=unit,
            quantity=quantity,
            price_per_unit=price_per_unit,
            price_currency=price_currency,
            category=category,
            material_type=self._normalize(material_type) or self.DEFAULT_MATERIAL_TYPE,
            min_stock_quantity=min_stock_quantity if min_stock_quantity is not None else self.LOW_STOCK_THRESHOLD,
            supplier_name=supplier_name,
        )
        db.session.add(material)
        db.session.commit()
        return material

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
        q = Material.query
        if factory_id is not None:
            q = q.filter(Material.factory_id == factory_id)
        materials = q.all()

        total_fabrics = len(materials)
        low_stock_count = sum(
            1 for material in materials if (material.quantity or 0) < self.effective_low_stock_threshold(material)
        )

        total_value_uzs_native = 0.0
        total_value_usd = 0.0

        for material in materials:
            if material.price_per_unit is None:
                continue

            qty = material.quantity or 0.0
            value = qty * float(material.price_per_unit)

            if material.price_currency == "UZS":
                total_value_uzs_native += value
            elif material.price_currency == "USD":
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

    def export_csv(
        self,
        factory_id: int | None = None,
        query: str | None = None,
        category: str | None = None,
        material_type: str | None = None,
        stock_state: str | None = None,
        supplier_name: str | None = None,
    ) -> bytes:
        """
        Export fabrics as UTF-8-SIG CSV for Excel.
        """
        return self.export_materials_csv(
            factory_id=factory_id,
            query=query,
            category=category,
            material_type=material_type,
            stock_state=stock_state,
            supplier_name=supplier_name,
        )

    def export_materials_csv(
        self,
        factory_id: int | None = None,
        query: str | None = None,
        category: str | None = None,
        material_type: str | None = None,
        stock_state: str | None = None,
        supplier_name: str | None = None,
    ) -> bytes:
        """
        Export materials as UTF-8-SIG CSV for Excel.
        """
        output = StringIO()
        writer = csv.writer(output)

        writer.writerow(
            ["ID", "Name", "Color", "MaterialType", "Unit", "Quantity", "MinStock", "PricePerUnit", "Currency", "Category", "Supplier"]
        )

        materials, _ = self.search_materials(
            query=query,
            sort="name",
            category=category,
            material_type=material_type,
            stock_state=stock_state,
            supplier_name=supplier_name,
            factory_id=factory_id,
        )
        for material in materials:
            writer.writerow([
                material.id,
                material.name,
                material.color or "",
                getattr(material, "material_type", self.DEFAULT_MATERIAL_TYPE),
                material.unit,
                material.quantity or 0,
                getattr(material, "min_stock_quantity", self.LOW_STOCK_THRESHOLD),
                material.price_per_unit if material.price_per_unit is not None else "",
                material.price_currency or "",
                material.category or "",
                getattr(material, "supplier_name", None) or "",
            ])

        csv_text = output.getvalue()
        return csv_text.encode("utf-8-sig")

    # ---------- CUT LOGIC ----------

    def cut_fabric(
        self,
        fabric_id: int,
        used_amount: float,
        factory_id: int,
        *,
        cut_date=None,
        comment: str | None = None,
        created_by_id: int | None = None,
    ) -> Cut | None:
        """
        Reduce fabric quantity by used_amount and create Cut row with snapshot details.
        """
        return self.cut_material(
            material_id=fabric_id,
            used_amount=used_amount,
            factory_id=factory_id,
            cut_date=cut_date,
            comment=comment,
            created_by_id=created_by_id,
        )

    def cut_material(
        self,
        material_id: int,
        used_amount: float,
        factory_id: int,
        *,
        cut_date=None,
        comment: str | None = None,
        created_by_id: int | None = None,
    ) -> Cut | None:
        """
        Reduce material quantity by used_amount and create Cut row with snapshot details.
        """
        if used_amount <= 0:
            return None

        material = (
            Material.query
            .filter_by(id=material_id, factory_id=factory_id)
            .first()
        )
        if not material:
            return None

        current_qty = material.quantity or 0.0
        if used_amount > current_qty:
            return None

        remaining_quantity = current_qty - used_amount
        material.quantity = remaining_quantity

        cut = Cut(
            fabric_id=material.id,
            used_amount=used_amount,
            cut_date=cut_date or date.today(),
            remaining_quantity=remaining_quantity,
            comment=(comment or "").strip() or None,
            created_by_id=created_by_id,
        )
        db.session.add(cut)
        db.session.commit()
        return cut

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
        return self.latest_materials(limit=limit, factory_id=factory_id)
    def latest_materials(self, limit: int = 5, factory_id: int | None = None):
        q = Material.query
        if factory_id is not None:
            q = q.filter(Material.factory_id == factory_id)

        if hasattr(Material, "created_at"):
            q = q.order_by(Material.created_at.desc(), Material.id.desc())
        else:
            q = q.order_by(Material.id.desc())

        return q.limit(limit).all()

    def produce_with_fabric(
        self,
        *,
        factory_id: int,
        product_id: int,
        quantity: int,
        fabric_id: int,
        used_amount: float,
        note: str | None = None,
        production_date=None,
    ) -> tuple[bool, str]:
        """
        Creates Production, increases product.qty, decreases fabric.qty,
        and logs FabricConsumption. All in one transaction.
        """
        if quantity <= 0:
            return False, "Quantity must be > 0"
        if used_amount <= 0:
            return False, "Used amount must be > 0"

        production_date = production_date or date.today()

        product = Product.query.filter_by(id=product_id, factory_id=factory_id).first()
        if not product:
            return False, "Product not found"

        fabric = Fabric.query.filter_by(id=fabric_id, factory_id=factory_id).first()
        if not fabric:
            return False, "Fabric not found"

        current_qty = fabric.quantity or 0.0
        if used_amount > current_qty:
            return False, "Not enough fabric quantity"

        try:
            # 1) create production
            prod = Production(
                product_id=product.id,
                date=production_date,
                quantity=quantity,
                note=note,
            )
            db.session.add(prod)
            db.session.flush()  # get prod.id without commit

            # 2) update product stock
            product.quantity = (product.quantity or 0) + quantity

            # 3) deduct fabric
            fabric.quantity = current_qty - used_amount

            # 4) log consumption
            cons = FabricConsumption(
                factory_id=factory_id,
                fabric_id=fabric.id,
                production_id=prod.id,
                used_amount=used_amount,
            )
            db.session.add(cons)

            db.session.commit()
            return True, "OK"
        except Exception as e:
            db.session.rollback()
            return False, str(e)
