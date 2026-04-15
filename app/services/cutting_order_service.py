from datetime import date
from ..extensions import db
from ..models import CuttingOrder, CuttingOrderMaterial, Product, Fabric

class CuttingOrderService:
    def create_cutting_order(self, factory_id, product_id, cut_date, sets_cut, materials, notes, created_by_id):
        order = CuttingOrder(
            factory_id=factory_id,
            product_id=product_id,
            cut_date=cut_date or date.today(),
            sets_cut=sets_cut,
            status="open",
            notes=notes,
            created_by_id=created_by_id,
        )
        db.session.add(order)
        db.session.flush()  # get order.id

        for m in materials:
            fabric = Fabric.query.get(m["material_id"])
            used_amount = float(m["used_amount"])
            unit_cost = float(fabric.price_per_unit or 0)
            total_cost = used_amount * unit_cost
            order_material = CuttingOrderMaterial(
                cutting_order_id=order.id,
                material_id=fabric.id,
                used_amount=used_amount,
                unit_cost_snapshot=unit_cost,
                total_cost_snapshot=total_cost,
            )
            db.session.add(order_material)
        db.session.commit()
        return order

    def list_cutting_orders(self, factory_id):
        return CuttingOrder.query.filter_by(factory_id=factory_id).order_by(CuttingOrder.cut_date.desc()).all()

    def get_cutting_order(self, order_id, factory_id):
        return CuttingOrder.query.filter_by(id=order_id, factory_id=factory_id).first()
