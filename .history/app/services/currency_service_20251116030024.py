import requests


CBU_USD_JSON_URL = "https://cbu.uz/ru/arkhiv-kursov-valyut/json/USD/"


def get_usd_uzs_rate() -> float | None:
    """
    Возвращает курс: 1 USD = X UZS по данным ЦБ Узбекистана.
    Если не удалось получить курс (нет интернета, ошибка), вернёт None.
    """
    try:
        resp = requests.get(CBU_USD_JSON_URL, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        if not data:
            return None

        last = data[-1]
        rate_str = last.get("Rate")
        nominal_str = last.get("Nominal") or "1"

        if not rate_str:
            return None

        # В API часто числа с запятой
        rate = float(str(rate_str).replace(",", "."))
        nominal = float(str(nominal_str).replace(",", ".")) or 1.0

        return rate / nominal  # курс за 1 USD
    except Exception:
        return None
