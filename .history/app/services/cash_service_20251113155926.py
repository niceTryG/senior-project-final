from datetime import date
from ..extensions import db
from ..models import CashRecord


class CashService:
    def list_records(self, date_from=None, date_to=None):
        q = CashRecord.query

        if date_from:
            q = q.filter(CashRecord.date >= date_from)
        if date_to:
            q = q.filter(CashRecord.date <= date_to)

        return q.order_by(CashRecord.date.desc(), CashRecord.id.desc()).all()

    def totals(self, date_from=None, date_to=None):
        q = CashRecord.query

        if date_from:
            q = q.filter(CashRecord.date >= date_from)
        if date_to:
            q = q.filter(CashRecord.date <= date_to)

        total_uzs = 0.0
        total_usd = 0.0

        for r in q.all():
            if r.currency == "USD":
                total_usd += r.amount
            else:  # default UZS
                total_uzs += r.amount

        return total_uzs, total_usd

    def today_totals(self):
        today = date.today()
        return self.totals(date_from=today, date_to=today)
