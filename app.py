# -*- coding: utf-8 -*-
"""
СпецТех — финальная сборка (Render-ready).
- Регистрация по телефону + код (демо SMS в last_otp.txt)
- Продавцы добавляют товары, у каждого товара: изображение, цена, бренд, категория,
  номер телефона для звонка, переключатели: WhatsApp и Позвонить
- Кнопки WhatsApp (wa.me) и Позвонить (tel:) на карточке товара
- Админ-панель: вход /admin (admin / admin123)
  * Глобальные настройки: включить/выключить WhatsApp и «Позвонить», название сайта, загрузка логотипа
  * Баннеры: верх/низ — загрузка картинки, ссылка, включить/выключить
  * Управление: удалить/редактировать товары, бренды и категории
Все изображения хранятся в static/ (uploads, banners, logo), что подходит для Render.
"""
import os, sqlite3, random, re
from datetime import datetime, timezone, timedelta
from functools import wraps
from flask import Flask, g, render_template, request, redirect, url_for, session, flash
from werkzeug.utils import secure_filename

APP_DEFAULT_TITLE = "СпецТех"
DB_PATH = "data.sqlite"
STATIC_UPLOADS = "static/uploads"
STATIC_BANNERS = "static/banners"
STATIC_LOGO = "static/logo"
ALLOWED_IMG = {"png","jpg","jpeg","webp"}

app = Flask(__name__)
app.config["SECRET_KEY"] = "changeme_render_secret"

for d in (STATIC_UPLOADS, STATIC_BANNERS, STATIC_LOGO):
    os.makedirs(d, exist_ok=True)

def nowiso(): return datetime.now(timezone.utc).isoformat()

# -------- DB helpers --------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, timeout=5)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None: db.close()

def col_exists(table, col):
    cur = get_db().execute(f"PRAGMA table_info({table})")
    return any(r[1]==col for r in cur.fetchall())

def create_schema_and_seed():
    db = get_db()
    db.executescript("""
    PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        phone TEXT UNIQUE NOT NULL,
        name TEXT,
        whatsapp TEXT,
        is_verified INTEGER DEFAULT 0,
        is_blocked INTEGER DEFAULT 0,
        is_admin INTEGER DEFAULT 0,
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS otps(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        phone TEXT,
        code TEXT,
        expires_at TEXT,
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS categories(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE
    );
    CREATE TABLE IF NOT EXISTS brands(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE
    );
    CREATE TABLE IF NOT EXISTS listings(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT,
        brand_id INTEGER,
        category_id INTEGER,
        price REAL,
        image TEXT,
        created_at TEXT,
        user_id INTEGER,
        seller_phone TEXT,
        whatsapp_enabled INTEGER DEFAULT 1,
        call_enabled INTEGER DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS banners(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pos TEXT, -- 'top' or 'bottom'
        enabled INTEGER DEFAULT 0,
        image TEXT,
        url TEXT
    );
    CREATE TABLE IF NOT EXISTS settings(
        key TEXT PRIMARY KEY,
        val TEXT
    );
    """)
    # defaults
    db.execute("INSERT OR IGNORE INTO settings(key,val) VALUES('site_title',?)", (APP_DEFAULT_TITLE,))
    db.execute("INSERT OR IGNORE INTO settings(key,val) VALUES('logo_file','logo.png')")
    db.execute("INSERT OR IGNORE INTO settings(key,val) VALUES('whatsapp_global','1')")
    db.execute("INSERT OR IGNORE INTO settings(key,val) VALUES('allow_calls','1')")
    # base dicts
    for name in ("Шасси","Подъёмник","Сиденье","Двигатель","Тормоза"):
        db.execute("INSERT OR IGNORE INTO categories(name) VALUES(?)", (name,))
    for name in ("Shacman","Howo","Sinotruk","XCMG","Foton","DongFeng"):
        db.execute("INSERT OR IGNORE INTO brands(name) VALUES(?)", (name,))
    # seed users & listings only if empty
    if db.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]==0:
        db.execute("INSERT OR IGNORE INTO users(phone,name,whatsapp,is_verified,is_admin,created_at) VALUES (?,?,?,?,1,?)",
                   ("+992900000000","Админ","+992900000000",1, nowiso()))
        db.execute("INSERT OR IGNORE INTO users(phone,name,whatsapp,is_verified,created_at) VALUES (?,?,?,?,?)",
                   ("+992911111111","Продавец","+992911111111",1, nowiso()))
    if db.execute("SELECT COUNT(*) c FROM listings").fetchone()["c"]==0:
        seller_id = db.execute("SELECT id FROM users WHERE phone=?",( "+992911111111",)).fetchone()["id"]
        bid = lambda name: db.execute("SELECT id FROM brands WHERE name=?", (name,)).fetchone()["id"]
        cid = lambda name: db.execute("SELECT id FROM categories WHERE name=?", (name,)).fetchone()["id"]
        demo = [
            ("Фара Shacman F3000","Оригинал, гарантия 6 мес.", bid("Shacman"), cid("Шасси"), 1450, "sample1.png"),
            ("Тормозные колодки Howo","Комплект 4 шт.", bid("Howo"), cid("Тормоза"), 380, "sample2.png"),
            ("Фильтр масляный Sinotruk","Высокое качество", bid("Sinotruk"), cid("Двигатель"), 120, "sample3.png"),
        ]
        for t,d,br,ct,price,img in demo:
            db.execute("""INSERT INTO listings(title,description,brand_id,category_id,price,image,created_at,user_id,
                      seller_phone, whatsapp_enabled, call_enabled)
                      VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                      (t,d,br,ct,price,img, nowiso(), seller_id, "+992911111111",1,1))
        db.execute("INSERT OR IGNORE INTO banners(pos,enabled,image,url) VALUES('top',1,'top_demo.png','https://example.com')")
        db.execute("INSERT OR IGNORE INTO banners(pos,enabled,image,url) VALUES('bottom',1,'bottom_demo.png','https://example.com')")
    # migrations if old db
    if not col_exists("listings","whatsapp_enabled"):
        db.execute("ALTER TABLE listings ADD COLUMN whatsapp_enabled INTEGER DEFAULT 1")
    if not col_exists("listings","call_enabled"):
        db.execute("ALTER TABLE listings ADD COLUMN call_enabled INTEGER DEFAULT 1")
    if not col_exists("listings","seller_phone"):
        db.execute("ALTER TABLE listings ADD COLUMN seller_phone TEXT")
    if not col_exists("users","whatsapp"):
        db.execute("ALTER TABLE users ADD COLUMN whatsapp TEXT")
    db.commit()

@app.before_request
def boot():
    create_schema_and_seed()

# -------- Context --------
def ctx_user():
    if "user_id" in session:
        return get_db().execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
    return None

@app.context_processor
def inject():
    db = get_db()
    settings = {r["key"]: r["val"] for r in db.execute("SELECT key,val FROM settings").fetchall()}
    top = db.execute("SELECT * FROM banners WHERE pos='top'").fetchone()
    bottom = db.execute("SELECT * FROM banners WHERE pos='bottom'").fetchone()
    logo = settings.get("logo_file","logo.png")
    return dict(APP_TITLE=settings.get("site_title", APP_DEFAULT_TITLE),
                user=ctx_user(), settings=settings,
                top_banner=top, bottom_banner=bottom, logo_file=logo)

# -------- Auth (phone + demo OTP) --------
def send_sms_demo(phone, code):
    msg = f"[DEMO SMS] Код: {code} для {phone}"
    print(msg)
    try:
        with open("last_otp.txt","w",encoding="utf-8") as f: f.write(msg)
    except Exception: pass

@app.route("/auth", methods=["GET","POST"])
def auth_start():
    if request.method=="POST":
        phone = request.form["phone"].strip()
        if not phone: 
            flash("Введите номер"); return redirect(url_for("auth_start"))
        db = get_db()
        u = db.execute("SELECT * FROM users WHERE phone=?", (phone,)).fetchone()
        if not u:
            db.execute("INSERT INTO users(phone,is_verified,created_at) VALUES (?,?,?)",(phone,0,nowiso())); db.commit()
        code = f"{random.randint(0,999999):06d}"
        exp = datetime.now(timezone.utc)+timedelta(minutes=5)
        db.execute("INSERT INTO otps(phone,code,expires_at,created_at) VALUES (?,?,?,?)",(phone,code,exp.isoformat(),nowiso())); db.commit()
        session["pending_phone"]=phone
        send_sms_demo(phone, code)
        flash("Код отправлен (смотри last_otp.txt рядом с приложением).")
        return redirect(url_for("auth_verify"))
    return render_template("auth_start.html")

@app.route("/auth/verify", methods=["GET","POST"])
def auth_verify():
    phone = session.get("pending_phone")
    if not phone: return redirect(url_for("auth_start"))
    if request.method=="POST":
        code = request.form["code"].strip()
        db = get_db()
        otp = db.execute("SELECT * FROM otps WHERE phone=? ORDER BY id DESC LIMIT 1",(phone,)).fetchone()
        if not otp or otp["code"]!=code: flash("Неверный код"); return redirect(url_for("auth_verify"))
        if datetime.fromisoformat(otp["expires_at"])<datetime.now(timezone.utc): flash("Код истёк"); return redirect(url_for("auth_start"))
        u = db.execute("SELECT * FROM users WHERE phone=?", (phone,)).fetchone()
        db.execute("UPDATE users SET is_verified=1 WHERE id=?", (u["id"],)); db.commit()
        session["user_id"]=u["id"]; session.pop("pending_phone",None)
        return redirect(url_for("profile"))
    return render_template("auth_verify.html", phone=phone)

@app.route("/logout")
def logout(): session.clear(); return redirect(url_for("index"))

# -------- Profile --------
@app.route("/profile", methods=["GET","POST"])
def profile():
    if not ctx_user(): return redirect(url_for("auth_start", next=request.path))
    db = get_db()
    u = ctx_user()
    if request.method=="POST":
        name = request.form.get("name","").strip()
        whatsapp = request.form.get("whatsapp","").strip()
        db.execute("UPDATE users SET name=?, whatsapp=? WHERE id=?", (name,whatsapp,u["id"])); db.commit()
        flash("Профиль сохранён")
        return redirect(url_for("profile"))
    return render_template("profile.html", u=u)

# -------- Catalog --------
@app.route("/")
def index():
    q = request.args.get("q","").strip()
    brand_id = request.args.get("brand","").strip()
    cat_id = request.args.get("category","").strip()
    db = get_db()
    sql = """SELECT l.*, b.name as brand_name, c.name as cat_name, u.name as seller_name, u.whatsapp as seller_whatsapp
             FROM listings l 
             LEFT JOIN brands b ON b.id=l.brand_id
             LEFT JOIN categories c ON c.id=l.category_id
             LEFT JOIN users u ON u.id=l.user_id
             WHERE 1=1"""
    args = []
    if q:
        sql += " AND (l.title LIKE ? OR l.description LIKE ?)"; like = f"%{q}%"; args += [like, like]
    if brand_id: sql += " AND l.brand_id=?"; args.append(brand_id)
    if cat_id: sql += " AND l.category_id=?"; args.append(cat_id)
    sql += " ORDER BY l.id DESC"
    rows = db.execute(sql,args).fetchall()
    brands = db.execute("SELECT * FROM brands ORDER BY name").fetchall()
    cats = db.execute("SELECT * FROM categories ORDER BY name").fetchall()
    return render_template("index.html", rows=rows, q=q, brand_id=brand_id, cat_id=cat_id, brands=brands, categories=cats)

@app.route("/listing/<int:lid>")
def listing_detail(lid):
    db = get_db()
    row = db.execute("""SELECT l.*, b.name as brand_name, c.name as cat_name, u.id as seller_id, u.name as seller_name, u.whatsapp as seller_whatsapp 
                        FROM listings l 
                        LEFT JOIN brands b ON b.id=l.brand_id
                        LEFT JOIN categories c ON c.id=l.category_id
                        LEFT JOIN users u ON u.id=l.user_id
                        WHERE l.id=?""",(lid,)).fetchone()
    if not row: return "Not found", 404
    settings = {r["key"]: r["val"] for r in db.execute("SELECT key,val FROM settings").fetchall()}
    wa_on = settings.get("whatsapp_global","1")=="1" and row["whatsapp_enabled"]==1 and row["seller_whatsapp"]
    call_on = settings.get("allow_calls","1")=="1" and row["call_enabled"]==1 and row["seller_phone"]
    return render_template("listing_detail.html", row=row, wa_on=wa_on, call_on=call_on)

# Images saved to static/uploads
def save_image(file_storage, prefix="img"):
    if not file_storage or not file_storage.filename: return None
    ext = file_storage.filename.rsplit(".",1)[-1].lower()
    if ext not in ALLOWED_IMG: return None
    name = secure_filename(file_storage.filename).rsplit(".",1)[0]
    fname = f"{prefix}_{int(datetime.now().timestamp())}_{name}.{ext}"
    path = os.path.join(STATIC_UPLOADS, fname)
    file_storage.save(path)
    return fname

# -------- Add/Edit listing --------
def login_required(f):
    @wraps(f)
    def wrap(*a,**k):
        if not ctx_user(): return redirect(url_for("auth_start", next=request.path))
        return f(*a,**k)
    return wrap

@app.route("/add", methods=["GET","POST"])
@login_required
def add_listing():
    db = get_db()
    if request.method=="POST":
        title = request.form["title"].strip()
        desc = request.form.get("description","").strip()
        brand_id = int(request.form.get("brand_id") or 0) or None
        cat_id = int(request.form.get("category_id") or 0) or None
        price = float(request.form.get("price") or 0)
        seller_phone = request.form.get("seller_phone","").strip()
        wa_enabled = 1 if request.form.get("whatsapp_enabled")=="on" else 0
        call_enabled = 1 if request.form.get("call_enabled")=="on" else 0
        img = save_image(request.files.get("image"), "prod") or "sample1.png"
        db.execute("""INSERT INTO listings(title,description,brand_id,category_id,price,image,created_at,user_id,seller_phone,whatsapp_enabled,call_enabled)
                      VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                   (title,desc,brand_id,cat_id,price,img,nowiso(),session["user_id"],seller_phone,wa_enabled,call_enabled))
        db.commit()
        flash("Товар добавлен")
        return redirect(url_for("index"))
    brands = db.execute("SELECT * FROM brands ORDER BY name").fetchall()
    cats = db.execute("SELECT * FROM categories ORDER BY name").fetchall()
    return render_template("add_listing.html", brands=brands, categories=cats)

@app.route("/edit/<int:lid>", methods=["GET","POST"])
@login_required
def edit_listing(lid):
    db=get_db()
    row=db.execute("SELECT * FROM listings WHERE id=?", (lid,)).fetchone()
    if not row: return "Not found",404
    u=ctx_user()
    if not (u["is_admin"]==1 or row["user_id"]==u["id"]):
        flash("Нет прав"); return redirect(url_for("index"))
    if request.method=="POST":
        title=request.form["title"].strip()
        desc=request.form.get("description","").strip()
        brand_id=int(request.form.get("brand_id") or 0) or None
        cat_id=int(request.form.get("category_id") or 0) or None
        price=float(request.form.get("price") or 0)
        seller_phone=request.form.get("seller_phone","").strip()
        wa_enabled=1 if request.form.get("whatsapp_enabled")=="on" else 0
        call_enabled=1 if request.form.get("call_enabled")=="on" else 0
        img=row["image"]
        f=request.files.get("image")
        new_img=save_image(f,"prod")
        if new_img: img=new_img
        db.execute("""UPDATE listings SET title=?,description=?,brand_id=?,category_id=?,price=?,image=?,seller_phone=?,whatsapp_enabled=?,call_enabled=? WHERE id=?""",
                   (title,desc,brand_id,cat_id,price,img,seller_phone,wa_enabled,call_enabled,lid))
        db.commit(); flash("Сохранено"); return redirect(url_for("listing_detail", lid=lid))
    brands=db.execute("SELECT * FROM brands ORDER BY name").fetchall()
    cats=db.execute("SELECT * FROM categories ORDER BY name").fetchall()
    return render_template("edit_listing.html", r=row, brands=brands, categories=cats)

# -------- Admin --------
def admin_required(f):
    @wraps(f)
    def wrap(*a,**k):
        if not session.get("admin_logged"):
            return redirect(url_for("admin_login", next=request.path))
        return f(*a,**k)
    return wrap

@app.route("/admin/login", methods=["GET","POST"])
def admin_login():
    if request.method=="POST":
        if request.form["login"]=="admin" and request.form["password"]=="admin123":
            session["admin_logged"]=True; return redirect(url_for("admin_dashboard"))
        flash("Неверные данные")
    return render_template("admin_login.html")

@app.route("/admin/logout")
def admin_logout(): session.pop("admin_logged",None); return redirect(url_for("admin_login"))

@app.route("/admin")
@admin_required
def admin_dashboard():
    db = get_db()
    counts = {
        "users": db.execute("SELECT COUNT(*) c FROM users").fetchone()["c"],
        "listings": db.execute("SELECT COUNT(*) c FROM listings").fetchone()["c"],
        "brands": db.execute("SELECT COUNT(*) c FROM brands").fetchone()["c"],
        "categories": db.execute("SELECT COUNT(*) c FROM categories").fetchone()["c"],
    }
    settings = {r["key"]: r["val"] for r in db.execute("SELECT key,val FROM settings").fetchall()}
    top = db.execute("SELECT * FROM banners WHERE pos='top'").fetchone()
    bottom = db.execute("SELECT * FROM banners WHERE pos='bottom'").fetchone()
    listings = db.execute("""SELECT l.id,l.title,l.price,b.name brand,c.name cat FROM listings l 
                             LEFT JOIN brands b ON b.id=l.brand_id
                             LEFT JOIN categories c ON c.id=l.category_id
                             ORDER BY l.id DESC LIMIT 50""").fetchall()
    brands = db.execute("SELECT * FROM brands ORDER BY name").fetchall()
    cats = db.execute("SELECT * FROM categories ORDER BY name").fetchall()
    return render_template("admin_dashboard.html", counts=counts, settings=settings, top=top, bottom=bottom, listings=listings, brands=brands, categories=cats)

@app.route("/admin/settings", methods=["POST"])
@admin_required
def admin_settings():
    db = get_db()
    title = request.form.get("site_title","").strip() or APP_DEFAULT_TITLE
    db.execute("INSERT OR REPLACE INTO settings(key,val) VALUES('site_title',?)", (title,))
    db.execute("INSERT OR REPLACE INTO settings(key,val) VALUES('whatsapp_global',?)", ("1" if request.form.get("whatsapp_global")=="on" else "0",))
    db.execute("INSERT OR REPLACE INTO settings(key,val) VALUES('allow_calls',?)", ("1" if request.form.get("allow_calls")=="on" else "0",))
    # logo upload
    f = request.files.get("logo")
    if f and "." in f.filename and f.filename.rsplit(".",1)[1].lower() in {"png","jpg","jpeg","webp"}:
        name = secure_filename(f.filename)
        fname = f"logo_{int(datetime.now().timestamp())}_{name}"
        f.save(os.path.join(STATIC_LOGO, fname))
        db.execute("INSERT OR REPLACE INTO settings(key,val) VALUES('logo_file',?)", (fname,))
    db.commit(); flash("Настройки сохранены")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/banner/<pos>", methods=["POST"])
@admin_required
def admin_banner(pos):
    enabled = 1 if request.form.get("enabled")=="on" else 0
    url = request.form.get("url","").strip()
    f = request.files.get("image")
    img = None
    if f and "." in f.filename and f.filename.rsplit(".",1)[1].lower() in ALLOWED_IMG:
        name = secure_filename(f.filename)
        fname = f"bn_{pos}_{int(datetime.now().timestamp())}_{name}"
        f.save(os.path.join(STATIC_BANNERS, fname)); img=fname
    db = get_db()
    row = db.execute("SELECT id FROM banners WHERE pos=?", (pos,)).fetchone()
    if row:
        if img: db.execute("UPDATE banners SET enabled=?, url=?, image=? WHERE id=?", (enabled,url,img,row["id"]))
        else: db.execute("UPDATE banners SET enabled=?, url=? WHERE id=?", (enabled,url,row["id"]))
    else:
        db.execute("INSERT INTO banners(pos,enabled,image,url) VALUES (?,?,?,?)", (pos,enabled,img or "",url))
    db.commit(); flash("Баннер сохранён"); return redirect(url_for("admin_dashboard"))

@app.route("/admin/listing/delete/<int:lid>", methods=["POST"])
@admin_required
def admin_delete_listing(lid):
    db = get_db()
    db.execute("DELETE FROM listings WHERE id=?", (lid,)); db.commit(); flash("Товар удалён")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/brand/add", methods=["POST"])
@admin_required
def admin_brand_add():
    name=request.form.get("brand_name","").strip()
    if name: 
        get_db().execute("INSERT OR IGNORE INTO brands(name) VALUES(?)",(name,)); get_db().commit()
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/category/add", methods=["POST"])
@admin_required
def admin_category_add():
    name=request.form.get("category_name","").strip()
    if name:
        get_db().execute("INSERT OR IGNORE INTO categories(name) VALUES(?)",(name,)); get_db().commit()
    return redirect(url_for("admin_dashboard"))

# -------- Errors --------
@app.errorhandler(500)
def e500(e): return render_template("error.html", msg="Ошибка сервера"), 500

# -------- Run --------
if __name__=="__main__":
    # локально: python app.py
    app.run(host="127.0.0.1", port=5000, debug=False)
