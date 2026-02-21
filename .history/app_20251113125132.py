from flask import (
    Flask, request, redirect, url_for, session,
    render_template, Response, send_file
)
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import date
from jinja2 import DictLoader
from difflib import SequenceMatcher
from io import StringIO, BytesIO
import csv
import qrcode

app = Flask(__name__)
app.secret_key = "change_this_secret_key_to_something_random"

LOW_STOCK_THRESHOLD = 5  # below this quantity row will be highlighted


# ---------- DATABASE HELPERS ----------

def get_db():
    conn = sqlite3.connect("fabric.db")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    # Users table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        )
    """)

    # Fabrics table (base)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS fabrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            color TEXT,
            unit TEXT NOT NULL,
            quantity REAL NOT NULL,
            price_per_unit REAL
        )
    """)

    # Cuts / usage log
    cur.execute("""
        CREATE TABLE IF NOT EXISTS cuts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fabric_id INTEGER NOT NULL,
            used_amount REAL NOT NULL,
            cut_date TEXT NOT NULL,
            FOREIGN KEY (fabric_id) REFERENCES fabrics(id)
        )
    """)

    # Add column "category" if missing
    cur.execute("PRAGMA table_info(fabrics)")
    cols = [row[1] for row in cur.fetchall()]
    if "category" not in cols:
        cur.execute("ALTER TABLE fabrics ADD COLUMN category TEXT")

    # Default user
    cur.execute("SELECT * FROM users WHERE username = ?", ("admin",))
    user = cur.fetchone()
    if user is None:
        cur.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            ("admin", generate_password_hash("admin123"))
        )
        print("Created default user: admin / admin123")

    conn.commit()
    conn.close()


# ---------- TRANSLATIONS (RU / UZ) ----------

translations = {
    "ru": {
        "app_title": "Учёт ткани",
        "menu_dashboard": "Главная",
        "menu_fabrics": "Ткани",
        "menu_logout": "Выйти",
        "lang_ru": "RU",
        "lang_uz": "UZ",

        "login_title": "Вход",
        "login_username": "Логин",
        "login_password": "Пароль",
        "login_button": "Войти",
        "login_default_user": "Стандартный пользователь: admin / admin123",

        "dashboard_title": "Панель",
        "dashboard_welcome": "Добро пожаловать! Используйте меню для управления тканями.",

        "fabrics_title": "Ткани",
        "current_fabrics": "Текущие ткани",
        "table_id": "ID",
        "table_name": "Название",
        "table_color": "Цвет",
        "table_unit": "Ед. изм.",
        "table_quantity": "Количество",
        "table_price_per_unit": "Цена / ед.",
        "table_category": "Категория",
        "table_actions": "Действия",

        "cut_button": "Списать",
        "cut_placeholder": "Сколько списать",
        "delete_button": "Удалить",
        "delete_confirm": "Вы уверены, что хотите удалить эту ткань?",
        "qr_label": "QR",

        "add_fabric": "Добавить новую ткань",
        "add_name": "Название",
        "add_color": "Цвет",
        "add_unit": "Ед. изм. (например, kg или m)",
        "add_quantity": "Количество",
        "add_price_per_unit": "Цена за единицу",
        "add_category": "Категория (например, хлопок, подкладка)",
        "add_button": "Добавить ткань",

        "last_cuts": "Последние списания",
        "last_cuts_date": "Дата",
        "last_cuts_fabric": "Ткань",
        "last_cuts_used_amount": "Списанное количество",

        "search_placeholder": "Поиск по названию или цвету",
        "filter_category": "Категория",
        "all_categories": "Все категории",
        "sort_label": "Сортировать",
        "sort_name": "По названию",
        "sort_quantity": "По количеству",
        "sort_price": "По цене",
        "export_csv": "Экспорт в Excel (CSV)",
        "low_stock_warning": "Внимание: есть ткани с малым остатком",
        "low_stock_badge": "Мало",

        "error_wrong_credentials": "Неверный логин или пароль.",
        "error_fabric_not_found": "Ткань не найдена.",
        "error_used_amount_positive": "Количество должно быть больше нуля.",
        "error_used_amount_too_much": "Нельзя списать больше, чем есть.",

        "merge_title": "Похоже, такая ткань уже есть",
        "merge_found_similar": "Найдена похожая ткань. Объединить количество или создать новую запись?",
        "merge_existing_fabric": "Существующая ткань",
        "merge_new_fabric": "Новая ткань (вы ввели)",
        "merge_button_yes": "Да, объединить",
        "merge_button_no_new": "Создать как новую",
    },
    "uz": {
        "app_title": "Mato ombori",
        "menu_dashboard": "Asosiy",
        "menu_fabrics": "Matolar",
        "menu_logout": "Chiqish",
        "lang_ru": "RU",
        "lang_uz": "UZ",

        "login_title": "Kirish",
        "login_username": "Login",
        "login_password": "Parol",
        "login_button": "Kirish",
        "login_default_user": "Standart foydalanuvchi: admin / admin123",

        "dashboard_title": "Bosh sahifa",
        "dashboard_welcome": "Xush kelibsiz! Matolarni boshqarish uchun menyudan foydalaning.",

        "fabrics_title": "Matolar",
        "current_fabrics": "Joriy matolar",
        "table_id": "ID",
        "table_name": "Nomi",
        "table_color": "Rangi",
        "table_unit": "O‘lchov birligi",
        "table_quantity": "Miqdori",
        "table_price_per_unit": "Narx / birlik",
        "table_category": "Kategoriya",
        "table_actions": "Harakatlar",

        "cut_button": "Kesish / ishlatish",
        "cut_placeholder": "Qancha ishlatish",
        "delete_button": "O‘chirish",
        "delete_confirm": "Haqiqatan ham bu matoni o‘chirmoqchimisiz?",
        "qr_label": "QR",

        "add_fabric": "Yangi mato qo‘shish",
        "add_name": "Nomi",
        "add_color": "Rangi",
        "add_unit": "O‘lchov birligi (masalan, kg yoki m)",
        "add_quantity": "Miqdori",
        "add_price_per_unit": "Bir birlik narxi",
        "add_category": "Kategoriya (masalan, paxta, podkladka)",
        "add_button": "Mato qo‘shish",

        "last_cuts": "Oxirgi kesishlar",
        "last_cuts_date": "Sana",
        "last_cuts_fabric": "Mato",
        "last_cuts_used_amount": "Ishlatilgan miqdor",

        "search_placeholder": "Nomi yoki rangi bo‘yicha qidirish",
        "filter_category": "Kategoriya",
        "all_categories": "Barcha kategoriyalar",
        "sort_label": "Saralash",
        "sort_name": "Nomi bo‘yicha",
        "sort_quantity": "Miqdori bo‘yicha",
        "sort_price": "Narx bo‘yicha",
        "export_csv": "Excel (CSV) ga eksport",
        "low_stock_warning": "Diqqat: ba’zi matolarda qoldiq kam",
        "low_stock_badge": "Kam",

        "error_wrong_credentials": "Login yoki parol noto‘g‘ri.",
        "error_fabric_not_found": "Mato topilmadi.",
        "error_used_amount_positive": "Miqdor noldan katta bo‘lishi kerak.",
        "error_used_amount_too_much": "Boridan ko‘p ishlatib bo‘lmaydi.",

        "merge_title": "O‘xshash mato topildi",
        "merge_found_similar": "O‘xshash mato topildi. Miqdorni qo‘shib yuboramizmi yoki yangi yozuv yaratamizmi?",
        "merge_existing_fabric": "Mavjud mato",
        "merge_new_fabric": "Yangi mato (siz kiritdingiz)",
        "merge_button_yes": "Ha, qo‘shib yuborish",
        "merge_button_no_new": "Yangi yozuv yaratish",
    }
}


def t(key: str) -> str:
    lang = session.get("lang", "ru")
    if lang not in translations:
        lang = "ru"
    return translations[lang].get(key, key)


app.jinja_env.globals["t"] = t
app.jinja_env.globals["LOW_STOCK_THRESHOLD"] = LOW_STOCK_THRESHOLD


def string_similarity(a: str, b: str) -> float:
    a = (a or "").strip().lower()
    b = (b or "").strip().lower()
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


# ---------- AUTH DECORATOR ----------

def login_required(view_func):
    from functools import wraps

    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return view_func(*args, **kwargs)

    return wrapper


# ---------- HTML TEMPLATES ----------

layout_html = """
<!doctype html>
<html>
<head>
    <meta charset="utf-8">
    <title>{{ t('app_title') }}</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 0; padding: 0; }
        .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
        nav a { margin-right: 10px; }
        .error { color: red; }
        table { border-collapse: collapse; width: 100%%; margin-top: 10px; }
        th, td { border: 1px solid #ccc; padding: 6px; text-align: left; }
        form { margin-top: 10px; }
        input[type=text], input[type=number], input[type=password] {
            padding: 5px;
            width: 250px;
            max-width: 100%%;
        }
        input[type=submit], button {
            padding: 6px 12px;
            cursor: pointer;
        }
        .lang-switch {
            float: right;
        }
        .low-stock { background-color: #ffe5e5; }
        .badge-low { background-color: #ff6666; color: white; padding: 2px 6px; border-radius: 4px; font-size: 11px; }
        .top-bar { display: flex; justify-content: space-between; align-items: center; }
        .top-bar nav { flex: 1; }
        .top-bar .lang-switch { flex-shrink: 0; }
        @media (max-width: 768px) {
            table, thead, tbody, th, td, tr { font-size: 12px; }
            .top-bar { flex-direction: column; align-items: flex-start; }
            .lang-switch { margin-top: 8px; float: none; }
        }
    </style>
</head>
<body>
<div class="container">
    <div class="top-bar">
        <nav>
            {% if session.get('user_id') %}
                <a href="{{ url_for('dashboard') }}">{{ t('menu_dashboard') }}</a>
                <a href="{{ url_for('fabrics') }}">{{ t('menu_fabrics') }}</a>
                <a href="{{ url_for('logout') }}">{{ t('menu_logout') }}</a>
            {% endif %}
        </nav>
        <div class="lang-switch">
            <a href="{{ url_for('set_lang', lang='ru') }}">{{ t('lang_ru') }}</a> |
            <a href="{{ url_for('set_lang', lang='uz') }}">{{ t('lang_uz') }}</a>
        </div>
    </div>
    <hr>
    {% block content %}{% endblock %}
</div>
</body>
</html>
"""

login_html = """
{% extends "layout.html" %}
{% block content %}
<h2>{{ t('login_title') }}</h2>
{% if error %}
    <p class="error">{{ t(error) }}</p>
{% endif %}
<form method="post">
    <p>
        <label>{{ t('login_username') }}:<br>
        <input type="text" name="username" required></label>
    </p>
    <p>
        <label>{{ t('login_password') }}:<br>
        <input type="password" name="password" required></label>
    </p>
    <p><input type="submit" value="{{ t('login_button') }}"></p>
</form>
<p><b>{{ t('login_default_user') }}</b></p>
{% endblock %}
"""

dashboard_html = """
{% extends "layout.html" %}
{% block content %}
<h2>{{ t('dashboard_title') }}</h2>
<p>{{ t('dashboard_welcome') }}</p>
{% endblock %}
"""

fabrics_html = """
{% extends "layout.html" %}
{% block content %}
<h2>{{ t('fabrics_title') }}</h2>

{% if any_low_stock %}
<p style="color:#c00; font-weight:bold;">{{ t('low_stock_warning') }}</p>
{% endif %}

<form method="get" action="{{ url_for('fabrics') }}">
    <input type="text" name="q" placeholder="{{ t('search_placeholder') }}" value="{{ q }}">
    <label>{{ t('filter_category') }}:
        <select name="category">
            <option value="">{{ t('all_categories') }}</option>
            {% for cat in categories %}
                <option value="{{ cat }}" {% if selected_category == cat %}selected{% endif %}>{{ cat }}</option>
            {% endfor %}
        </select>
    </label>
    <label>{{ t('sort_label') }}:
        <select name="sort">
            <option value="name" {% if sort == 'name' %}selected{% endif %}>{{ t('sort_name') }}</option>
            <option value="qty" {% if sort == 'qty' %}selected{% endif %}>{{ t('sort_quantity') }}</option>
            <option value="price" {% if sort == 'price' %}selected{% endif %}>{{ t('sort_price') }}</option>
        </select>
    </label>
    <input type="submit" value="OK">
    <a href="{{ url_for('export_fabrics') }}">{{ t('export_csv') }}</a>
</form>

<h3>{{ t('current_fabrics') }}</h3>
<table>
    <tr>
        <th>{{ t('table_id') }}</th>
        <th>{{ t('table_name') }}</th>
        <th>{{ t('table_color') }}</th>
        <th>{{ t('table_unit') }}</th>
        <th>{{ t('table_quantity') }}</th>
        <th>{{ t('table_price_per_unit') }}</th>
        <th>{{ t('table_category') }}</th>
        <th>{{ t('qr_label') }}</th>
        <th>{{ t('table_actions') }}</th>
    </tr>
    {% for fab in fabrics %}
    <tr class="{% if fab.quantity < LOW_STOCK_THRESHOLD %}low-stock{% endif %}">
        <td>{{ fab.id }}</td>
        <td>
            {{ fab.name }}
            {% if fab.quantity < LOW_STOCK_THRESHOLD %}
                <span class="badge-low">{{ t('low_stock_badge') }}</span>
            {% endif %}
        </td>
        <td>{{ fab.color or "" }}</td>
        <td>{{ fab.unit }}</td>
        <td>{{ "%.2f"|format(fab.quantity) }}</td>
        <td>{% if fab.price_per_unit is not none %}{{ "%.2f"|format(fab.price_per_unit) }}{% endif %}</td>
        <td>{{ fab.category or "" }}</td>
        <td>
            <img src="{{ url_for('fabric_qrcode', fabric_id=fab.id) }}" alt="QR" width="60">
        </td>
        <td>
            <form method="post" action="{{ url_for('cut_fabric', fabric_id=fab.id) }}" style="display:inline-block;">
                <input type="number" name="used_amount" step="0.01" min="0"
                       placeholder="{{ t('cut_placeholder') }}" required>
                <input type="submit" value="{{ t('cut_button') }}">
            </form>
            <form method="post" action="{{ url_for('delete_fabric', fabric_id=fab.id) }}" style="display:inline-block;"
                  onsubmit="return confirm('{{ t('delete_confirm') }}');">
                <input type="submit" value="{{ t('delete_button') }}">
            </form>
        </td>
    </tr>
    {% endfor %}
</table>

<h3>{{ t('add_fabric') }}</h3>
<form method="post" action="{{ url_for('add_fabric') }}">
    <p>
        <label>{{ t('add_name') }}:<br>
        <input type="text" name="name" required></label>
    </p>
    <p>
        <label>{{ t('add_color') }}:<br>
        <input type="text" name="color"></label>
    </p>
    <p>
        <label>{{ t('add_unit') }}:<br>
        <input type="text" name="unit" value="kg" required></label>
    </p>
    <p>
        <label>{{ t('add_quantity') }}:<br>
        <input type="number" name="quantity" step="0.01" min="0" required></label>
    </p>
    <p>
        <label>{{ t('add_price_per_unit') }}:<br>
        <input type="number" name="price_per_unit" step="0.01" min="0"></label>
    </p>
    <p>
        <label>{{ t('add_category') }}:<br>
        <input type="text" name="category"></label>
    </p>
    <p><input type="submit" value="{{ t('add_button') }}"></p>
</form>

<h3>{{ t('last_cuts') }}</h3>
<table>
    <tr>
        <th>{{ t('last_cuts_date') }}</th>
        <th>{{ t('last_cuts_fabric') }}</th>
        <th>{{ t('last_cuts_used_amount') }}</th>
    </tr>
    {% for c in cuts %}
    <tr>
        <td>{{ c.cut_date }}</td>
        <td>{{ c.name }}</td>
        <td>{{ "%.2f"|format(c.used_amount) }} {{ c.unit }}</td>
    </tr>
    {% endfor %}
</table>

{% if error %}
    <p class="error">{{ t(error) }}</p>
{% endif %}

{% endblock %}
"""

merge_confirm_html = """
{% extends "layout.html" %}
{% block content %}
<h2>{{ t('merge_title') }}</h2>
<p>{{ t('merge_found_similar') }}</p>

<h3>{{ t('merge_existing_fabric') }}</h3>
<table>
    <tr>
        <th>{{ t('table_name') }}</th>
        <th>{{ t('table_color') }}</th>
        <th>{{ t('table_unit') }}</th>
        <th>{{ t('table_quantity') }}</th>
        <th>{{ t('table_price_per_unit') }}</th>
        <th>{{ t('table_category') }}</th>
    </tr>
    <tr>
        <td>{{ existing.name }}</td>
        <td>{{ existing.color or "" }}</td>
        <td>{{ existing.unit }}</td>
        <td>{{ "%.2f"|format(existing.quantity) }}</td>
        <td>{% if existing.price_per_unit is not none %}{{ "%.2f"|format(existing.price_per_unit) }}{% endif %}</td>
        <td>{{ existing.category or "" }}</td>
    </tr>
</table>

<h3>{{ t('merge_new_fabric') }}</h3>
<table>
    <tr>
        <th>{{ t('table_name') }}</th>
        <th>{{ t('table_color') }}</th>
        <th>{{ t('table_unit') }}</th>
        <th>{{ t('table_quantity') }}</th>
        <th>{{ t('table_price_per_unit') }}</th>
        <th>{{ t('table_category') }}</th>
    </tr>
    <tr>
        <td>{{ new.name }}</td>
        <td>{{ new.color or "" }}</td>
        <td>{{ new.unit }}</td>
        <td>{{ "%.2f"|format(new.quantity) }}</td>
        <td>{% if new.price_per_unit is not none %}{{ "%.2f"|format(new.price_per_unit) }}{% endif %}</td>
        <td>{{ new.category or "" }}</td>
    </tr>
</table>

<form method="post" action="{{ url_for('merge_fabric') }}" style="display:inline-block; margin-top:15px; margin-right:10px;">
    <input type="hidden" name="existing_id" value="{{ existing.id }}">
    <input type="hidden" name="name" value="{{ new.name }}">
    <input type="hidden" name="color" value="{{ new.color }}">
    <input type="hidden" name="unit" value="{{ new.unit }}">
    <input type="hidden" name="quantity" value="{{ new.quantity }}">
    <input type="hidden" name="price_per_unit" value="{{ new.price_per_unit if new.price_per_unit is not none else '' }}">
    <input type="hidden" name="category" value="{{ new.category }}">
    <input type="submit" value="{{ t('merge_button_yes') }}">
</form>

<form method="post" action="{{ url_for('create_new_fabric') }}" style="display:inline-block; margin-top:15px;">
    <input type="hidden" name="name" value="{{ new.name }}">
    <input type="hidden" name="color" value="{{ new.color }}">
    <input type="hidden" name="unit" value="{{ new.unit }}">
    <input type="hidden" name="quantity" value="{{ new.quantity }}">
    <input type="hidden" name="price_per_unit" value="{{ new.price_per_unit if new.price_per_unit is not none else '' }}">
    <input type="hidden" name="category" value="{{ new.category }}">
    <input type="submit" value="{{ t('merge_button_no_new') }}">
</form>

{% endblock %}
"""

app.jinja_loader = DictLoader({
    "layout.html": layout_html,
    "login.html": login_html,
    "dashboard.html": dashboard_html,
    "fabrics.html": fabrics_html,
    "merge_confirm.html": merge_confirm_html,
})


# ---------- LANGUAGE SWITCH ----------

@app.route("/lang/<lang>")
def set_lang(lang):
    if lang not in ("ru", "uz"):
        lang = "ru"
    session["lang"] = lang
    ref = request.referrer
    if ref:
        return redirect(ref)
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


# ---------- AUTH ROUTES ----------

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]

        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE username = ?", (username,))
        user = cur.fetchone()
        conn.close()

        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            return redirect(url_for("dashboard"))
        else:
            error = "error_wrong_credentials"

    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def dashboard():
    return render_template("dashboard.html")


# ---------- FABRICS LIST + SEARCH/SORT/FILTER ----------

@app.route("/fabrics")
@login_required
def fabrics():
    q = request.args.get("q", "").strip()
    category_filter = request.args.get("category", "").strip()
    sort = request.args.get("sort", "name")

    conn = get_db()
    cur = conn.cursor()

    # categories for dropdown
    cur.execute("""
        SELECT DISTINCT category FROM fabrics
        WHERE category IS NOT NULL AND TRIM(category) <> ''
        ORDER BY category
    """)
    categories = [row["category"] for row in cur.fetchall()]

    base_sql = "SELECT * FROM fabrics WHERE 1=1"
    params = []

    if q:
        base_sql += " AND (LOWER(name) LIKE ? OR LOWER(color) LIKE ?)"
        like = f"%{q.lower()}%"
        params.extend([like, like])

    if category_filter:
        base_sql += " AND LOWER(COALESCE(category,'')) = LOWER(?)"
        params.append(category_filter)

    order_sql = " ORDER BY "
    if sort == "qty":
        order_sql += "quantity DESC"
    elif sort == "price":
        order_sql += "price_per_unit DESC"
    else:
        order_sql += "name ASC"

    cur.execute(base_sql + order_sql, params)
    fabrics_list = cur.fetchall()

    any_low_stock = any(f["quantity"] < LOW_STOCK_THRESHOLD for f in fabrics_list)

    cur.execute("""
        SELECT cuts.cut_date, cuts.used_amount, fabrics.name, fabrics.unit
        FROM cuts
        JOIN fabrics ON cuts.fabric_id = fabrics.id
        ORDER BY cuts.id DESC
        LIMIT 10
    """)
    cuts_list = cur.fetchall()

    conn.close()
    return render_template(
        "fabrics.html",
        fabrics=fabrics_list,
        cuts=cuts_list,
        error=None,
        q=q,
        categories=categories,
        selected_category=category_filter,
        sort=sort,
        any_low_stock=any_low_stock,
    )


# ---------- ADD FABRIC (SMART MERGE + FUZZY SUGGEST) ----------

@app.route("/fabrics/add", methods=["POST"])
@login_required
def add_fabric():
    name = request.form["name"].strip()
    color = request.form.get("color", "").strip()
    unit = request.form["unit"].strip()
    quantity = float(request.form["quantity"])
    price_per_unit_raw = request.form.get("price_per_unit", "").strip()
    price_per_unit = float(price_per_unit_raw) if price_per_unit_raw else None
    category = request.form.get("category", "").strip()

    conn = get_db()
    cur = conn.cursor()

    # 1) Exact merge: same name+color+unit (case-insensitive)
    cur.execute("""
        SELECT * FROM fabrics
        WHERE LOWER(name) = LOWER(?)
          AND LOWER(COALESCE(color, '')) = LOWER(?)
          AND LOWER(unit) = LOWER(?)
    """, (name, color, unit))
    existing = cur.fetchone()

    if existing:
        new_qty = existing["quantity"] + quantity
        if price_per_unit is not None:
            cur.execute("""
                UPDATE fabrics
                   SET quantity = ?, price_per_unit = ?, category = COALESCE(?, category)
                 WHERE id = ?
            """, (new_qty, price_per_unit, category if category else None, existing["id"]))
        else:
            cur.execute("""
                UPDATE fabrics
                   SET quantity = ?, category = COALESCE(?, category)
                 WHERE id = ?
            """, (new_qty, category if category else None, existing["id"]))
        conn.commit()
        conn.close()
        return redirect(url_for("fabrics"))

    # 2) No exact match → fuzzy similar with same unit
    cur.execute("""
        SELECT * FROM fabrics
        WHERE LOWER(unit) = LOWER(?)
    """, (unit,))
    candidates = cur.fetchall()

    best = None
    best_score = 0.0

    for row in candidates:
        name_score = string_similarity(name, row["name"])
        color_score = string_similarity(color, row["color"] or "")
        total_score = 0.7 * name_score + 0.3 * color_score
        if total_score > best_score:
            best_score = total_score
            best = row

    conn.close()

    if best is not None and best_score >= 0.8:
        new_obj = {
            "name": name,
            "color": color,
            "unit": unit,
            "quantity": quantity,
            "price_per_unit": price_per_unit,
            "category": category,
        }
        return render_template("merge_confirm.html", existing=best, new=new_obj)

    # 3) No similar → create new
    return create_new_fabric_internal(name, color, unit, quantity, price_per_unit, category)


def create_new_fabric_internal(name, color, unit, quantity, price_per_unit, category):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO fabrics (name, color, unit, quantity, price_per_unit, category)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (name, color, unit, quantity, price_per_unit, category))
    conn.commit()
    conn.close()
    return redirect(url_for("fabrics"))


@app.route("/fabrics/merge", methods=["POST"])
@login_required
def merge_fabric():
    existing_id = int(request.form["existing_id"])
    quantity = float(request.form["quantity"])
    price_per_unit_raw = request.form.get("price_per_unit", "").strip()
    price_per_unit = float(price_per_unit_raw) if price_per_unit_raw else None
    category = request.form.get("category", "").strip()

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM fabrics WHERE id = ?", (existing_id,))
    existing = cur.fetchone()

    if not existing:
        conn.close()
        return redirect(url_for("fabrics"))

    new_qty = existing["quantity"] + quantity
    if price_per_unit is not None:
        cur.execute("""
            UPDATE fabrics
               SET quantity = ?, price_per_unit = ?, category = COALESCE(?, category)
             WHERE id = ?
        """, (new_qty, price_per_unit, category if category else None, existing_id))
    else:
        cur.execute("""
            UPDATE fabrics
               SET quantity = ?, category = COALESCE(?, category)
             WHERE id = ?
        """, (new_qty, category if category else None, existing_id))

    conn.commit()
    conn.close()
    return redirect(url_for("fabrics"))


@app.route("/fabrics/create_new", methods=["POST"])
@login_required
def create_new_fabric():
    name = request.form["name"].strip()
    color = request.form.get("color", "").strip()
    unit = request.form["unit"].strip()
    quantity = float(request.form["quantity"])
    price_per_unit_raw = request.form.get("price_per_unit", "").strip()
    price_per_unit = float(price_per_unit_raw) if price_per_unit_raw else None
    category = request.form.get("category", "").strip()
    return create_new_fabric_internal(name, color, unit, quantity, price_per_unit, category)


# ---------- CUT / DELETE / QR / EXPORT ----------

@app.route("/fabrics/<int:fabric_id>/cut", methods=["POST"])
@login_required
def cut_fabric(fabric_id):
    try:
        used_amount = float(request.form["used_amount"])
    except ValueError:
        used_amount = -1

    error = None
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM fabrics WHERE id = ?", (fabric_id,))
    fabric = cur.fetchone()

    if not fabric:
        conn.close()
        error = "error_fabric_not_found"
    elif used_amount <= 0:
        conn.close()
        error = "error_used_amount_positive"
    elif used_amount > fabric["quantity"]:
        conn.close()
        error = "error_used_amount_too_much"
    else:
        new_qty = fabric["quantity"] - used_amount
        cur.execute("UPDATE fabrics SET quantity = ? WHERE id = ?",
                    (new_qty, fabric_id))
        cur.execute("""
            INSERT INTO cuts (fabric_id, used_amount, cut_date)
            VALUES (?, ?, ?)
        """, (fabric_id, used_amount, date.today().isoformat()))
        conn.commit()
        conn.close()

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM fabrics ORDER BY name ASC")
    fabrics_list = cur.fetchall()
    any_low_stock = any(f["quantity"] < LOW_STOCK_THRESHOLD for f in fabrics_list)
    cur.execute("""
        SELECT cuts.cut_date, cuts.used_amount, fabrics.name, fabrics.unit
        FROM cuts
        JOIN fabrics ON cuts.fabric_id = fabrics.id
        ORDER BY cuts.id DESC
        LIMIT 10
    """)
    cuts_list = cur.fetchall()
    conn.close()

    return render_template(
        "fabrics.html",
        fabrics=fabrics_list,
        cuts=cuts_list,
        error=error,
        q="",
        categories=[],
        selected_category="",
        sort="name",
        any_low_stock=any_low_stock,
    )


@app.route("/fabrics/<int:fabric_id>/delete", methods=["POST"])
@login_required
def delete_fabric(fabric_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM cuts WHERE fabric_id = ?", (fabric_id,))
    cur.execute("DELETE FROM fabrics WHERE id = ?", (fabric_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("fabrics"))


@app.route("/fabrics/<int:fabric_id>/qrcode")
@login_required
def fabric_qrcode(fabric_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM fabrics WHERE id = ?", (fabric_id,))
    fabric = cur.fetchone()
    conn.close()

    if not fabric:
        return "Not found", 404

    text = f"Fabric #{fabric['id']}\nName: {fabric['name']}\nColor: {fabric['color']}\nUnit: {fabric['unit']}\nQty: {fabric['quantity']}\nCategory: {fabric['category']}"
    img = qrcode.make(text)
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


@app.route("/fabrics/export")
@login_required
def export_fabrics():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, name, color, unit, quantity, price_per_unit, category
        FROM fabrics
        ORDER BY name ASC
    """)
    rows = cur.fetchall()
    conn.close()

    si = StringIO()
    writer = csv.writer(si)
    writer.writerow(["ID", "Name", "Color", "Unit", "Quantity", "PricePerUnit", "Category"])
    for r in rows:
        writer.writerow([
            r["id"], r["name"], r["color"], r["unit"],
            r["quantity"], r["price_per_unit"], r["category"]
        ])

    output = si.getvalue().encode("utf-8-sig")
    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=fabrics.csv"}
    )


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
