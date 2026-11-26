import streamlit as st
import requests
import sqlite3
import os
import io
import shutil
import pandas as pd
import re
import html
import json
import hashlib
import secrets
import uuid
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import quote

# ============================================================
# MOVIE REVIEW - CINEMA DARK
# Data: StreamX keyless API (Cinemeta, IMDb suggestion, TVmaze, AniList)
# IMPORTANT: enrich=0 is used to avoid Wikidata/Wikipedia enrichment.
# Storage: SQLite
# ============================================================

st.set_page_config(
    page_title="Movie Review | Discover · Review · Collect",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Anonymous session identity: no sign-up, no password, no extra cookie package.
# Streamlit session state creates a random ID for the active browser session.
# Note: this ID may change when the session ends or the browser reconnects.
if "visitor_id" not in st.session_state:
    st.session_state.visitor_id = secrets.token_hex(32)

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "movie_reviews.db"
# Lưu trữ cục bộ bằng SQLite. Tài khoản đầu tiên được tạo sẽ là chủ ứng dụng (Host).

def db_connect():
    conn = sqlite3.connect(str(DB_PATH), timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def create_database_backup_bytes():
    """Tạo bản sao nhất quán kể cả khi SQLite đang dùng WAL."""
    if not DB_PATH.exists():
        raise FileNotFoundError("Chưa tìm thấy movie_reviews.db.")
    memory_db = sqlite3.connect(":memory:")
    try:
        with db_connect() as source:
            source.execute("PRAGMA wal_checkpoint(FULL)")
            source.backup(memory_db)
        # Serialize trực tiếp database trong bộ nhớ thành bytes tải xuống.
        return memory_db.serialize()
    finally:
        memory_db.close()

def validate_database_file(path):
    """Chỉ chấp nhận file SQLite hợp lệ có các bảng cốt lõi của Movie Review."""
    conn = sqlite3.connect(str(path))
    try:
        result = conn.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            return False, "File database bị lỗi hoặc không toàn vẹn."
        tables = {
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        required = {"users", "profiles", "watchlist", "reviews", "movie_catalog"}
        missing = required - tables
        if missing:
            return False, "File không đúng database Movie Review. Thiếu bảng: " + ", ".join(sorted(missing))
        return True, "Database hợp lệ."
    finally:
        conn.close()

def restore_database_from_bytes(file_bytes):
    """Tạo backup trước, kiểm tra file nhập rồi thay thế DB bằng thao tác an toàn."""
    temp_path = BASE_DIR / "movie_reviews_restore_temp.db"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safety_backup = BASE_DIR / f"movie_reviews_before_restore_{timestamp}.db"

    try:
        temp_path.write_bytes(file_bytes)
        valid, message = validate_database_file(temp_path)
        if not valid:
            temp_path.unlink(missing_ok=True)
            return False, message, None

        # Đồng bộ WAL về file chính trước khi tạo bản sao an toàn.
        if DB_PATH.exists():
            with db_connect() as current:
                current.execute("PRAGMA wal_checkpoint(FULL)")
                backup_conn = sqlite3.connect(str(safety_backup))
                try:
                    current.backup(backup_conn)
                finally:
                    backup_conn.close()

        # Loại bỏ sidecar WAL/SHM cũ sau checkpoint để không áp dụng nhầm lên DB mới.
        for suffix in ("-wal", "-shm"):
            sidecar = Path(str(DB_PATH) + suffix)
            if sidecar.exists():
                sidecar.unlink()

        os.replace(temp_path, DB_PATH)

        # Chạy migration/init an toàn để bổ sung bảng/column nếu phiên bản app cần.
        init_db()
        return True, "Khôi phục database thành công.", str(safety_backup) if safety_backup.exists() else None
    except Exception as exc:
        temp_path.unlink(missing_ok=True)
        return False, f"Không thể khôi phục database: {exc}", None


API_BASE = "https://api.streamx.qzz.io"
HEADERS = {
    "User-Agent": "MovieReviewCommunity/1.0 (Streamlit educational project)",
    "Accept": "application/json"
}

# -------------------- CSS --------------------
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600;700;800&family=Playfair+Display:wght@600;700;800&display=swap');
:root { --bg:#080D16; --panel:#111B2A; --panel2:#172438; --line:rgba(213,180,111,.22); --gold:#D9B875; --gold2:#F1DCA9; --white:#F5F3EE; --muted:#AAB6C7; }
.stApp {background:radial-gradient(ellipse at 75% -10%,rgba(115,82,42,.18),transparent 34%),linear-gradient(145deg,#080D16 0%,#0C1421 52%,#101827 100%);color:var(--white);font-family:'Be Vietnam Pro',sans-serif;}
[data-testid="stHeader"] {background:rgba(8,13,22,.72);}
[data-testid="stSidebar"] {
  background:
    radial-gradient(ellipse at 15% 0%, rgba(217,184,117,.12), transparent 34%),
    linear-gradient(180deg,#101B2B 0%,#0A111D 58%,#080E18 100%);
  border-right:1px solid rgba(217,184,117,.20);
}
[data-testid="stSidebar"] > div {padding:1.15rem .85rem 1.4rem;}
[data-testid="stSidebar"] [data-testid="stVerticalBlock"] {gap:.55rem;}
.sidebar-brand {padding:13px 13px 17px;border-bottom:1px solid rgba(217,184,117,.18);margin-bottom:15px;}
.sidebar-brand-mark {display:flex;align-items:center;gap:10px;color:#F3DDAA;font-weight:800;font-size:17px;letter-spacing:.7px;}
.sidebar-brand-icon {width:34px;height:34px;border-radius:11px;display:flex;align-items:center;justify-content:center;background:linear-gradient(145deg,#EAD39E,#B88C4D);color:#111927;font-size:18px;box-shadow:0 5px 18px rgba(201,164,95,.18);}
.sidebar-brand-sub {font-size:9px;letter-spacing:2.4px;color:#8292A8;font-weight:700;margin:8px 0 0 44px;}
.sidebar-profile {padding:14px;border:1px solid rgba(217,184,117,.23);border-radius:15px;background:linear-gradient(145deg,rgba(29,44,65,.94),rgba(15,25,40,.96));margin:2px 0 18px;}
.sidebar-profile-top {display:flex;align-items:center;gap:10px;margin-bottom:10px;}
.sidebar-avatar {width:36px;height:36px;border-radius:50%;display:flex;align-items:center;justify-content:center;background:linear-gradient(145deg,#EAD39E,#B98F54);color:#172033;font-size:17px;}
.sidebar-profile-title {color:#F2E2BF;font-size:12px;font-weight:800;letter-spacing:.7px;}
.sidebar-profile-status {color:#8FD5B0;font-size:10px;margin-top:3px;}
.sidebar-profile-note {color:#AAB8C9;font-size:10px;line-height:1.55;}
.sidebar-section-label {font-size:9px;font-weight:800;letter-spacing:2px;color:#8495AA;text-transform:uppercase;margin:17px 0 7px 4px;}
.sidebar-foot {border-top:1px solid rgba(217,184,117,.16);padding:13px 5px 0;margin-top:15px;color:#8493A7;font-size:10px;line-height:1.65;}
.block-container {max-width:1440px;padding-top:2rem;padding-bottom:3rem;}
h1,h2,h3,h4,h5,h6 {color:var(--white) !important;letter-spacing:-.35px;}
h1 {font-family:'Playfair Display',serif !important;font-weight:800 !important;}
p, label, li {color:#E1E7EF;}
[data-testid="stMarkdownContainer"] p {color:#D7DFEA;}
[data-testid="stCaptionContainer"], .stCaption, small {color:var(--muted) !important;}
.stTextInput label,.stTextArea label,.stSelectbox label,.stSlider label,[data-testid="stWidgetLabel"] p {color:var(--gold2) !important;font-weight:600;}
.hero {position:relative;overflow:hidden;background:radial-gradient(circle at 85% 20%,rgba(220,184,117,.22),transparent 24%),linear-gradient(112deg,rgba(19,34,53,.98),rgba(25,30,39,.96) 55%,rgba(62,45,31,.92));border:1px solid rgba(217,184,117,.34);border-radius:26px;padding:48px 46px;margin:4px 0 30px;box-shadow:0 24px 70px rgba(0,0,0,.28);}
.hero:after {content:'✦';position:absolute;right:7%;top:8%;font-size:150px;line-height:1;color:rgba(241,220,169,.08);transform:rotate(12deg);pointer-events:none;}
.hero h1 {font-family:'Playfair Display',serif;font-size:clamp(32px,4vw,52px);line-height:1.13;margin:12px 0 10px;color:#F5E8C9 !important;max-width:760px;}
.hero p {font-size:15px;line-height:1.9;color:#D5DFEA;max-width:680px;margin:0;}
.hero-kicker {display:inline-flex;align-items:center;gap:9px;color:#E6C98E;font-size:11px;font-weight:800;letter-spacing:3px;text-transform:uppercase;}
.hero-kicker:before {content:'';width:28px;height:1px;background:var(--gold);}
.hero-note {margin-top:22px;color:#B7C2D0;font-size:12px;letter-spacing:.4px;}
.section {font-size:22px;font-weight:800;color:var(--gold2);margin:26px 0 14px;}
div[data-testid="stMetric"] {background:linear-gradient(145deg,#172438,#101A29);border:1px solid var(--line);border-radius:18px;padding:18px;box-shadow:0 10px 30px rgba(0,0,0,.12);}
div[data-testid="stMetricLabel"] {color:#B8C5D5 !important;}
div[data-testid="stMetricValue"] {color:var(--gold2) !important;}
div[data-testid="stForm"] {background:rgba(17,27,42,.88);border:1px solid var(--line);border-radius:20px;padding:22px;box-shadow:0 14px 35px rgba(0,0,0,.16);}
.stButton > button,.stFormSubmitButton > button,.stDownloadButton > button {transition:all .2s ease;border-radius:11px;font-weight:700;min-height:43px;}
.stButton > button[kind="primary"],.stFormSubmitButton > button {background:linear-gradient(135deg,#E7CD96,#C9A45F) !important;color:#111927 !important;border:1px solid #F0DDAF !important;box-shadow:0 7px 20px rgba(201,164,95,.16);}
.stButton > button[kind="primary"]:hover,.stFormSubmitButton > button:hover {transform:translateY(-1px);filter:brightness(1.08);box-shadow:0 10px 25px rgba(201,164,95,.24);}
.stButton > button[kind="secondary"],.stDownloadButton > button {background:#18263A !important;color:#F2F4F8 !important;border:1px solid #40516A !important;}
.stButton > button[kind="secondary"]:hover,.stDownloadButton > button:hover {background:#24364F !important;border-color:var(--gold) !important;color:#FFF !important;}
.stTextInput input,.stTextArea textarea {background:#0D1929 !important;color:#FFFFFF !important;border:1px solid #43546B;border-radius:10px;}
.stTextInput input:focus,.stTextArea textarea:focus {border-color:var(--gold) !important;box-shadow:0 0 0 1px var(--gold) !important;}
.stTextInput input::placeholder,.stTextArea textarea::placeholder {color:#8796AA !important;opacity:1;}
.stSelectbox div[data-baseweb="select"] > div {background:#0D1929;color:#FFFFFF;border-color:#43546B;border-radius:10px;}
.stSlider [data-testid="stTickBar"] {color:#DCE5F1;}
[data-testid="stAlert"] {border-radius:14px;}
div[data-testid="stVerticalBlockBorderWrapper"] {border-color:var(--line);border-radius:17px;background:linear-gradient(145deg,rgba(21,34,52,.96),rgba(13,23,37,.96));}
a {color:var(--gold2) !important;}
.muted {font-size:12px;color:#9EADBF;}
.poster-placeholder {height:280px;background:linear-gradient(145deg,#1b2a40,#3a3028);border:1px solid #46536a;border-radius:13px;display:flex;align-items:center;justify-content:center;font-size:56px;}
[data-testid="stImage"] img {border-radius:12px;transition:transform .25s ease,filter .25s ease;}
[data-testid="stImage"] img:hover {filter:brightness(1.08);}
[data-testid="stSidebar"] .stButton {margin:0 !important;}
[data-testid="stSidebar"] .stButton button {
  text-align:left;border-radius:11px;padding:9px 12px;min-height:42px;
  font-size:12px;font-weight:650;letter-spacing:.15px;
  border:1px solid rgba(117,139,168,.34) !important;
  background:rgba(24,38,58,.82) !important;color:#F0F4FA !important;
  box-shadow:none;transition:all .18s ease;
}
[data-testid="stSidebar"] .stButton button:hover {
  border-color:rgba(217,184,117,.7) !important;background:rgba(43,58,78,.96) !important;
  color:#FFF !important;transform:translateX(2px);
}
[data-testid="stSidebar"] .stButton button[kind="primary"] {
  background:linear-gradient(110deg,#F0DCA9 0%,#D4B16F 100%) !important;
  border:1px solid #F5E5BE !important;
  color:#142033 !important;
  box-shadow:0 7px 20px rgba(201,164,95,.22), inset 0 1px 0 rgba(255,255,255,.35);
}
[data-testid="stSidebar"] .stButton button[kind="primary"] *,
[data-testid="stSidebar"] .stButton button[kind="primary"] p,
[data-testid="stSidebar"] .stButton button[kind="primary"] span,
[data-testid="stSidebar"] .stButton button[kind="primary"] div {
  color:#142033 !important;
  -webkit-text-fill-color:#142033 !important;
  font-weight:800 !important;
  opacity:1 !important;
}
[data-testid="stSidebar"] .stButton button[kind="primary"]:hover {
  background:linear-gradient(110deg,#F7E8C4 0%,#E1C486 100%) !important;
  color:#101A2A !important;
}
[data-testid="stSidebar"] .stButton button[kind="primary"]:hover {
  background:linear-gradient(110deg,#F3E1B8,#D8B675) !important;color:#101827 !important;
}
hr {border-color:rgba(217,184,117,.18);}
 
.featured-panel {border:1px solid rgba(230,199,137,.35);border-radius:24px;padding:30px;background:linear-gradient(110deg,rgba(9,17,29,.96),rgba(24,35,51,.88));box-shadow:0 22px 55px rgba(0,0,0,.24);margin:10px 0 25px;}
.eyebrow {font-size:10px;font-weight:800;letter-spacing:2.8px;color:#E7CB91;text-transform:uppercase;}
.featured-title {font-family:'Playfair Display',serif;font-size:clamp(28px,3vw,42px);font-weight:800;color:#F6E8C7;line-height:1.15;margin:10px 0;}
.featured-copy {color:#C7D2E0;font-size:13px;line-height:1.75;}
.poster-tile {background:linear-gradient(145deg,#18263A,#0C1421);border:1px solid rgba(217,184,117,.16);border-radius:15px;padding:10px;height:100%;}
.pill {display:inline-block;border:1px solid rgba(217,184,117,.35);border-radius:999px;padding:4px 9px;color:#EAD39E;font-size:10px;letter-spacing:.5px;}
.social-card {background:linear-gradient(145deg,#152238,#0F1928);border:1px solid rgba(217,184,117,.22);border-radius:16px;padding:16px;margin:10px 0;}
.social-meta {color:#9EADC0;font-size:11px;}
footer {visibility:hidden;}
</style>
""", unsafe_allow_html=True)

# -------------------- HTTP --------------------
@st.cache_data(ttl=900, show_spinner=False)
def api_get(path, params=None):
    url = API_BASE.rstrip("/") + "/" + path.lstrip("/")
    response = requests.get(url, params=params or {}, headers=HEADERS, timeout=10)
    response.raise_for_status()
    return response.json()

def first(dct, *keys, default=None):
    if not isinstance(dct, dict):
        return default
    for key in keys:
        value = dct.get(key)
        if value not in (None, "", [], {}):
            return value
    return default

def clean_text(value):
    if not value:
        return ""
    value = re.sub(r"<[^>]+>", " ", str(value))
    return html.unescape(re.sub(r"\s+", " ", value)).strip()

def listify(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return list(value.values())
    return [value]

def normalize_search_item(item, default_type="movie", source="StreamX"):
    """Normalize IMDb/Cinemeta/AniList-like results to one app schema."""
    if not isinstance(item, dict):
        return None

    nested = item.get("meta") if isinstance(item.get("meta"), dict) else {}
    data = {**item, **nested}

    imdb_id = first(data, "imdb_id", "imdbId", "imdb", "id")
    media_type = first(data, "type", "media_type", "mediaType", default=default_type)
    media_type = str(media_type).lower()
    if media_type in ("tv", "show", "series", "tvseries"):
        media_type = "series"
    elif media_type in ("anime",):
        media_type = "anime"
    else:
        media_type = "movie"

    title = first(data, "title", "name", "original_title", "originalTitle", default="Chưa có tên")
    year = first(data, "year", "release_year", "releaseYear", "released")
    if isinstance(year, str) and len(year) >= 4:
        year = year[:4]
    poster = first(data, "poster", "poster_url", "posterUrl", "image", "coverImage", "cover")
    background = first(data, "background", "backdrop", "backdrop_url", "backgroundUrl")
    if isinstance(poster, dict):
        poster = first(poster, "url", "large", "medium")
    if isinstance(background, dict):
        background = first(background, "url", "large", "medium")

    if isinstance(imdb_id, str) and not imdb_id.startswith("tt"):
        # IMDb search results can wrap the ID in a nested object.
        imdb_id = first(data, "imdbID", "tconst", default=imdb_id)

    return {
        "id": str(imdb_id or first(data, "slug", "id", default=f"{media_type}:{title}:{year}")),
        "imdb_id": str(imdb_id) if imdb_id else None,
        "type": media_type,
        "source": source,
        "title": str(title),
        "year": str(year) if year else "Chưa rõ",
        "poster": poster,
        "background": background,
        "overview": clean_text(first(data, "description", "overview", "plot", "summary", default="")),
        "rating": first(data, "imdbRating", "rating", "imdb_rating", "score", "averageScore"),
        "genres": listify(first(data, "genres", "genre", default=[])),
        "raw": data
    }

def unwrap_results(payload):
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ("results", "metas", "items", "shows", "data", "titles"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            for subkey in ("results", "metas", "items"):
                if isinstance(value.get(subkey), list):
                    return value[subkey]
    # Some endpoints return a single object
    if any(k in payload for k in ("title", "name", "imdb_id", "imdbId")):
        return [payload]
    return []

# -------------------- DATABASE --------------------
def init_db():
    with db_connect() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                movie_id TEXT NOT NULL,
                movie_name TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT '',
                reviewer TEXT NOT NULL,
                score INTEGER NOT NULL CHECK(score BETWEEN 1 AND 10),
                comment TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        # Migrate older databases without deleting existing reviews.
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(reviews)").fetchall()]
        migrations = {
            "source": "ALTER TABLE reviews ADD COLUMN source TEXT NOT NULL DEFAULT ''",
            "movie_name": "ALTER TABLE reviews ADD COLUMN movie_name TEXT NOT NULL DEFAULT ''",
            "owner_id": "ALTER TABLE reviews ADD COLUMN owner_id TEXT",
            "spoiler": "ALTER TABLE reviews ADD COLUMN spoiler INTEGER NOT NULL DEFAULT 0"
        }
        for col, sql in migrations.items():
            if col not in cols:
                conn.execute(sql)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_reviews_movie ON reviews(movie_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_reviews_date ON reviews(created_at)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS review_likes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                review_id INTEGER NOT NULL,
                owner_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(review_id, owner_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS review_comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                review_id INTEGER NOT NULL,
                owner_id TEXT NOT NULL,
                display_name TEXT NOT NULL,
                comment TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS collections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                UNIQUE(owner_id, name)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS collection_movies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                collection_id INTEGER NOT NULL,
                movie_id TEXT NOT NULL,
                movie_json TEXT NOT NULL,
                added_at TEXT NOT NULL,
                UNIQUE(collection_id, movie_id)
            )
        """)

        # Hồ sơ hiển thị đơn giản (chưa phải hệ thống đăng nhập bảo mật).
        conn.execute("""
            CREATE TABLE IF NOT EXISTS profiles (
                username TEXT PRIMARY KEY,
                bio TEXT NOT NULL DEFAULT '',
                favorite_genres TEXT NOT NULL DEFAULT '[]',
                updated_at TEXT NOT NULL
            )
        """)

        # Watchlist: mỗi người dùng có danh sách riêng.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS watchlist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                movie_id TEXT NOT NULL,
                movie_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Muốn xem',
                created_at TEXT NOT NULL,
                UNIQUE(username, movie_id)
            )
        """)

        # Lưu danh mục phim đã tìm thấy để dùng cho gợi ý.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS movie_catalog (
                movie_id TEXT PRIMARY KEY,
                movie_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        # Lịch sử tìm kiếm riêng theo từng tài khoản; không lưu lịch sử khách.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS search_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL COLLATE NOCASE,
                query TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'Tất cả',
                result_count INTEGER NOT NULL DEFAULT 0,
                searched_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_search_history_user_date ON search_history(username, searched_at DESC)")

        # Tài khoản đăng nhập. Mật khẩu chỉ lưu dạng PBKDF2 hash + salt.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL COLLATE NOCASE UNIQUE,
                password_hash TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        # Dữ liệu hồ sơ/watchlist cũ được tạo khi chưa có đăng nhập,
        # nên không thể xác minh chủ sở hữu. Xóa đúng một lần để tránh
        # người khác đăng ký trùng tên và nhận dữ liệu cá nhân cũ.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS app_meta (
                meta_key TEXT PRIMARY KEY,
                meta_value TEXT NOT NULL
            )
        """)
        # Không xóa hoặc reset dữ liệu cũ khi khởi động ứng dụng.
        conn.commit()

init_db()


def save_search_history(username, query, category, result_count):
    """Persist a search only for an authenticated account."""
    if not username or not str(query).strip():
        return
    with db_connect() as conn:
        conn.execute(
            """INSERT INTO search_history(username, query, category, result_count, searched_at)
               VALUES(?,?,?,?,?)""",
            (str(username).strip(), str(query).strip(), str(category or "Tất cả"),
             int(result_count or 0), datetime.now(timezone.utc).isoformat(timespec="seconds"))
        )
        conn.commit()


def load_search_history(username, limit=12):
    if not username:
        return []
    with db_connect() as conn:
        rows = conn.execute(
            """SELECT id, query, category, result_count, searched_at
               FROM search_history WHERE username=? COLLATE NOCASE
               ORDER BY id DESC LIMIT ?""",
            (str(username).strip(), int(limit))
        ).fetchall()
    return [dict(row) for row in rows]


def clear_search_history(username):
    if not username:
        return
    with db_connect() as conn:
        conn.execute("DELETE FROM search_history WHERE username=? COLLATE NOCASE",
                     (str(username).strip(),))
        conn.commit()


def save_review(movie_id, movie_name, source, reviewer, score, comment, owner_id=None, spoiler=False):
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with db_connect() as conn:
        conn.execute("""
            INSERT INTO reviews(movie_id,movie_name,source,reviewer,score,comment,created_at,owner_id,spoiler)
            VALUES(?,?,?,?,?,?,?,?,?)
        """, (str(movie_id), movie_name, source, reviewer, int(score), comment, created, owner_id, 1 if spoiler else 0))
        conn.commit()

def load_reviews(movie_id=None, limit=5000):
    with db_connect() as conn:
        if movie_id:
            rows = conn.execute(
                "SELECT * FROM reviews WHERE movie_id=? ORDER BY id DESC LIMIT ?",
                (str(movie_id), int(limit))
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM reviews ORDER BY id DESC LIMIT ?",
                (int(limit),)
            ).fetchall()
    return pd.DataFrame([dict(row) for row in rows])


def toggle_review_like(review_id, owner_id):
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with db_connect() as conn:
        exists = conn.execute(
            "SELECT id FROM review_likes WHERE review_id=? AND owner_id=?",
            (int(review_id), str(owner_id))
        ).fetchone()
        if exists:
            conn.execute("DELETE FROM review_likes WHERE id=?", (exists["id"],))
            liked = False
        else:
            conn.execute(
                "INSERT INTO review_likes(review_id,owner_id,created_at) VALUES(?,?,?)",
                (int(review_id), str(owner_id), now)
            )
            liked = True
        conn.commit()
    return liked

def review_social_stats(review_id, owner_id):
    with db_connect() as conn:
        likes = conn.execute(
            "SELECT COUNT(*) AS n FROM review_likes WHERE review_id=?",
            (int(review_id),)
        ).fetchone()["n"]
        mine = conn.execute(
            "SELECT 1 FROM review_likes WHERE review_id=? AND owner_id=?",
            (int(review_id), str(owner_id))
        ).fetchone()
        comments = conn.execute(
            "SELECT * FROM review_comments WHERE review_id=? ORDER BY id DESC LIMIT 30",
            (int(review_id),)
        ).fetchall()
    return int(likes), bool(mine), [dict(row) for row in comments]

def add_review_comment(review_id, owner_id, display_name, comment):
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with db_connect() as conn:
        conn.execute(
            "INSERT INTO review_comments(review_id,owner_id,display_name,comment,created_at) VALUES(?,?,?,?,?)",
            (int(review_id), str(owner_id), display_name.strip()[:40], comment.strip()[:1000], now)
        )
        conn.commit()

def create_collection(owner_id, name, description=""):
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with db_connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO collections(owner_id,name,description,created_at) VALUES(?,?,?,?)",
            (str(owner_id), name.strip()[:60], description.strip()[:300], now)
        )
        conn.commit()

def load_collections(owner_id):
    with db_connect() as conn:
        rows = conn.execute(
            "SELECT * FROM collections WHERE owner_id=? ORDER BY id DESC",
            (str(owner_id),)
        ).fetchall()
        output=[]
        for row in rows:
            movies=conn.execute(
                "SELECT movie_json FROM collection_movies WHERE collection_id=? ORDER BY id DESC",
                (row["id"],)
            ).fetchall()
            items=[]
            for item in movies:
                try: items.append(json.loads(item["movie_json"]))
                except Exception: pass
            data=dict(row)
            data["movies"]=items
            output.append(data)
    return output

def add_movie_to_collection(collection_id, movie):
    movie_id=str(movie.get("imdb_id") or movie.get("id"))
    now=datetime.now(timezone.utc).isoformat(timespec="seconds")
    with db_connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO collection_movies(collection_id,movie_id,movie_json,added_at) VALUES(?,?,?,?)",
            (int(collection_id),movie_id,json.dumps(movie,ensure_ascii=False),now)
        )
        conn.commit()

def delete_collection(collection_id, owner_id):
    with db_connect() as conn:
        conn.execute(
            "DELETE FROM collection_movies WHERE collection_id=? AND collection_id IN (SELECT id FROM collections WHERE id=? AND owner_id=?)",
            (int(collection_id),int(collection_id),str(owner_id))
        )
        conn.execute("DELETE FROM collections WHERE id=? AND owner_id=?",(int(collection_id),str(owner_id)))
        conn.commit()

def save_profile(username, bio, favorite_genres):
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with db_connect() as conn:
        conn.execute("""
            INSERT INTO profiles(username,bio,favorite_genres,updated_at)
            VALUES(?,?,?,?)
            ON CONFLICT(username) DO UPDATE SET
                bio=excluded.bio,
                favorite_genres=excluded.favorite_genres,
                updated_at=excluded.updated_at
        """, (username, bio, json.dumps(favorite_genres, ensure_ascii=False), now))
        conn.commit()

def load_profile(username):
    with db_connect() as conn:
        row = conn.execute(
            "SELECT * FROM profiles WHERE username=?", (username,)
        ).fetchone()
    if not row:
        return {"bio": "", "favorite_genres": []}
    try:
        genres = json.loads(row["favorite_genres"] or "[]")
    except Exception:
        genres = []
    return {"bio": row["bio"], "favorite_genres": genres}

def save_movie_catalog(movies):
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with db_connect() as conn:
        for movie in movies:
            movie_id = str(movie.get("imdb_id") or movie.get("id"))
            conn.execute("""
                INSERT INTO movie_catalog(movie_id,movie_json,updated_at)
                VALUES(?,?,?)
                ON CONFLICT(movie_id) DO UPDATE SET
                    movie_json=excluded.movie_json,
                    updated_at=excluded.updated_at
            """, (movie_id, json.dumps(movie, ensure_ascii=False), now))
        conn.commit()

def add_to_watchlist(username, movie, status="Muốn xem"):
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    movie_id = str(movie.get("imdb_id") or movie.get("id"))
    with db_connect() as conn:
        conn.execute("""
            INSERT INTO watchlist(username,movie_id,movie_json,status,created_at)
            VALUES(?,?,?,?,?)
            ON CONFLICT(username,movie_id) DO UPDATE SET
                movie_json=excluded.movie_json,
                status=excluded.status
        """, (username, movie_id, json.dumps(movie, ensure_ascii=False), status, now))
        conn.commit()

def load_watchlist(username):
    with db_connect() as conn:
        rows = conn.execute("""
            SELECT * FROM watchlist WHERE username=?
            ORDER BY id DESC
        """, (username,)).fetchall()
    output = []
    for row in rows:
        try:
            movie = json.loads(row["movie_json"])
            movie["_watchlist_id"] = row["id"]
            movie["_watch_status"] = row["status"]
            output.append(movie)
        except Exception:
            continue
    return output

def update_watch_status(item_id, status):
    with db_connect() as conn:
        conn.execute("UPDATE watchlist SET status=? WHERE id=?", (status, item_id))
        conn.commit()

def remove_from_watchlist(item_id):
    with db_connect() as conn:
        conn.execute("DELETE FROM watchlist WHERE id=?", (item_id,))
        conn.commit()

def _normalize_genre(value):
    text = str(value or "").strip().casefold()
    aliases = {
        "sci-fi": "science fiction", "scifi": "science fiction",
        "science-fiction": "science fiction", "action & adventure": "action",
        "tv movie": "tv movie", "animation": "animation",
    }
    return aliases.get(text, text)

def _extract_movie_genres(movie):
    raw = movie.get("genres") or movie.get("genre") or []
    if isinstance(raw, str):
        raw = re.split(r"[,|/;]", raw)
    result = []
    for item in raw:
        if isinstance(item, dict):
            item = item.get("name") or item.get("title") or ""
        normalized = _normalize_genre(item)
        if normalized:
            result.append(normalized)
    return set(result)

def get_recommendations(username, limit=20):
    """Cá nhân hóa theo hồ sơ + điểm review của đúng tài khoản; dữ liệu cộng đồng không trộn vào gu cá nhân."""
    profile = load_profile(username)
    preferred = {_normalize_genre(g) for g in profile.get("favorite_genres", [])}
    preferred.discard("")

    reviews = load_reviews(limit=10000)
    reviewed_ids = set()
    personal_genre_scores = {}
    if not reviews.empty and "owner_id" in reviews.columns:
        owner_col = reviews["owner_id"].fillna("").astype(str)
        mine = reviews[owner_col == str(username)]
        catalog_by_id = {}
        with db_connect() as conn:
            rows = conn.execute("SELECT movie_id,movie_json FROM movie_catalog").fetchall()
        for row in rows:
            try:
                catalog_by_id[str(row["movie_id"])] = json.loads(row["movie_json"])
            except Exception:
                continue

        for _, review in mine.iterrows():
            movie_id = str(review.get("movie_id") or "")
            if movie_id:
                reviewed_ids.add(movie_id)
            movie = catalog_by_id.get(movie_id, {})
            try:
                user_score = float(review.get("score") or 0)
            except (TypeError, ValueError):
                user_score = 0
            # Điểm >= 7 làm tăng affinity; điểm <= 4 làm giảm affinity.
            influence = (user_score - 5.5) / 4.5
            for genre in _extract_movie_genres(movie):
                personal_genre_scores[genre] = personal_genre_scores.get(genre, 0.0) + influence

    watch_items = load_watchlist(username)
    watch_ids = {
        str(item.get("imdb_id") or item.get("id") or "")
        for item in watch_items
    }
    excluded = reviewed_ids | watch_ids

    with db_connect() as conn:
        rows = conn.execute(
            "SELECT movie_id,movie_json FROM movie_catalog ORDER BY updated_at DESC"
        ).fetchall()

    candidates = []
    for row in rows:
        try:
            movie = json.loads(row["movie_json"])
        except Exception:
            continue
        movie_id = str(movie.get("imdb_id") or movie.get("id") or row["movie_id"])
        if not movie_id or movie_id in excluded:
            continue

        genres = _extract_movie_genres(movie)
        if not genres:
            continue

        profile_fit = (
            len(preferred & genres) / max(1, len(preferred)) * 10
            if preferred else 5.0
        )
        if personal_genre_scores:
            max_signal = max(1.0, max(abs(v) for v in personal_genre_scores.values()))
            review_fit = sum(personal_genre_scores.get(g, 0.0) for g in genres) / max_signal
            review_fit = max(0.0, min(10.0, 5.0 + 5.0 * review_fit / max(1, len(genres))))
        else:
            review_fit = profile_fit

        raw_rating = movie.get("imdbRating") or movie.get("rating") or movie.get("vote_average")
        rating_score = None
        try:
            match = re.search(r"\d+(?:[.,]\d+)?", str(raw_rating))
            if match:
                rating_score = float(match.group(0).replace(",", "."))
                if 10 < rating_score <= 100:
                    rating_score /= 10
                if not 0 <= rating_score <= 10:
                    rating_score = None
        except Exception:
            rating_score = None

        parts = [(profile_fit, 0.35), (review_fit, 0.45)]
        if rating_score is not None:
            parts.append((rating_score, 0.20))
        weight_sum = sum(weight for _, weight in parts)
        score = sum(value * weight for value, weight in parts) / weight_sum
        candidates.append((round(score, 3), movie))

    candidates.sort(key=lambda item: item[0], reverse=True)
    return [movie for _, movie in candidates[:limit]]

# -------------------- ACCOUNT / STABLE USER ID --------------------
def current_owner_id():
    """Tài khoản đăng nhập có ID ổn định; nếu chưa đăng nhập dùng ID phiên ẩn danh."""
    return str(st.session_state.get("account_username") or st.session_state.get("visitor_id") or "")

def _password_digest(password: str, salt_hex: str) -> str:
    salt = bytes.fromhex(salt_hex)
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 310_000).hex()

def register_account(username: str, password: str):
    username = username.strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,24}", username):
        return False, "Tên tài khoản cần 3–24 ký tự: chữ, số, dấu chấm, gạch dưới hoặc gạch ngang."
    if len(password) < 8:
        return False, "Mật khẩu cần tối thiểu 8 ký tự."
    salt = secrets.token_hex(16)
    digest = _password_digest(password, salt)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        with db_connect() as conn:
            conn.execute(
                "INSERT INTO users(username,password_hash,password_salt,created_at) VALUES(?,?,?,?)",
                (username, digest, salt, now)
            )
            conn.commit()
        return True, "Tạo tài khoản thành công. Bạn có thể đăng nhập."
    except Exception as exc:
        if isinstance(exc, sqlite3.IntegrityError) or getattr(getattr(exc, "diag", None), "sqlstate", None) == "23505":
            return False, "Tên tài khoản đã tồn tại."
        raise

def authenticate_account(username: str, password: str):
    with db_connect() as conn:
        row = conn.execute(
            "SELECT username,password_hash,password_salt FROM users WHERE LOWER(username)=LOWER(?)",
            (username.strip(),)
        ).fetchone()
    if not row:
        return None
    try:
        candidate = _password_digest(password, row["password_salt"])
        if secrets.compare_digest(candidate, row["password_hash"]):
            return str(row["username"])
    except Exception:
        return None
    return None



def merge_session_data_into_account(anonymous_id: str, username: str):
    """Gắn dữ liệu của phiên hiện tại vào tài khoản, không ghi đè dữ liệu tài khoản đã có."""
    if not anonymous_id or anonymous_id == username:
        return
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with db_connect() as conn:
        # Review, lượt thích, bình luận và bộ sưu tập có thể chuyển owner trực tiếp.
        for table, column in (
            ("reviews", "owner_id"),
            ("review_likes", "owner_id"),
            ("review_comments", "owner_id"),
            ("collections", "owner_id"),
        ):
            conn.execute(
                f"UPDATE {table} SET {column}=? WHERE {column}=?",
                (username, anonymous_id)
            )

        # Chuyển Watchlist nhưng không tạo bản ghi trùng (username, movie_id).
        old_items = conn.execute(
            "SELECT * FROM watchlist WHERE username=?", (anonymous_id,)
        ).fetchall()
        for item in old_items:
            exists = conn.execute(
                "SELECT id FROM watchlist WHERE username=? AND movie_id=?",
                (username, item["movie_id"])
            ).fetchone()
            if exists:
                conn.execute("DELETE FROM watchlist WHERE id=?", (item["id"],))
            else:
                conn.execute(
                    "UPDATE watchlist SET username=? WHERE id=?",
                    (username, item["id"])
                )

        # Chỉ chuyển hồ sơ ẩn danh nếu tài khoản chưa có hồ sơ.
        old_profile = conn.execute(
            "SELECT * FROM profiles WHERE username=?", (anonymous_id,)
        ).fetchone()
        account_profile = conn.execute(
            "SELECT username FROM profiles WHERE username=?", (username,)
        ).fetchone()
        if old_profile and not account_profile:
            conn.execute(
                "UPDATE profiles SET username=?,updated_at=? WHERE username=?",
                (username, now, anonymous_id)
            )
        conn.commit()



# -------------------- DIRECT KEYLESS SOURCE ADAPTERS --------------------
# StreamX remains the primary aggregator. These adapters provide independent
# fallbacks so one upstream outage or incomplete catalogue does not empty results.

TVMAZE_BASE = "https://api.tvmaze.com"
ANILIST_URL = "https://graphql.anilist.co"

def _tvmaze_country_codes(show):
    show = show if isinstance(show, dict) else {}
    codes = []
    for parent in (show.get("network"), show.get("webChannel")):
        country = parent.get("country") if isinstance(parent, dict) else None
        if isinstance(country, dict):
            code = first(country, "code", "name", default="")
            if code:
                codes.append(str(code).casefold())
    return codes

def _normalize_tvmaze_result(row):
    show = row.get("show", row) if isinstance(row, dict) else {}
    if not isinstance(show, dict):
        return None
    image = show.get("image") or {}
    externals = show.get("externals") or {}
    premiered = str(show.get("premiered") or "")
    return {
        "id": str(externals.get("imdb") or f"tvmaze:{show.get('id')}"),
        "imdb_id": externals.get("imdb"),
        "type": "series",
        "source": "TVmaze",
        "title": show.get("name") or "Chưa có tên",
        "year": premiered[:4] if premiered else "Chưa rõ",
        "poster": first(image, "original", "medium"),
        "background": None,
        "overview": clean_text(show.get("summary") or ""),
        "rating": (show.get("rating") or {}).get("average"),
        "genres": show.get("genres") or [],
        "raw": {
            "tvmaze_id": show.get("id"),
            "network": show.get("network"),
            "webChannel": show.get("webChannel"),
            "country_codes": _tvmaze_country_codes(show),
            "language": show.get("language"),
            "status": show.get("status"),
            "officialSite": show.get("officialSite")
        }
    }

@st.cache_data(ttl=1800, show_spinner=False)
def search_tvmaze_shows(query):
    """TVmaze official keyless show search."""
    response = requests.get(
        f"{TVMAZE_BASE}/search/shows",
        params={"q": query},
        headers={"User-Agent": "MovieReviewCommunity/1.0"},
        timeout=12
    )
    response.raise_for_status()
    return [item for row in response.json() if (item := _normalize_tvmaze_result(row))]

@st.cache_data(ttl=1800, show_spinner=False)
def search_anilist_titles(query):
    """AniList public GraphQL search for anime."""
    gql = """
    query ($search: String) {
      Page(page: 1, perPage: 30) {
        media(search: $search, type: ANIME, sort: SEARCH_MATCH) {
          id
          idMal
          title { romaji english native }
          startDate { year }
          coverImage { large extraLarge }
          bannerImage
          description(asHtml: false)
          averageScore
          genres
          countryOfOrigin
          format
        }
      }
    }
    """
    response = requests.post(
        ANILIST_URL,
        json={"query": gql, "variables": {"search": query}},
        headers={"User-Agent": "MovieReviewCommunity/1.0"},
        timeout=15
    )
    response.raise_for_status()
    rows = response.json().get("data", {}).get("Page", {}).get("media", [])
    output = []
    for item in rows:
        title_data = item.get("title") or {}
        title = first(title_data, "english", "romaji", "native", default="Chưa có tên")
        cover = item.get("coverImage") or {}
        output.append({
            "id": f"anilist:{item.get('id')}",
            "imdb_id": None,
            "type": "anime",
            "source": "AniList",
            "title": title,
            "year": str((item.get("startDate") or {}).get("year") or "Chưa rõ"),
            "poster": first(cover, "extraLarge", "large"),
            "background": item.get("bannerImage"),
            "overview": clean_text(item.get("description") or ""),
            "rating": item.get("averageScore"),
            "genres": item.get("genres") or [],
            "raw": {"anilist_id": item.get("id"), "countryOfOrigin": item.get("countryOfOrigin"), "format": item.get("format")}
        })
    return output


# -------------------- SEARCH --------------------
@st.cache_data(ttl=900, show_spinner=False)
def search_movies(query, category):
    """Search multiple keyless catalogues and fetch additional pages concurrently."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    query = str(query or "").strip()
    if len(query) < 2:
        return [], ["Vui lòng nhập ít nhất 2 ký tự."]

    found, errors = [], []
    jobs = []

    # IMDb suggestion search is useful for title spelling, release year and artwork.
    jobs.append(("imdb", "imdb/search", {"q": query}, "movie", "IMDb suggestion"))

    if category in ("Tất cả", "Phim điện ảnh"):
        for skip in (0, 20, 40):
            jobs.append((f"movie_{skip}", "search", {"q": query, "type": "movie", "skip": skip}, "movie", "Cinemeta"))
    if category in ("Tất cả", "Phim bộ / Series"):
        for skip in (0, 20, 40):
            jobs.append((f"series_{skip}", "search", {"q": query, "type": "series", "skip": skip}, "series", "Cinemeta"))
    if category in ("Tất cả", "Anime"):
        jobs.append(("anime", "anime/search", {"q": query}, "anime", "AniList"))

    def fetch(job):
        key, endpoint, params, media_type, source = job
        payload = api_get(endpoint, params)
        return key, media_type, source, unwrap_results(payload)

    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(fetch, job): job for job in jobs}
        direct_jobs = {}
        if category in ("Tất cả", "Phim bộ / Series", "Phim bộ"):
            direct_jobs[pool.submit(search_tvmaze_shows, query)] = "TVmaze"
        if category in ("Tất cả", "Anime"):
            direct_jobs[pool.submit(search_anilist_titles, query)] = "AniList"

        for future in as_completed(futures):
            job = futures[future]
            try:
                _, media_type, source, rows = future.result()
                for raw in rows:
                    item = normalize_search_item(raw, media_type, source)
                    if item:
                        if media_type == "anime":
                            item["type"] = "anime"
                        found.append(item)
            except Exception as exc:
                errors.append(f"{job[0]}: {str(exc)[:160]}")

        for future in as_completed(direct_jobs):
            source = direct_jobs[future]
            try:
                found.extend(future.result())
            except Exception as exc:
                errors.append(f"{source}: {str(exc)[:160]}")

    unique = {}
    for item in found:
        title_key = re.sub(r"[^a-z0-9]+", "", item["title"].casefold())
        key = item.get("imdb_id") or f'{item["type"]}:{title_key}:{item["year"]}'
        if key not in unique:
            unique[key] = item
        else:
            old = unique[key]
            # Prefer richer metadata while retaining the first source's ranking.
            for field in ("poster", "background", "overview", "rating", "imdb_id"):
                if not old.get(field) and item.get(field):
                    old[field] = item[field]

    results = list(unique.values())
    # Titles with posters first, then titles with release years; don't fabricate ratings.
    results.sort(
        key=lambda item: (
            bool(item.get("poster")),
            item.get("year") != "Chưa rõ",
            _rating_number(item.get("rating"))
        ),
        reverse=True
    )
    return results[:100], errors[:10]

# -------------------- DETAILS --------------------
@st.cache_data(ttl=1800, show_spinner=False)
def get_details(movie):
    imdb_id = movie.get("imdb_id")
    media_type = movie.get("type", "movie")
    if not imdb_id or not str(imdb_id).startswith("tt"):
        return movie

    api_type = "series" if media_type in ("series", "anime") else "movie"
    payload = api_get(f"meta/{api_type}/{quote(str(imdb_id), safe='')}", {"enrich": "0"})

    meta = payload.get("meta", payload) if isinstance(payload, dict) else {}
    result = dict(movie)
    result["raw_detail"] = meta

    result["title"] = first(meta, "name", "title", default=movie["title"])
    result["overview"] = clean_text(first(meta, "description", "plot", "overview", "summary", default=movie.get("overview")))
    result["year"] = str(first(meta, "year", "releaseInfo", default=movie.get("year", "Chưa rõ")))
    result["poster"] = first(meta, "poster", default=movie.get("poster"))
    result["background"] = first(meta, "background", "backdrop", default=movie.get("background"))
    result["rating"] = first(meta, "imdbRating", "rating", default=movie.get("rating"))
    result["genres"] = listify(first(meta, "genres", default=movie.get("genres", [])))
    result["runtime"] = first(meta, "runtime", "runtimeMinutes")
    result["released"] = first(meta, "released", "releaseInfo", "release_date")
    result["director"] = first(meta, "director", "directors")
    result["cast"] = listify(first(meta, "cast", "actors", default=[]))
    result["writer"] = first(meta, "writer", "writers")
    result["country"] = first(meta, "country", "countries")
    result["videos"] = listify(first(meta, "videos", "trailers", default=[]))
    result["episodes"] = listify(first(meta, "videos", "episodes", default=[]))
    result["imdb_url"] = f"https://www.imdb.com/title/{imdb_id}/"
    return result

# -------------------- NAVIGATION STATE --------------------
for key, default in {
    "page": "Trang chủ",
    "previous_page": "Tìm kiếm phim",
    "selected_movie": None,
    "search_results": [],
    "last_query": "",
    "search_category": "Tất cả"
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

def select_movie(movie):
    # Lưu trang hiện tại để nút quay lại trở về đúng nơi người dùng vừa xem.
    current_page = st.session_state.get("page", "Tìm kiếm phim")
    if current_page != "Chi tiết phim":
        st.session_state.previous_page = current_page

    st.session_state.selected_movie = movie
    st.session_state.page = "Chi tiết phim"

def go_search():
    st.session_state.page = "Tìm kiếm phim"

def back_from_detail():
    previous = st.session_state.get("previous_page", "Tìm kiếm phim")
    if previous == "Chi tiết phim":
        previous = "Tìm kiếm phim"
    st.session_state.page = previous

def navigate(page_name):
    st.session_state.page = page_name

# -------------------- OPTIONAL ACCOUNT / OPEN ACCESS --------------------
if "account_username" not in st.session_state:
    st.session_state.account_username = None
if "visitor_id" not in st.session_state:
    st.session_state.visitor_id = "guest_" + secrets.token_hex(8)
if "page" not in st.session_state:
    st.session_state.page = "Trang chủ"

# -------------------- SIDEBAR --------------------
st.sidebar.caption("Lưu trữ: SQLite cục bộ")

st.sidebar.markdown("""
<div class="sidebar-brand">
  <div class="sidebar-brand-mark"><span class="sidebar-brand-icon">✦</span><span>MOVIE REVIEW</span></div>
  <div class="sidebar-brand-sub">THE CINEMA EXPERIENCE</div>
</div>
""", unsafe_allow_html=True)

if st.session_state.account_username:
    st.sidebar.success(f"Đang đăng nhập: {st.session_state.account_username}")
    st.sidebar.caption("🔒 Dữ liệu cá nhân được lưu riêng theo tài khoản.")
    if st.sidebar.button("Đăng xuất", key="optional_logout", use_container_width=True):
        st.session_state.account_username = None
        st.session_state.visitor_id = "guest_" + secrets.token_hex(8)
        st.session_state.page = "Trang chủ"
        st.rerun()
else:
    st.sidebar.info("Bạn đang sử dụng với tư cách khách.")
    st.sidebar.caption("Dữ liệu cá nhân chỉ gắn với phiên hiện tại. Đăng nhập để lưu và đồng bộ lâu dài.")
    with st.sidebar.expander("Đăng nhập / Tạo tài khoản (không bắt buộc)", expanded=False):
        login_tab, register_tab = st.tabs(["Đăng nhập", "Tạo tài khoản"])
        with login_tab:
            with st.form("optional_login_form", clear_on_submit=False):
                login_username = st.text_input("Tên tài khoản", key="optional_login_username")
                login_password = st.text_input("Mật khẩu", type="password", key="optional_login_password")
                login_submit = st.form_submit_button("Đăng nhập", use_container_width=True)
            if login_submit:
                account = authenticate_account(login_username, login_password)
                if account:
                    merge_session_data_into_account(st.session_state.visitor_id, account)
                    st.session_state.account_username = account
                    st.session_state.page = "Trang chủ"
                    st.rerun()
                else:
                    st.error("Tên tài khoản hoặc mật khẩu không đúng.")
        with register_tab:
            with st.form("optional_register_form", clear_on_submit=False):
                register_username_value = st.text_input("Tên tài khoản mới", key="optional_register_username")
                register_password_value = st.text_input("Mật khẩu (ít nhất 8 ký tự)", type="password", key="optional_register_password")
                register_confirm_value = st.text_input("Nhập lại mật khẩu", type="password", key="optional_register_confirm")
                register_submit = st.form_submit_button("Tạo tài khoản", use_container_width=True)
            if register_submit:
                if register_password_value != register_confirm_value:
                    st.error("Mật khẩu nhập lại chưa khớp.")
                else:
                    ok, message = register_account(register_username_value, register_password_value)
                    if ok:
                        account = authenticate_account(register_username_value, register_password_value)
                        if account:
                            merge_session_data_into_account(st.session_state.visitor_id, account)
                            st.session_state.account_username = account
                            st.session_state.page = "Trang chủ"
                            st.success("Tạo tài khoản thành công.")
                            st.rerun()
                    else:
                        st.error(message)

st.sidebar.markdown("""
<div class="sidebar-profile">
  <div class="sidebar-profile-top">
    <div class="sidebar-avatar">◉</div>
    <div>
      <div class="sidebar-profile-title">KHÔNG GIAN CỦA BẠN</div>
      <div class="sidebar-profile-status">● Khám phá phim tự do</div>
    </div>
  </div>
  <div class="sidebar-profile-note">Bạn có thể sử dụng ứng dụng ngay. Đăng ký tài khoản nếu muốn đồng bộ hồ sơ và danh sách cá nhân qua các lần truy cập.</div>
</div>
<div class="sidebar-section-label">Khám phá & điều hướng</div>
""", unsafe_allow_html=True)

nav_items = [
    ("Trang chủ", "⌂"),
    ("Tìm kiếm phim", "⌕"),
    ("Chi tiết phim", "▤"),
    ("Cộng đồng review", "▱"),
    ("Thư viện của tôi", "▣"),
    ("Movie Battle", "⚔"),
    ("Gợi ý phim", "✧"),
    ("Hồ sơ cá nhân", "◎")
]
for page_name, page_icon in nav_items:
    st.sidebar.button(
        f"{page_icon}    {page_name}",
        key=f"nav_{page_name}",
        use_container_width=True,
        type="primary" if st.session_state.page == page_name else "secondary",
        on_click=navigate,
        args=(page_name,)
    )

st.sidebar.markdown("""
<div class="sidebar-foot">
  <div style="color:#DCC18A;font-weight:800;letter-spacing:1.5px;margin-bottom:5px;">MOVIE DISCOVERY</div>
  <div>Khám phá · Đánh giá · Lưu giữ</div>
  <div style="margin-top:8px;">Nguồn phim công khai · Không cần API Key</div>
</div>
""", unsafe_allow_html=True)

def render_dark_bar_chart(title, labels, values, colors, max_value=None, value_suffix=""):
    """Biểu đồ SVG tích hợp, không cần thư viện biểu đồ bên ngoài."""
    labels = [str(x) for x in labels]
    values = [float(v) for v in values]
    if not values:
        st.info("Chưa có dữ liệu để hiển thị biểu đồ.")
        return

    width, height = 1000, 360
    left, right, top, bottom = 62, 24, 34, 92
    plot_w, plot_h = width - left - right, height - top - bottom
    max_v = max(max_value if max_value is not None else max(values), 1)
    slot = plot_w / len(values)
    bar_w = min(58, slot * 0.62)

    parts = [
        '<div style="background:#111C2A;border:1px solid #344258;border-radius:14px;padding:10px 12px;overflow:hidden">',
        f'<div style="color:#F2D38A;font-weight:700;padding:5px 8px 10px">{html.escape(title)}</div>',
        f'<svg viewBox="0 0 {width} {height}" role="img" style="width:100%;height:auto;display:block;font-family:Arial,sans-serif">'
    ]

    for tick in range(6):
        val = max_v * tick / 5
        y = top + plot_h - (val / max_v) * plot_h
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width-right}" y2="{y:.1f}" stroke="#344258" stroke-width="1"/>')
        parts.append(f'<text x="{left-12}" y="{y+4:.1f}" text-anchor="end" fill="#D8E2EF" font-size="12">{val:g}</text>')

    for i, (label, value, color) in enumerate(zip(labels, values, colors)):
        xc = left + slot * (i + 0.5)
        bar_h = (value / max_v) * plot_h
        y = top + plot_h - bar_h
        x = xc - bar_w / 2
        parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{max(0,bar_h):.1f}" rx="6" fill="{color}" stroke="#F5E5B8" stroke-width="0.7"/>')
        parts.append(f'<text x="{xc:.1f}" y="{max(top+16,y-9):.1f}" text-anchor="middle" fill="#FFFFFF" font-size="13" font-weight="700">{value:g}{value_suffix}</text>')
        safe_label = html.escape(label[:24])
        ly = top + plot_h + 18
        parts.append(f'<text x="{xc:.1f}" y="{ly}" text-anchor="end" transform="rotate(-28 {xc:.1f} {ly})" fill="#E1E9F3" font-size="12">{safe_label}</text>')

    parts.append("</svg></div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


# -------------------- PAGE ACCESS CONTROL --------------------
# The anonymous visitor_id is assigned to the active Streamlit session above.
# Private tables are always queried with this ID, never with a public nickname.

# -------------------- HOME DISCOVERY FEED --------------------
def _rating_number(value):
    try:
        match = re.search(r"\d+(?:\.\d+)?", str(value))
        if match:
            number = float(match.group())
            return number / 10 if number > 10 else number
    except Exception:
        pass
    return 0.0

def _normalize_catalog_payload(payload, media_type="movie", source="StreamX Catalog"):
    items = unwrap_results(payload)
    normalized = []
    for raw in items:
        item = normalize_search_item(raw, media_type, source)
        if not item:
            continue
        item["type"] = media_type
        # A streaming catalogue should show actual titles with artwork, not event graphics.
        if not item.get("poster"):
            continue
        if not item.get("title") or item.get("title") == "Chưa có tên":
            continue
        normalized.append(item)
    unique = {}
    for item in normalized:
        key = item.get("imdb_id") or f'{item["type"]}:{item["title"].casefold()}:{item["year"]}'
        unique.setdefault(key, item)
    return list(unique.values())

@st.cache_data(ttl=21600, show_spinner=False)
def load_catalog_row(media_type, genre="", catalog_name="top", skip=0):
    params = {"skip": skip}
    if genre:
        params["genre"] = genre
    payload = api_get(f"catalog/{media_type}/{catalog_name}", params)
    return _normalize_catalog_payload(payload, media_type, f"StreamX {genre or catalog_name}")

@st.cache_data(ttl=21600, show_spinner=False)
def load_trending_movies():
    payload = api_get("trending/movie", {"limit": 40})
    return _normalize_catalog_payload(payload, "movie", "StreamX Trending")


COUNTRY_OPTIONS = {
    "Tất cả quốc gia": None,
    "Việt Nam": "VN",
    "Hàn Quốc": "KR",
    "Nhật Bản": "JP",
    "Hoa Kỳ": "US",
    "Trung Quốc": "CN",
    "Thái Lan": "TH",
    "Ấn Độ": "IN",
    "Anh": "GB",
    "Pháp": "FR",
    "Tây Ban Nha": "ES",
    "Canada": "CA", "Đức": "DE", "Ý": "IT", "Úc": "AU", "New Zealand": "NZ",
    "Brazil": "BR", "Mexico": "MX", "Argentina": "AR", "Indonesia": "ID",
    "Malaysia": "MY", "Singapore": "SG", "Philippines": "PH", "Hong Kong": "HK",
    "Đài Loan": "TW", "Thổ Nhĩ Kỳ": "TR", "Thụy Điển": "SE", "Na Uy": "NO",
    "Đan Mạch": "DK", "Hà Lan": "NL", "Thụy Sĩ": "CH", "Ba Lan": "PL",
    "Nga": "RU", "Ai Cập": "EG", "Nam Phi": "ZA"
}

def _country_values(meta_payload):
    meta = meta_payload.get("meta", meta_payload) if isinstance(meta_payload, dict) else {}
    facts = meta.get("facts", {}) if isinstance(meta, dict) else {}
    values = []
    for source in (
        facts.get("countries"), meta.get("countries"), meta.get("country"),
        meta.get("production_countries"), meta.get("productionCountries")
    ):
        for value in listify(source):
            if isinstance(value, dict):
                value = first(value, "iso_3166_1", "iso", "code", "name", "english_name", default="")
            if value:
                values.append(str(value).strip().casefold())
    return values

COUNTRY_ALIASES = {
    "VN": {"vn", "vietnam", "viet nam", "việt nam"},
    "KR": {"kr", "south korea", "korea, republic of", "korea"},
    "JP": {"jp", "japan"},
    "US": {"us", "usa", "united states", "united states of america"},
    "CN": {"cn", "china", "people's republic of china"},
    "TH": {"th", "thailand"},
    "IN": {"in", "india"},
    "GB": {"gb", "uk", "united kingdom", "great britain"},
    "FR": {"fr", "france"},
    "ES": {"es", "spain"},
    "CA": {"ca", "canada"}, "DE": {"de", "germany"}, "IT": {"it", "italy"},
    "AU": {"au", "australia"}, "NZ": {"nz", "new zealand"}, "BR": {"br", "brazil"},
    "MX": {"mx", "mexico"}, "AR": {"ar", "argentina"}, "ID": {"id", "indonesia"},
    "MY": {"my", "malaysia"}, "SG": {"sg", "singapore"}, "PH": {"ph", "philippines"},
    "HK": {"hk", "hong kong"}, "TW": {"tw", "taiwan"}, "TR": {"tr", "turkey", "türkiye"},
    "SE": {"se", "sweden"}, "NO": {"no", "norway"}, "DK": {"dk", "denmark"},
    "NL": {"nl", "netherlands"}, "CH": {"ch", "switzerland"}, "PL": {"pl", "poland"},
    "RU": {"ru", "russia"}, "EG": {"eg", "egypt"}, "ZA": {"za", "south africa"}
}


# Keyless, public country catalogue fallback. Wikidata is used because the
# StreamX popular catalogue is not a complete country-indexed catalogue.
WIKIDATA_COUNTRIES = {
    "VN": "Q881", "KR": "Q884", "JP": "Q17", "US": "Q30",
    "CN": "Q148", "TH": "Q869", "IN": "Q668", "GB": "Q145",
    "FR": "Q142", "ES": "Q29", "CA": "Q16",
    "DE": "Q183", "IT": "Q38", "AU": "Q408", "NZ": "Q664", "BR": "Q155",
    "MX": "Q96", "AR": "Q414", "ID": "Q252", "MY": "Q833", "SG": "Q334",
    "PH": "Q928", "HK": "Q8646", "TW": "Q865", "TR": "Q43", "SE": "Q34",
    "NO": "Q20", "DK": "Q35", "NL": "Q55", "CH": "Q39", "PL": "Q36",
    "RU": "Q159", "EG": "Q79", "ZA": "Q258"
}
WIKIDATA_GENRES = {
    "Tình cảm": "Q2221906", "Hành động": "Q188473", "Hài hước": "Q157443",
    "Kinh dị": "Q200092", "Phiêu lưu": "Q319221", "Khoa học viễn tưởng": "Q471839",
    "Tội phạm": "Q959790", "Chính kịch": "Q130232", "Hoạt hình": "Q202866",
    "Giả tưởng": "Q157394", "Bí ẩn & Giật gân": "Q2484376", "Tài liệu": "Q93204"
}

@st.cache_data(ttl=86400, show_spinner=False)
def load_wikidata_country_titles(country_code, genre_label="Tất cả thể loại", media_filter="Tất cả", limit=100):
    """Country-first query: exact genre first, then transparent country-level fallback."""
    country_qid = WIKIDATA_COUNTRIES.get(country_code)
    if not country_qid:
        return []
    genre_qid = WIKIDATA_GENRES.get(genre_label)
    if media_filter == "Phim điện ảnh":
        type_filter = "?item wdt:P31/wdt:P279* wd:Q11424 ."
    elif media_filter == "Phim bộ / Series":
        type_filter = "?item wdt:P31/wdt:P279* wd:Q5398426 ."
    else:
        type_filter = """{ ?item wdt:P31/wdt:P279* wd:Q11424 . }
          UNION { ?item wdt:P31/wdt:P279* wd:Q5398426 . }"""

    def run_query(require_genre):
        genre_filter = f"?item wdt:P136/wdt:P279* wd:{genre_qid} ." if require_genre and genre_qid else ""
        query = f"""
        SELECT DISTINCT ?item ?itemLabel ?date ?imdb ?image ?genreLabel WHERE {{
          ?item wdt:P495 wd:{country_qid} .
          {type_filter}
          {genre_filter}
          OPTIONAL {{ ?item wdt:P577 ?date . }}
          OPTIONAL {{ ?item wdt:P345 ?imdb . }}
          OPTIONAL {{ ?item wdt:P18 ?image . }}
          OPTIONAL {{ ?item wdt:P136 ?genre . }}
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "vi,en". }}
        }}
        ORDER BY DESC(?date)
        LIMIT {int(limit)}
        """
        response = requests.get(
            "https://query.wikidata.org/sparql",
            params={"query": query, "format": "json"},
            headers={"User-Agent": "MovieReviewCommunity/1.0", "Accept": "application/sparql-results+json"},
            timeout=22
        )
        response.raise_for_status()
        return response.json().get("results", {}).get("bindings", [])

    exact_genre = bool(genre_qid)
    try:
        bindings = run_query(True) if genre_qid else run_query(False)
        if not bindings and genre_qid:
            bindings = run_query(False)
            exact_genre = False
    except Exception:
        try:
            bindings = run_query(False)
            exact_genre = False
        except Exception:
            return []

    by_id = {}
    for row in bindings:
        title = row.get("itemLabel", {}).get("value", "").strip()
        if not title or title.lower().startswith("q"):
            continue
        qid = row.get("item", {}).get("value", "").rsplit("/", 1)[-1]
        date_value = row.get("date", {}).get("value", "")
        imdb_id = row.get("imdb", {}).get("value", "")
        image_url = row.get("image", {}).get("value", "")
        poster = ""
        if image_url:
            poster = "https://commons.wikimedia.org/wiki/Special:FilePath/" + quote(image_url.rsplit("/", 1)[-1])
        genre_name = row.get("genreLabel", {}).get("value", "")
        media_type = "series" if media_filter == "Phim bộ / Series" else "movie"
        item = {
            "id": imdb_id or f"wikidata:{qid}", "imdb_id": imdb_id or None,
            "type": media_type, "source": "Wikidata", "title": title,
            "year": date_value[:4] if date_value else "Chưa rõ",
            "poster": poster or None, "background": None, "overview": "",
            "rating": None, "genres": [genre_name] if genre_name else [],
            "match_note": "Khớp thể loại" if exact_genre else ("Bổ sung theo quốc gia; thể loại chưa được xác nhận" if genre_label != "Tất cả thể loại" else "Khớp quốc gia"),
            "raw": {"wikidata_id": qid, "country_code": country_code, "genre_label": genre_name}
        }
        key = imdb_id or f"{title.casefold()}:{item['year']}"
        by_id.setdefault(key, item)
    return list(by_id.values())

@st.cache_data(ttl=86400, show_spinner=False)
def get_title_country_codes(media_type, imdb_id):
    """Country metadata is enriched on demand and cached for 24 hours."""
    if not imdb_id:
        return []
    try:
        payload = api_get(f"meta/{media_type}/{imdb_id}", {"enrich": 1})
        return _country_values(payload)
    except Exception:
        return []

def filter_titles_by_country(items, country_code, max_check=80):
    if not country_code:
        return items
    aliases = COUNTRY_ALIASES.get(country_code, {country_code.casefold()})
    filtered = []
    # Only inspect a bounded set to keep country filtering responsive.
    candidates = items[:max_check]
    from concurrent.futures import ThreadPoolExecutor, as_completed
    # Sources that already include country metadata do not need another request.
    needs_lookup = []
    for item in candidates:
        raw = item.get("raw") or {}
        direct_values = [str(v).casefold() for v in listify(raw.get("country_codes")) if v]
        direct_values += [str(raw.get("countryOfOrigin") or "").casefold()]
        if any(v in aliases for v in direct_values):
            filtered.append(item)
        elif item.get("imdb_id"):
            needs_lookup.append(item)

    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = {
            pool.submit(get_title_country_codes, item.get("type", "movie"), item.get("imdb_id")): item
            for item in needs_lookup
        }
        for future in as_completed(futures):
            item = futures[future]
            try:
                values = future.result()
                if any(v in aliases for v in values):
                    filtered.append(item)
            except Exception:
                continue
    # Keep original catalogue order (trending/rating rank) after parallel lookup.
    ids = {item.get("imdb_id") for item in filtered}
    return [item for item in candidates if item.get("imdb_id") in ids]


@st.cache_data(ttl=21600, show_spinner=False)
def load_home_discovery():
    """Load movie and series genre shelves concurrently, with fail-soft handling."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    errors = []
    output = {}
    genres = {
        "Hành động": "Action",
        "Tình cảm": "Romance",
        "Phiêu lưu": "Adventure",
        "Hài hước": "Comedy",
        "Kinh dị": "Horror",
        "Khoa học viễn tưởng": "Sci-Fi",
        "Tội phạm": "Crime",
        "Chính kịch": "Drama",
        "Hoạt hình": "Animation",
        "Giả tưởng": "Fantasy",
        "Bí ẩn & Giật gân": "Thriller",
        "Tài liệu": "Documentary"
    }

    jobs = {
        "featured": ("trending/movie", {"limit": 40}, "movie", "Trending"),
        "movie_base": ("catalog/movie/top", {"skip": 0}, "movie", "Top movies"),
        "series_base": ("catalog/series/top", {"skip": 0}, "series", "Top series")
    }
    for label, genre in genres.items():
        jobs[f"{label}_movie"] = ("catalog/movie/top", {"skip": 0, "genre": genre}, "movie", genre)
        jobs[f"{label}_series"] = ("catalog/series/top", {"skip": 0, "genre": genre}, "series", genre)

    def fetch_one(key, job):
        endpoint, params, media_type, source = job
        payload = api_get(endpoint, params)
        return key, _normalize_catalog_payload(payload, media_type, f"StreamX {source}")

    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(fetch_one, key, job): key for key, job in jobs.items()}
        for future in as_completed(futures):
            key = futures[future]
            try:
                result_key, items = future.result()
                output[result_key] = items
            except Exception as exc:
                output[key] = []
                errors.append(f"{key}: {str(exc)[:140]}")

    movie_base = output.pop("movie_base", [])
    series_base = output.pop("series_base", [])
    base = movie_base + series_base
    base.sort(
        key=lambda m: (
            int(m["year"]) if str(m.get("year", "")).isdigit() else 0,
            _rating_number(m.get("rating"))
        ),
        reverse=True
    )
    output["newest"] = base[:36]
    output.setdefault("featured", [])
    if not output["featured"]:
        output["featured"] = base[:36]

    for label in genres:
        combined = output.pop(f"{label}_movie", []) + output.pop(f"{label}_series", [])
        unique = {}
        for item in combined:
            identity = item.get("imdb_id") or f'{item.get("type")}:{item.get("title","").casefold()}:{item.get("year")}'
            unique.setdefault(identity, item)
        output[label] = list(unique.values())[:40]

    return output, errors[:12]

def render_discovery_toolbar(discovery):
    st.markdown("### 🎛️ Lọc phim theo sở thích")
    with st.container(border=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            country = st.selectbox("Quốc gia sản xuất", list(COUNTRY_OPTIONS.keys()), key="home_country_filter")
        with c2:
            genre = st.selectbox(
                "Thể loại",
                ["Tất cả thể loại", "Tình cảm", "Hành động", "Hài hước", "Kinh dị",
                 "Phiêu lưu", "Khoa học viễn tưởng", "Tội phạm", "Chính kịch",
                 "Hoạt hình", "Giả tưởng", "Bí ẩn & Giật gân", "Tài liệu"],
                key="home_genre_filter"
            )
        with c3:
            media = st.selectbox("Định dạng", ["Tất cả", "Phim điện ảnh", "Phim bộ / Series"], key="home_media_filter")

    country_code = COUNTRY_OPTIONS[country]
    genre_key = genre if genre != "Tất cả thể loại" else None
    if genre_key:
        base = discovery.get(genre_key, [])
    else:
        base = discovery.get("newest", []) + discovery.get("featured", [])
    # De-duplicate merged rows before applying the remaining filters.
    merged = {}
    for item in base:
        identity = item.get("imdb_id") or f'{item.get("type")}:{item.get("title","").casefold()}:{item.get("year")}'
        merged.setdefault(identity, item)
    base = list(merged.values())

    if media == "Phim điện ảnh":
        base = [m for m in base if m.get("type") == "movie"]
    elif media == "Phim bộ / Series":
        base = [m for m in base if m.get("type") == "series"]

    if country_code:
        with st.spinner(f"Đang tìm phim tại {country} (các nguồn chạy song song; kết quả được lưu bộ nhớ đệm)..."):
            # First use country metadata on StreamX titles, then supplement from
            # Wikidata's country-of-origin catalogue instead of filtering only
            # the small trending/top list.
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=2) as pool:
                streamx_future = pool.submit(filter_titles_by_country, base, country_code, max_check=80)
                wikidata_future = pool.submit(
                    load_wikidata_country_titles,
                    country_code,
                    genre_label=genre if genre_key else "Tất cả thể loại",
                    media_filter=media,
                    limit=100
                )
                try:
                    streamx_matches = streamx_future.result()
                except Exception:
                    streamx_matches = []
                try:
                    wikidata_matches = wikidata_future.result()
                except Exception:
                    wikidata_matches = []
            combined = streamx_matches + wikidata_matches
            merged_country = {}
            for item in combined:
                identity = item.get("imdb_id") or f'{item.get("type")}:{item.get("title","").casefold()}:{item.get("year")}'
                merged_country.setdefault(identity, item)
            base = list(merged_country.values())

    if country_code or genre_key or media != "Tất cả":
        label_parts = [x for x in (country, genre if genre_key else None, media if media != "Tất cả" else None) if x]
        st.markdown("#### 🎬 Kết quả: " + " · ".join(label_parts))
        render_movie_grid(base[:24], "home_filter_result")
        if base and genre_key and any(item.get("match_note", "").startswith("Bổ sung theo quốc gia") for item in base):
            st.caption("Một số phim được bổ sung theo quốc gia vì nguồn dữ liệu chưa xác nhận đủ thể loại. Vui lòng kiểm tra thể loại thực tế trên từng phim.")
        if not base and country_code:
            st.info("Hiện nguồn công khai chưa có bản ghi phù hợp cho lựa chọn này. Hãy thử định dạng 'Tất cả' hoặc bỏ bộ lọc thể loại.")
        return True
    return False

def render_home_search():
    with st.form("home_catalog_search", clear_on_submit=False):
        c1, c2 = st.columns([5, 1])
        with c1:
            query = st.text_input("Tìm kiếm phim", placeholder="Tìm tên phim, series hoặc anime...")
        with c2:
            st.markdown("<div style='height:27px'></div>", unsafe_allow_html=True)
            submitted = st.form_submit_button("🔎 Tìm phim", use_container_width=True)
    if submitted:
        if len(query.strip()) < 2:
            st.warning("Nhập ít nhất 2 ký tự để tìm kiếm.")
        else:
            st.session_state.last_query = query.strip()
            st.session_state.search_category = "Tất cả"
            st.session_state.page = "Tìm kiếm phim"
            st.rerun()

def render_discovery_row(title, movies, key, note=None, limit=12):
    if not movies:
        return
    st.markdown(f"### {title}")
    if note:
        st.caption(note)
    # Dense poster shelf: 6 titles per line, with a second line when available.
    render_movie_grid(movies[:limit], key)

# -------------------- HOME --------------------
def render_hero():
    st.markdown("""
    <div class="hero">
      <div class="hero-kicker">Movie Review · Cinema Community</div>
      <h1>Mỗi bộ phim là một thế giới<br>đang chờ bạn khám phá.</h1>
      <p>Khám phá những câu chuyện đáng nhớ, tìm hiểu dàn diễn viên, lưu lại bộ phim yêu thích và chia sẻ góc nhìn của bạn cùng cộng đồng điện ảnh.</p>
      <div class="hero-note">DISCOVER &nbsp; · &nbsp; WATCHLIST &nbsp; · &nbsp; REVIEW &nbsp; · &nbsp; CONNECT</div>
    </div>
    """, unsafe_allow_html=True)

def render_movie_grid(movies, key_prefix="movie"):
    if not movies:
        st.info("Không tìm thấy phim phù hợp.")
        return
    cols_per_row = 6
    for start in range(0, len(movies), cols_per_row):
        cols = st.columns(cols_per_row)
        for col, movie in zip(cols, movies[start:start+cols_per_row]):
            with col:
                with st.container(border=True):
                    poster = movie.get("poster")
                    if poster:
                        st.image(poster, use_container_width=True)
                    else:
                        st.markdown('<div class="poster-placeholder">🎬</div>', unsafe_allow_html=True)
                    title = movie.get("title", "Chưa có tên")
                    st.markdown(f"**{title[:55]}**")
                    st.caption(f'{movie.get("year","")} · {movie.get("type","").upper()}')
                    if st.button("Xem chi tiết", key=f"{key_prefix}_{movie['id']}_{start}", use_container_width=True):
                        select_movie(movie)
                        st.rerun()

if st.session_state.page == "Trang chủ":
    render_hero()
    st.markdown("## Khám phá theo danh mục")
    st.caption("Chọn phim trực tiếp từ từng tuyển tập. Nhấn poster hoặc nút xem chi tiết để mở hồ sơ phim.")

    # Trang chủ chỉ tập trung vào khám phá theo danh mục.
    # Tìm kiếm chi tiết được thực hiện tại trang "Tìm kiếm phim".
    with st.spinner("Đang tải các danh mục phim..."):
        discovery, discovery_errors = load_home_discovery()

    if render_discovery_toolbar(discovery):
        st.divider()

    render_discovery_row(
        "🔥 Đang thịnh hành",
        discovery.get("featured", []),
        "home_trending",
        "Các tựa phim được xếp theo danh mục thịnh hành từ nguồn dữ liệu.",
        18
    )
    render_discovery_row(
        "🆕 Phim mới trong danh mục",
        discovery.get("newest", []),
        "home_recent",
        "Các phim có năm phát hành mới nhất trong danh mục phổ biến mà nguồn cung cấp; không phải lịch phát hành rạp trực tiếp.",
        18
    )

    shelves = [
        ("💥 Phim hành động", "Hành động"),
        ("🧭 Phiêu lưu", "Phiêu lưu"),
        ("😂 Hài hước", "Hài hước"),
        ("💕 Tình cảm", "Tình cảm"),
        ("👻 Kinh dị", "Kinh dị"),
        ("🚀 Khoa học viễn tưởng", "Khoa học viễn tưởng"),
        ("🕵️ Tội phạm", "Tội phạm"),
        ("🎭 Chính kịch", "Chính kịch"),
        ("🎨 Hoạt hình", "Hoạt hình"),
        ("🐉 Giả tưởng", "Giả tưởng"),
        ("🧩 Bí ẩn & Giật gân", "Bí ẩn & Giật gân"),
        ("🌍 Phim tài liệu", "Tài liệu")
    ]
    for title, key in shelves:
        render_discovery_row(title, discovery.get(key, []), f"home_genre_{key}", limit=18)

    # Previously explored titles remain available as a separate personal shelf.
    with db_connect() as conn:
        catalog_rows = conn.execute(
            "SELECT movie_json FROM movie_catalog ORDER BY updated_at DESC LIMIT 60"
        ).fetchall()
    catalog = []
    for row in catalog_rows:
        try:
            catalog.append(json.loads(row["movie_json"]))
        except Exception:
            continue
    if catalog:
        render_discovery_row(
            "🕘 Những phim bạn vừa khám phá",
            catalog,
            "home_recent_catalog",
            "Danh sách được tạo từ những phim đã tìm kiếm trong ứng dụng.",
            12
        )

    community_reviews = load_reviews(limit=5000)
    if not community_reviews.empty:
        st.markdown("### 💬 Cộng đồng đang đánh giá")
        for _, review_row in community_reviews.sort_values("created_at", ascending=False).head(4).iterrows():
            with st.container(border=True):
                st.markdown(f"**{html.escape(str(review_row['movie_name']))}** · ⭐ {review_row['score']}/10")
                st.write(f"{html.escape(str(review_row['reviewer']))}: {str(review_row['comment'])[:220]}")
                st.caption(str(review_row["created_at"]))

    if not any(discovery.get(k) for k in ("featured", "newest", "Hành động", "Phiêu lưu", "Hài hước", "Tình cảm", "Kinh dị")):
        st.warning("Nguồn danh mục phim hiện chưa phản hồi. Bạn vẫn có thể tìm phim bằng ô tìm kiếm phía trên.")
    elif discovery_errors:
        st.caption("Một số danh mục tạm thời chưa tải được. Các danh mục còn lại vẫn có thể sử dụng.")

    st.markdown("""
    <div class="muted">Phim được lấy từ danh mục công khai theo thể loại và xu hướng của StreamX/Cinemeta. Số lượng, poster, năm phát hành và rating phụ thuộc dữ liệu nguồn.</div>
    """, unsafe_allow_html=True)

# -------------------- SEARCH PAGE --------------------
elif st.session_state.page == "Tìm kiếm phim":
    render_hero()
    st.markdown("### 🔎 Tìm kiếm phim")
    with st.form("search_form"):
        c1, c2 = st.columns([3, 1])
        with c1:
            query = st.text_input("Tên phim", value=st.session_state.last_query, placeholder="Nhập tên phim...")
        with c2:
            category = st.selectbox(
                "Danh mục",
                ["Tất cả", "Phim điện ảnh", "Phim truyền hình", "Anime"],
                index=["Tất cả", "Phim điện ảnh", "Phim truyền hình", "Anime"].index(
                    st.session_state.get("search_category", "Tất cả")
                )
            )
        do_search = st.form_submit_button("Tìm kiếm phim", use_container_width=True)

    if do_search:
        if len(query.strip()) < 2:
            st.warning("Nhập ít nhất 2 ký tự để tìm kiếm.")
        else:
            st.session_state.last_query = query.strip()
            st.session_state.search_category = category
            with st.spinner("Đang tìm kiếm từ các nguồn dữ liệu..."):
                results, errors = search_movies(query.strip(), category)
            st.session_state.search_results = results
            st.session_state.search_errors = errors
            if results:
                save_movie_catalog(results)
            # Lưu lịch sử cho tài khoản đăng nhập; khách không được lưu vào hồ sơ tài khoản.
            if st.session_state.get("account_username"):
                save_search_history(
                    st.session_state.account_username,
                    query.strip(),
                    category,
                    len(results)
                )

    # Lịch sử chỉ hiển thị cho đúng tài khoản đang đăng nhập.
    signed_in_user = st.session_state.get("account_username")
    if signed_in_user:
        with st.expander("🕘 Lịch sử tìm kiếm của bạn", expanded=False):
            history_rows = load_search_history(signed_in_user, limit=12)
            if history_rows:
                st.caption("Chỉ tài khoản của bạn nhìn thấy lịch sử này.")
                for history in history_rows:
                    h1, h2, h3 = st.columns([4, 2, 1])
                    with h1:
                        st.markdown(f"**{history['query']}**")
                        st.caption(f"{history['category']} · {history['result_count']} kết quả")
                    with h2:
                        st.caption(history["searched_at"][:16].replace("T", " "))
                    with h3:
                        if st.button("Tìm lại", key=f"repeat_search_{history['id']}", use_container_width=True):
                            st.session_state.last_query = history["query"]
                            st.session_state.search_category = history["category"]
                            with st.spinner("Đang tìm lại..."):
                                again_results, again_errors = search_movies(history["query"], history["category"])
                            st.session_state.search_results = again_results
                            st.session_state.search_errors = again_errors
                            if again_results:
                                save_movie_catalog(again_results)
                            st.rerun()
                if st.button("Xóa lịch sử tìm kiếm", key="clear_my_search_history"):
                    clear_search_history(signed_in_user)
                    st.rerun()
            else:
                st.caption("Chưa có lịch sử tìm kiếm. Những lần tìm tiếp theo sẽ được lưu tại đây.")
    else:
        st.caption("Đăng nhập để lưu lịch sử tìm kiếm riêng và xem lại ở những lần truy cập sau.")

    results = st.session_state.search_results
    if st.session_state.last_query:
        st.markdown(f"### Kết quả cho: **{st.session_state.last_query}**")
    if results:
        st.caption(f"Tìm thấy {len(results)} kết quả")
        render_movie_grid(results, "search")
    elif st.session_state.last_query:
        st.info("Chưa có kết quả. Thử tên phim tiếng Anh hoặc tên gốc.")
    for err in st.session_state.get("search_errors", [])[:3]:
        st.caption(f"Nguồn tạm thời không phản hồi: {err}")

# -------------------- DETAIL PAGE --------------------
elif st.session_state.page == "Chi tiết phim":
    movie = st.session_state.selected_movie
    if not movie:
        st.info("Bạn chưa chọn phim. Hãy tìm kiếm và nhấn 'Xem chi tiết'.")
        if st.button("Đi đến tìm kiếm"):
            go_search()
            st.rerun()
    else:
        previous_page = st.session_state.get("previous_page", "Tìm kiếm phim")
        back_label = {
            "Trang chủ": "← Quay lại trang chủ",
            "Tìm kiếm phim": "← Quay lại kết quả tìm kiếm",
            "Cộng đồng review": "← Quay lại cộng đồng review"
        }.get(previous_page, "← Quay lại")

        if st.button(back_label, key="detail_back", use_container_width=False):
            back_from_detail()
            st.rerun()

        with st.spinner("Đang tải thông tin chi tiết..."):
            try:
                detail = get_details(movie)
            except Exception as exc:
                detail = movie
                st.warning(f"Không tải được toàn bộ thông tin chi tiết: {exc}")

        st.markdown(f"# {detail.get('title', movie['title'])}")
        watch_items = load_watchlist(current_owner_id())
        current_movie_key = str(movie.get("imdb_id") or movie.get("id"))
        already_saved = any(
            str(item.get("imdb_id") or item.get("id")) == current_movie_key
            for item in watch_items
        )
        if already_saved:
            st.success("Phim này đã có trong Watchlist riêng của trình duyệt này.")
        elif st.button("♡ Thêm vào Watchlist", key="add_watchlist_detail", type="primary"):
            add_to_watchlist(current_owner_id(), movie)
            st.success("Đã thêm phim vào Watchlist!")
            st.rerun()
        if detail.get("background"):
            st.image(detail["background"], use_container_width=True)

        left, right = st.columns([1, 2])
        with left:
            if detail.get("poster"):
                st.image(detail["poster"], use_container_width=True)
            else:
                st.markdown('<div class="poster-placeholder">🎬</div>', unsafe_allow_html=True)
                st.caption("Nguồn dữ liệu chưa cung cấp poster cho phim này.")
        with right:
            st.caption(f"Nguồn: {movie.get('source','StreamX')} · Loại: {movie.get('type','').upper()}")
            st.markdown(f"**Năm:** {detail.get('year','Chưa cập nhật')}")
            st.markdown(f"**Ngày phát hành:** {detail.get('released') or 'Chưa cập nhật'}")
            genres = detail.get("genres") or []
            if genres and isinstance(genres[0], dict):
                genres = [g.get("name", "") for g in genres]
            st.markdown(f"**Thể loại:** {', '.join(map(str, genres)) if genres else 'Chưa cập nhật'}")
            st.markdown(f"**Thời lượng:** {detail.get('runtime') or 'Chưa cập nhật'}")
            st.markdown(f"**Điểm tham khảo:** {detail.get('rating') or 'Chưa có dữ liệu'}")
            if detail.get("imdb_url"):
                st.markdown(f"[Xem trên IMDb]({detail['imdb_url']})")
            st.markdown("### Nội dung phim")
            st.write(detail.get("overview") or "Nguồn dữ liệu chưa có mô tả cho phim này.")

        st.markdown("### 🎭 Diễn viên")
        cast = detail.get("cast") or []
        if cast:
            cast_cols = st.columns(5)
            for i, person in enumerate(cast[:20]):
                with cast_cols[i % 5]:
                    if isinstance(person, dict):
                        pname = first(person, "name", "title", default="Chưa rõ")
                        character = first(person, "character", "role", default="")
                        pimage = first(person, "photo", "image", "avatar")
                        if pimage:
                            st.image(pimage, use_container_width=True)
                        st.markdown(f"**{pname}**")
                        if character:
                            st.caption(str(character))
                    else:
                        st.write(str(person))
        else:
            st.caption("Chưa có danh sách diễn viên từ nguồn dữ liệu.")

        videos = detail.get("videos") or []
        trailer_url = None
        for video in videos:
            if isinstance(video, dict):
                trailer_url = first(video, "trailer", "url", "link", "youtube")
                if trailer_url:
                    break
        st.markdown("### 🎞️ Trailer")
        if trailer_url:
            if "youtube.com" in trailer_url or "youtu.be" in trailer_url:
                st.video(trailer_url)
            else:
                st.markdown(f"[Mở trailer]({trailer_url})")
        else:
            st.caption("Chưa có trailer trong dữ liệu nguồn.")

        # Reviews
        movie_id = str(movie.get("imdb_id") or movie["id"])
        st.markdown("### ⭐ Đánh giá cộng đồng")
        reviews = load_reviews(movie_id)
        if not reviews.empty:
            avg = reviews["score"].mean()
            m1, m2, m3 = st.columns(3)
            m1.metric("Điểm trung bình", f"{avg:.1f}/10")
            m2.metric("Số lượt đánh giá", len(reviews))
            m3.metric("Điểm cao nhất", f"{reviews['score'].max()}/10")
            for _, row in reviews.iterrows():
                with st.container(border=True):
                    likes, liked_by_me, comment_rows = review_social_stats(row["id"], current_owner_id())
                    st.markdown(f"**{row['reviewer']}** · ⭐ {row['score']}/10")
                    if int(row.get("spoiler",0) or 0):
                        st.warning("Nội dung có thể tiết lộ tình tiết phim.")
                    st.write(row["comment"])
                    st.caption(f"{row['created_at']} · {likes} lượt thích")
                    if st.button(("♥ Đã thích" if liked_by_me else "♡ Thích review"),key=f"like_review_detail_{row['id']}"):
                        toggle_review_like(row["id"],current_owner_id()); st.rerun()
                    with st.expander(f"💬 Bình luận ({len(comment_rows)})"):
                        for cr in comment_rows:
                            st.markdown(f"**{cr['display_name']}** · {cr['comment']}")
                        with st.form(f"comment_form_detail_{row['id']}"):
                            cn=st.text_input("Tên hiển thị",key=f"comment_name_{row['id']}")
                            ct=st.text_input("Viết bình luận",key=f"comment_text_{row['id']}")
                            cs=st.form_submit_button("Gửi bình luận")
                        if cs:
                            if cn.strip() and ct.strip():
                                add_review_comment(row["id"],current_owner_id(),cn,ct)
                                st.rerun()
                            else: st.warning("Vui lòng nhập tên và bình luận.")
        else:
            st.info("Phim này chưa có đánh giá. Hãy là người đầu tiên review!")

        with st.form("review_form", clear_on_submit=True):
            st.markdown("#### Viết đánh giá của bạn")
            reviewer_name = st.text_input("Tên hiển thị công khai", placeholder="Ví dụ: Duy")
            score = st.slider("Bạn chấm phim bao nhiêu điểm?", 1, 10, 8)
            comment = st.text_area("Nhận xét", placeholder="Chia sẻ cảm nhận của bạn...")
            spoiler = st.checkbox("Review có tiết lộ tình tiết phim (spoiler)")
            public_consent = st.checkbox("Tôi đồng ý công khai tên hiển thị, điểm số và nội dung review trong cộng đồng.")
            send = st.form_submit_button("Gửi đánh giá")
        if send:
            if not reviewer_name.strip() or not comment.strip():
                st.error("Vui lòng nhập tên hiển thị và nội dung đánh giá.")
            elif not public_consent:
                st.warning("Bạn cần xác nhận review sẽ được công khai trước khi đăng.")
            else:
                try:
                    save_review(
                        movie_id,
                        detail.get("title", movie["title"]),
                        movie.get("source", "StreamX"),
                        reviewer_name.strip(),
                        score,
                        comment.strip(),
                        owner_id=current_owner_id(),
                        spoiler=spoiler
                    )
                    st.success("Đánh giá đã được đăng công khai!")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Không thể lưu đánh giá: {exc}")



# -------------------- MY LIBRARY PAGE --------------------
elif st.session_state.page == "Thư viện của tôi":
    render_hero()
    st.markdown("### ▣ Thư viện của tôi")
    st.caption("🔒 RIÊNG TƯ · Watchlist và bộ sưu tập chỉ hiển thị trong không gian của bạn, không xuất hiện trên trang cộng đồng.")
    if not st.session_state.account_username:
        st.info("Bạn đang dùng chế độ khách. Các thay đổi ở thư viện chỉ được gắn với phiên hiện tại; hãy đăng nhập hoặc tạo tài khoản để giữ chúng qua những lần truy cập sau.")
    st.caption("Quản lý phim muốn xem, phim đang xem, phim đã xem và những bộ sưu tập theo sở thích trong cùng một nơi.")
    watch_tab, collection_tab = st.tabs(["♡ Watchlist", "▦ Bộ sưu tập"])
    with watch_tab:
            render_hero()
            username = current_owner_id()
            st.markdown("### ♡ Watchlist của bạn")
            st.caption("🔒 Riêng tư: chỉ tài khoản của bạn nhìn thấy danh sách này.")
            items = load_watchlist(username)
            if not items:
                st.info("Watchlist đang trống. Hãy mở một bộ phim và chọn 'Thêm vào Watchlist'.")
            else:
                st.caption(f"{len(items)} phim trong Watchlist riêng của bạn")
                status_filter = st.selectbox(
                    "Lọc trạng thái", ["Tất cả", "Muốn xem", "Đang xem", "Đã xem"],
                    key="watchlist_filter"
                )
                shown = items if status_filter == "Tất cả" else [
                    item for item in items if item.get("_watch_status") == status_filter
                ]
                for idx in range(0, len(shown), 4):
                    cols = st.columns(4)
                    for col, item in zip(cols, shown[idx:idx+4]):
                        with col:
                            with st.container(border=True):
                                if item.get("poster"):
                                    st.image(item["poster"], use_container_width=True)
                                else:
                                    st.markdown('<div class="poster-placeholder">🎬</div>', unsafe_allow_html=True)
                                st.markdown(f"**{item.get('title','Chưa rõ')}**")
                                st.caption(f"{item.get('year','')} · {item.get('_watch_status','Muốn xem')}")
                                with st.popover("Quản lý"):
                                    new_status = st.selectbox(
                                        "Trạng thái",
                                        ["Muốn xem", "Đang xem", "Đã xem"],
                                        index=["Muốn xem", "Đang xem", "Đã xem"].index(item.get("_watch_status", "Muốn xem")),
                                        key=f"watch_status_{item['_watchlist_id']}"
                                    )
                                    if st.button("Lưu trạng thái", key=f"save_watch_{item['_watchlist_id']}"):
                                        update_watch_status(item["_watchlist_id"], new_status)
                                        st.rerun()
                                    if st.button("Xóa khỏi Watchlist", key=f"remove_watch_{item['_watchlist_id']}"):
                                        remove_from_watchlist(item["_watchlist_id"])
                                        st.rerun()
                                if st.button("Xem chi tiết", key=f"watch_detail_{item['_watchlist_id']}", use_container_width=True):
                                    select_movie(item)
                                    st.rerun()

        # -------------------- COLLECTIONS PAGE --------------------
    with collection_tab:
            render_hero()
            owner=current_owner_id()
            st.markdown("### ▦ Bộ sưu tập phim của bạn")
            st.caption("🔒 Riêng tư: bộ sưu tập và phim bên trong chỉ hiển thị với tài khoản của bạn.")
            st.caption("Tạo những danh sách theo gu riêng: phim cuối tuần, phim kinh điển, anime yêu thích...")
            with st.form("new_collection_form",clear_on_submit=True):
                cname=st.text_input("Tên bộ sưu tập",placeholder="Ví dụ: 10 phim phải xem một lần")
                cdesc=st.text_input("Mô tả ngắn",placeholder="Điều gì kết nối những bộ phim này?")
                csubmit=st.form_submit_button("＋ Tạo bộ sưu tập")
            if csubmit:
                if cname.strip():
                    create_collection(owner,cname,cdesc); st.success("Đã tạo bộ sưu tập."); st.rerun()
                else: st.warning("Hãy nhập tên bộ sưu tập.")
            collections=load_collections(owner)
            catalog_items=[]
            with db_connect() as conn:
                catalog_rows=conn.execute("SELECT movie_json FROM movie_catalog ORDER BY updated_at DESC LIMIT 100").fetchall()
            for row in catalog_rows:
                try: catalog_items.append(json.loads(row["movie_json"]))
                except Exception: pass
            if collections and catalog_items:
                st.markdown("#### Thêm phim vào bộ sưu tập")
                with st.form("collection_add_form"):
                    collection_labels=[f"{c['id']} · {c['name']}" for c in collections]
                    movie_labels=[f"{i} · {m.get('title')} ({m.get('year','')})" for i,m in enumerate(catalog_items)]
                    chosen_collection_label=st.selectbox("Chọn bộ sưu tập",collection_labels)
                    chosen_movie_label=st.selectbox("Chọn phim đã khám phá",movie_labels)
                    add_submit=st.form_submit_button("Thêm phim")
                if add_submit:
                    collection_id=int(chosen_collection_label.split(" · ",1)[0])
                    movie_index=int(chosen_movie_label.split(" · ",1)[0])
                    add_movie_to_collection(collection_id,catalog_items[movie_index]); st.success("Đã thêm phim."); st.rerun()
            elif not catalog_items:
                st.info("Hãy tìm kiếm phim trước để đưa phim vào bộ sưu tập.")
            if not collections:
                st.info("Bạn chưa tạo bộ sưu tập nào.")
            for collection in collections:
                with st.container(border=True):
                    st.markdown(f"### {collection['name']}")
                    st.caption(collection["description"] or "Bộ sưu tập cá nhân")
                    st.caption(f"{len(collection['movies'])} phim")
                    if collection["movies"]:
                        render_movie_grid(collection["movies"],f"collection_{collection['id']}")
                    if st.button("Xóa bộ sưu tập",key=f"delete_collection_{collection['id']}"):
                        delete_collection(collection["id"],owner); st.rerun()

# -------------------- MOVIE BATTLE PAGE --------------------
elif st.session_state.page == "Movie Battle":
    render_hero()
    st.markdown("### ⚔ Movie Battle")
    st.caption("Chọn phim trực tiếp từ poster, thiết lập nhu cầu xem và để ứng dụng phân tích hai lựa chọn.")

    battle_catalog = []
    with db_connect() as conn:
        rows = conn.execute(
            "SELECT movie_json FROM movie_catalog ORDER BY updated_at DESC LIMIT 200"
        ).fetchall()

    seen_battle_ids = set()
    for row in rows:
        try:
            movie = json.loads(row["movie_json"])
            movie_id = str(movie.get("imdb_id") or movie.get("id") or movie.get("title") or "")
            if movie_id and movie_id not in seen_battle_ids:
                battle_catalog.append(movie)
                seen_battle_ids.add(movie_id)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue

    # Kết quả tìm kiếm riêng của từng đối thủ được giữ trong session và ghép vào thư viện
    # để người dùng có thể chọn ngay, kể cả phim chưa từng được khám phá trước đó.
    for search_key in ("battle_remote_left", "battle_remote_right"):
        for movie in st.session_state.get(search_key, []):
            movie_id = str(movie.get("imdb_id") or movie.get("id") or movie.get("title") or "")
            if movie_id and movie_id not in seen_battle_ids:
                battle_catalog.insert(0, movie)
                seen_battle_ids.add(movie_id)

    if len(battle_catalog) < 2:
        st.info("Hãy tìm kiếm và khám phá ít nhất hai bộ phim để mở màn Movie Battle.")
    else:
        def _battle_id(movie):
            return str(movie.get("imdb_id") or movie.get("id") or movie.get("title") or "")

        def _battle_title(movie):
            return movie.get("title") or movie.get("name") or "Phim chưa có tên"

        def _battle_year(movie):
            return movie.get("year") or movie.get("release_year") or "Chưa rõ năm"

        def _battle_raw(movie):
            # Gộp dữ liệu tìm kiếm và metadata chi tiết từ Cinemeta/IMDb.
            raw = movie.get("raw")
            raw = raw if isinstance(raw, dict) else {}
            detail = movie.get("raw_detail")
            detail = detail if isinstance(detail, dict) else {}
            nested = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
            return {**raw, **nested, **detail}

        def _battle_value(movie, *keys):
            raw = _battle_raw(movie)
            for source in (movie, raw):
                for key in keys:
                    value = source.get(key)
                    if value not in (None, "", [], {}):
                        return value
            return None

        def _battle_genres(movie):
            value = _battle_value(movie, "genres", "genre", "genre_names")
            if isinstance(value, str):
                values = re.split(r"[,|/]", value)
            elif isinstance(value, (list, tuple, set)):
                values = value
            elif isinstance(value, dict):
                values = list(value.values())
            else:
                values = []
            result = []
            for item in values:
                if isinstance(item, dict):
                    item = item.get("name") or item.get("title") or item.get("genre")
                if item and str(item).strip():
                    result.append(str(item).strip())
            return result

        def _rating_to_10(raw_value, percent=False):
            if isinstance(raw_value, dict):
                raw_value = (
                    raw_value.get("average") or raw_value.get("value")
                    or raw_value.get("rating") or raw_value.get("score")
                )
            try:
                match = re.search(r"\d+(?:[.,]\d+)?", str(raw_value))
                if not match:
                    return None
                value = float(match.group(0).replace(",", "."))
                if percent:
                    if 0 <= value <= 100:
                        return value / 10
                    return None
                if 0 <= value <= 10:
                    return value
                if 0 <= value <= 100:
                    return value / 10
            except (TypeError, ValueError):
                pass
            return None

        def _external_rating_bundle(movie):
            # Audience ratings and critic approval/critic scores are different measures.
            imdb = _rating_to_10(_battle_value(movie, "imdbRating", "imdb_rating"))
            tmdb = _rating_to_10(_battle_value(movie, "vote_average", "tmdb_rating", "averageScore"))
            rt = _rating_to_10(
                _battle_value(movie, "tomatoMeter", "tomatometer", "rt_score", "rotten_tomatoes"),
                percent=True
            )
            meta = _rating_to_10(
                _battle_value(movie, "Metascore", "metascore", "critic_score"),
                percent=True
            )

            audience = []
            if imdb is not None:
                audience.append(("IMDb (khán giả)", imdb, 0.70))
            if tmdb is not None:
                audience.append(("TMDB (người dùng)", tmdb, 0.30))
            critics = []
            if rt is not None:
                critics.append(("Rotten Tomatoes (tỷ lệ tích cực)", rt, 0.60))
            if meta is not None:
                critics.append(("Metacritic (điểm phê bình)", meta, 0.40))

            groups = []
            if audience:
                weight = sum(x[2] for x in audience)
                groups.append((
                    "Điểm khán giả",
                    sum(value * w for _, value, w in audience) / weight,
                    0.70,
                    [(name, value) for name, value, _ in audience]
                ))
            if critics:
                weight = sum(x[2] for x in critics)
                groups.append((
                    "Điểm giới phê bình",
                    sum(value * w for _, value, w in critics) / weight,
                    0.30,
                    [(name, value) for name, value, _ in critics]
                ))

            if not groups:
                return None, []
            used_weight = sum(group[2] for group in groups)
            consensus = sum(group[1] * group[2] for group in groups) / used_weight
            sources = []
            for _, _, _, source_items in groups:
                sources.extend(source_items)
            return round(consensus, 2), sources

        def _battle_rating(movie):
            consensus, _ = _external_rating_bundle(movie)
            return consensus

        def _battle_runtime(movie):
            raw = _battle_value(
                movie, "runtime", "runtime_minutes", "duration",
                "duration_minutes", "runtimeMins", "length"
            )
            if isinstance(raw, dict):
                raw = raw.get("minutes") or raw.get("value")
            try:
                if isinstance(raw, (int, float)):
                    minutes = float(raw)
                else:
                    match = re.search(r"\d+(?:[.,]\d+)?", str(raw or ""))
                    if not match:
                        return None
                    minutes = float(match.group(0).replace(",", "."))
                return int(round(minutes)) if 1 <= minutes <= 600 else None
            except (TypeError, ValueError):
                return None

        def _poster(movie):
            return movie.get("poster") or movie.get("poster_url") or movie.get("image")

        def _short_id(movie):
            return hashlib.md5(_battle_id(movie).encode("utf-8")).hexdigest()[:10]

        # ----- Mood and time configuration -----
        mood_options = [
            "🎈 Vui vẻ, giải trí nhẹ nhàng",
            "😂 Hài hước, muốn được cười",
            "🧘 Thư giãn, chữa lành, dễ xem",
            "🔥 Hành động, nhịp độ nhanh",
            "😱 Hồi hộp, căng thẳng, nghẹt thở",
            "👻 Kinh dị, ma quái, giật gân",
            "💗 Lãng mạn, tình yêu",
            "🥹 Cảm xúc, sâu sắc, dễ đồng cảm",
            "🌱 Truyền cảm hứng, tích cực",
            "🧩 Bí ẩn, điều tra, đấu trí",
            "🚀 Khám phá, giả tưởng, khoa học viễn tưởng",
            "👨‍👩‍👧‍👦 Gia đình, ấm áp, phù hợp xem cùng nhau",
            "🎲 Không có yêu cầu cụ thể",
        ]
        duration_options = [
            "⚡ Dưới 60 phút",
            "🕐 60–90 phút",
            "🎬 90–120 phút",
            "🍿 120–150 phút",
            "🌙 Trên 150 phút",
            "♾️ Không giới hạn",
        ]

        st.markdown("#### 🎬 1. Bạn muốn xem phim như thế nào?")
        mood_col, duration_col = st.columns(2)
        with mood_col:
            battle_mood = st.selectbox(
                "Tâm trạng / trải nghiệm mong muốn",
                mood_options,
                index=7,
                key="battle_mood_choice",
                help="Chọn cảm xúc hoặc trải nghiệm bạn muốn. Ứng dụng sẽ đối chiếu với thể loại và nội dung phim.",
            )
            mood_descriptions = {
                "🎈 Vui vẻ, giải trí nhẹ nhàng": "Ưu tiên phim vui tươi, dễ xem, ít nặng nề.",
                "😂 Hài hước, muốn được cười": "Ưu tiên comedy, tình huống hài và nội dung dí dỏm.",
                "🧘 Thư giãn, chữa lành, dễ xem": "Ưu tiên câu chuyện ấm áp, nhẹ nhàng, feel-good.",
                "🔥 Hành động, nhịp độ nhanh": "Ưu tiên action, phiêu lưu, chiến đấu và tiết tấu nhanh.",
                "😱 Hồi hộp, căng thẳng, nghẹt thở": "Ưu tiên thriller, suspense, tội phạm và sinh tồn.",
                "👻 Kinh dị, ma quái, giật gân": "Ưu tiên horror, supernatural, paranormal và ám ảnh.",
                "💗 Lãng mạn, tình yêu": "Ưu tiên romance, tình yêu và các mối quan hệ.",
                "🥹 Cảm xúc, sâu sắc, dễ đồng cảm": "Ưu tiên drama, gia đình, mất mát và hành trình trưởng thành.",
                "🌱 Truyền cảm hứng, tích cực": "Ưu tiên câu chuyện vượt khó, hy vọng và phát triển bản thân.",
                "🧩 Bí ẩn, điều tra, đấu trí": "Ưu tiên mystery, detective, crime và plot twist.",
                "🚀 Khám phá, giả tưởng, khoa học viễn tưởng": "Ưu tiên sci-fi, fantasy, vũ trụ và thế giới mới.",
                "👨‍👩‍👧‍👦 Gia đình, ấm áp, phù hợp xem cùng nhau": "Ưu tiên family, animation và nội dung phù hợp nhiều lứa tuổi.",
                "🎲 Không có yêu cầu cụ thể": "Không ưu tiên tâm trạng; hệ thống tập trung vào đánh giá phim và dữ liệu có sẵn.",
            }
            st.caption(mood_descriptions[battle_mood])
        with duration_col:
            battle_duration = st.selectbox(
                "Khoảng thời gian bạn có",
                duration_options,
                index=5,
                key="battle_duration_choice",
                help="Nếu có dữ liệu runtime, phim phù hợp khoảng thời gian sẽ được ưu tiên.",
            )
            st.caption("Thời lượng chỉ ảnh hưởng điểm khi bạn giới hạn thời gian và phim có dữ liệu runtime.")

        # ----- Independent poster-based movie pickers for each opponent -----
        st.markdown("#### 🎞️ 2. Chọn hai bộ phim để so tài")
        st.caption("Mỗi đối thủ có ô tìm kiếm riêng. Tìm và chọn phim độc lập cho từng bên.")

        movie_by_id = {_battle_id(movie): movie for movie in battle_catalog}
        if "battle_selected_left" not in st.session_state:
            st.session_state["battle_selected_left"] = _battle_id(battle_catalog[0])
        if "battle_selected_right" not in st.session_state:
            st.session_state["battle_selected_right"] = _battle_id(battle_catalog[1])

        if st.session_state["battle_selected_left"] not in movie_by_id:
            st.session_state["battle_selected_left"] = _battle_id(battle_catalog[0])
        if st.session_state["battle_selected_right"] not in movie_by_id or (
            st.session_state["battle_selected_right"] == st.session_state["battle_selected_left"]
        ):
            st.session_state["battle_selected_right"] = next(
                _battle_id(movie) for movie in battle_catalog
                if _battle_id(movie) != st.session_state["battle_selected_left"]
            )

        def _render_opponent_picker(side, title, state_key, opponent_state_key):
            st.markdown(f"**{title}**")
            with st.form(f"battle_search_form_{side}", clear_on_submit=False):
                query = st.text_input(
                    f"Tìm phim cho {title}",
                    placeholder="Nhập tên phim, ví dụ: Conan, Batman, Mai...",
                    key=f"battle_search_{side}",
                )
                search_submitted = st.form_submit_button(
                    f"🔎 Tìm phim cho {title}",
                    use_container_width=True,
                )

            if search_submitted:
                if len(query.strip()) < 2:
                    st.warning("Nhập ít nhất 2 ký tự để tìm phim.")
                else:
                    with st.spinner(f"Đang tìm '{query.strip()}' từ các nguồn phim công khai..."):
                        remote_results, remote_errors = search_movies(query.strip(), "Tất cả")
                    st.session_state[f"battle_remote_{side}"] = remote_results
                    st.session_state[f"battle_remote_errors_{side}"] = remote_errors
                    if remote_results:
                        save_movie_catalog(remote_results)
                        st.session_state.pop("battle_run_result", None)
                        st.rerun()
                    elif remote_errors:
                        st.warning("Không kết nối được nguồn tìm phim lúc này. " + " | ".join(remote_errors[:2]))
                    else:
                        st.info("Không tìm thấy kết quả từ nguồn dữ liệu. Hãy thử tên phim khác.")

            query = st.session_state.get(f"battle_search_{side}", "")
            remote_results = st.session_state.get(f"battle_remote_{side}", [])
            local_matches = [
                movie for movie in battle_catalog
                if not query.strip()
                or query.casefold() in _battle_title(movie).casefold()
            ]
            # Ưu tiên kết quả online của lần tìm gần nhất ở đúng đối thủ này.
            candidates = remote_results if remote_results else local_matches
            if query.strip() and remote_results:
                candidates = [
                    movie for movie in remote_results
                    if query.casefold() in _battle_title(movie).casefold()
                ] or remote_results
            # Không cho chọn phim đang được sử dụng ở đối thủ còn lại.
            other_id = st.session_state[opponent_state_key]
            candidates = [movie for movie in candidates if _battle_id(movie) != other_id]

            selected_id = st.session_state[state_key]
            selected_movie = movie_by_id[selected_id]

            current_col = st.container(border=True)
            with current_col:
                st.caption("ĐANG CHỌN")
                if _poster(selected_movie):
                    st.image(_poster(selected_movie), width=150)
                else:
                    st.markdown("🎬 *Chưa có poster*")
                st.markdown(f"**{_battle_title(selected_movie)}** ({_battle_year(selected_movie)})")

            if query.strip() and not candidates:
                st.info(
                    f"Chưa có kết quả cho {title}. Nhấn nút 'Tìm phim cho {title}' "
                    "để tìm trên các nguồn phim công khai, hoặc thử từ khóa khác."
                )
                return

            if not query.strip():
                st.caption("Nhập tên phim rồi nhấn nút tìm kiếm để tra cứu nguồn phim công khai, hoặc chọn từ thư viện bên dưới.")
            if candidates:
                display_candidates = candidates[:12]
                cols = st.columns(3, gap="small")
                for idx, movie in enumerate(display_candidates):
                    movie_id = _battle_id(movie)
                    with cols[idx % 3]:
                        with st.container(border=True):
                            if _poster(movie):
                                st.image(_poster(movie), use_container_width=True)
                            else:
                                st.markdown(
                                    "<div style='height:145px;display:flex;align-items:center;"
                                    "justify-content:center;background:#172438;border-radius:10px'>🎬</div>",
                                    unsafe_allow_html=True
                                )
                            st.markdown(f"**{_battle_title(movie)}**")
                            st.caption(
                                f"{_battle_year(movie)} · ⭐ "
                                f"{_battle_rating(movie):.1f}" if _battle_rating(movie) is not None
                                else f"{_battle_year(movie)} · Chưa có rating"
                            )
                            if st.button(
                                "Chọn phim này",
                                key=f"battle_choose_{side}_{_short_id(movie)}",
                                use_container_width=True,
                                disabled=(movie_id == selected_id),
                            ):
                                st.session_state[state_key] = movie_id
                                st.session_state.pop("battle_run_result", None)
                                st.rerun()
                if len(candidates) > len(display_candidates):
                    st.caption(
                        f"Hiển thị {len(display_candidates)} trong {len(candidates)} kết quả. "
                        "Nhập thêm ký tự để thu hẹp danh sách."
                    )

        picker_left, picker_right = st.columns(2, gap="large")
        with picker_left:
            _render_opponent_picker(
                "left", "ĐỐI THỦ 1",
                "battle_selected_left", "battle_selected_right"
            )
        with picker_right:
            _render_opponent_picker(
                "right", "ĐỐI THỦ 2",
                "battle_selected_right", "battle_selected_left"
            )

        left_movie = movie_by_id[st.session_state["battle_selected_left"]]
        right_movie = movie_by_id[st.session_state["battle_selected_right"]]

        st.markdown("#### ⚔️ Cặp đấu hiện tại")
        pair_cols = st.columns(2, gap="large")
        for col, label, movie in (
            (pair_cols[0], "Đối thủ 1", left_movie),
            (pair_cols[1], "Đối thủ 2", right_movie),
        ):
            with col:
                if _poster(movie):
                    st.image(_poster(movie), width=130)
                st.markdown(f"**{label}: {_battle_title(movie)}**")
        st.markdown("---")
        if st.button("⚔️ BẮT ĐẦU SO TÀI", type="primary", use_container_width=True, key="battle_start_decision"):
            st.session_state["battle_run_result"] = {
                "left_id": _battle_id(left_movie),
                "right_id": _battle_id(right_movie),
                "mood": battle_mood,
                "duration": battle_duration,
            }

        run = st.session_state.get("battle_run_result")
        current_pair = (_battle_id(left_movie), _battle_id(right_movie))
        if run and (
            run.get("left_id"), run.get("right_id"), run.get("mood"), run.get("duration")
        ) == (*current_pair, battle_mood, battle_duration):

            mood_terms = {
                "🎈 Vui vẻ, giải trí nhẹ nhàng": {
                    "genres": {"comedy", "animation", "family", "adventure", "musical"},
                    "terms": {"fun", "funny", "comedy", "joy", "feel-good", "lighthearted", "hài", "vui", "giải trí", "ấm áp"}
                },
                "😂 Hài hước, muốn được cười": {
                    "genres": {"comedy"},
                    "terms": {"comedy", "humor", "funny", "satire", "parody", "hài", "hài hước", "châm biếm", "gây cười"}
                },
                "🧘 Thư giãn, chữa lành, dễ xem": {
                    "genres": {"family", "comedy", "animation", "romance"},
                    "terms": {"healing", "friendship", "hope", "kindness", "peaceful", "comfort", "chữa lành", "tình bạn", "hy vọng", "nhẹ nhàng", "ấm áp"}
                },
                "🔥 Hành động, nhịp độ nhanh": {
                    "genres": {"action", "adventure", "war", "science fiction"},
                    "terms": {"action", "fight", "battle", "chase", "warrior", "explosion", "hành động", "chiến đấu", "truy đuổi", "chiến tranh"}
                },
                "😱 Hồi hộp, căng thẳng, nghẹt thở": {
                    "genres": {"thriller", "crime", "mystery", "action"},
                    "terms": {"thriller", "suspense", "survival", "conspiracy", "danger", "tension", "căng thẳng", "sinh tồn", "nguy hiểm", "truy sát"}
                },
                "👻 Kinh dị, ma quái, giật gân": {
                    "genres": {"horror", "thriller"},
                    "terms": {"horror", "ghost", "demon", "haunted", "supernatural", "paranormal", "possession", "ma quỷ", "ma ám", "kinh dị", "ám ảnh"}
                },
                "💗 Lãng mạn, tình yêu": {
                    "genres": {"romance"},
                    "terms": {"romance", "love", "relationship", "wedding", "tình yêu", "lãng mạn", "hẹn hò", "hôn nhân"}
                },
                "🥹 Cảm xúc, sâu sắc, dễ đồng cảm": {
                    "genres": {"drama", "romance", "family", "biography", "history"},
                    "terms": {"loss", "family", "friendship", "memory", "sacrifice", "hope", "life", "identity", "tình yêu", "gia đình", "tình bạn", "hy sinh", "mất mát", "ký ức", "trưởng thành", "bi kịch", "cảm động"}
                },
                "🌱 Truyền cảm hứng, tích cực": {
                    "genres": {"drama", "biography", "sport", "documentary", "family"},
                    "terms": {"inspiring", "inspiration", "overcome", "dream", "achievement", "courage", "hope", "vượt khó", "ước mơ", "thành công", "nghị lực", "truyền cảm hứng"}
                },
                "🧩 Bí ẩn, điều tra, đấu trí": {
                    "genres": {"mystery", "crime", "thriller"},
                    "terms": {"mystery", "detective", "investigation", "murder", "secret", "puzzle", "twist", "điều tra", "phá án", "bí ẩn", "đấu trí", "manh mối"}
                },
                "🚀 Khám phá, giả tưởng, khoa học viễn tưởng": {
                    "genres": {"science fiction", "fantasy", "adventure", "animation"},
                    "terms": {"science fiction", "sci-fi", "fantasy", "space", "future", "alien", "parallel world", "magic", "vũ trụ", "giả tưởng", "khoa học viễn tưởng", "du hành", "khám phá"}
                },
                "👨‍👩‍👧‍👦 Gia đình, ấm áp, phù hợp xem cùng nhau": {
                    "genres": {"family", "animation", "comedy"},
                    "terms": {"family", "children", "parent", "friendship", "together", "gia đình", "trẻ em", "cha mẹ", "tình bạn", "ấm áp"}
                },
            }

            def _mood_fit(movie, mood):
                if mood == "🎲 Không có yêu cầu cụ thể":
                    return None, []
                rule = mood_terms[mood]
                genres = {g.casefold() for g in _battle_genres(movie)}
                genre_hits = sorted(genres & rule["genres"])
                overview = str(_battle_value(movie, "overview", "description", "plot", "synopsis") or "").casefold()
                keywords = _battle_value(movie, "keywords", "themes") or []
                if isinstance(keywords, (list, tuple, set)):
                    keyword_text = " ".join(
                        str(x.get("name", "")) if isinstance(x, dict) else str(x)
                        for x in keywords
                    ).casefold()
                else:
                    keyword_text = str(keywords).casefold()
                text = f"{overview} {keyword_text}"
                term_hits = sorted(term for term in rule["terms"] if term in text)
                if not genres and not overview and not keyword_text:
                    return None, []
                genre_score = min(10.0, len(genre_hits) * 3.2)
                text_score = min(10.0, len(term_hits) * 1.8)
                if genre_hits and (overview or keyword_text):
                    value = genre_score * 0.55 + text_score * 0.45
                elif genre_hits:
                    value = genre_score
                else:
                    value = text_score
                return round(value, 1), (genre_hits + term_hits)[:6]

            def _duration_fit(movie, choice):
                runtime = _battle_runtime(movie)
                if "Không giới hạn" in choice or runtime is None:
                    return 10.0, runtime, True
                if "Dưới 60" in choice:
                    ok = runtime < 60
                elif "60–90" in choice:
                    ok = 60 <= runtime < 90
                elif "90–120" in choice:
                    ok = 90 <= runtime <= 120
                elif "120–150" in choice:
                    ok = 120 < runtime <= 150
                elif "Trên 150" in choice:
                    ok = runtime > 150
                else:
                    ok = True
                return (10.0 if ok else 2.0), runtime, ok

            def _score_movie(movie, mood, duration):
                components = []
                rating = _battle_rating(movie)
                if rating is not None:
                    components.append(("Điểm đánh giá tổng hợp từ nguồn ngoài", rating, 0.55))

                mood_score, mood_signals = _mood_fit(movie, mood)
                if mood_score is not None:
                    components.append(("Tâm trạng", mood_score, 0.35))

                # Mức độ giàu thông tin nội dung: điểm dựa vào dữ liệu synopsis/keywords,
                # không coi độ dài mô tả là chất lượng phim.
                synopsis = str(_battle_value(movie, "overview", "description", "plot", "synopsis") or "").strip()
                keywords = _battle_value(movie, "keywords", "themes") or []
                if isinstance(keywords, (list, tuple, set)):
                    keyword_count = len(keywords)
                else:
                    keyword_count = len([x for x in re.split(r"[,; ]+", str(keywords)) if x])
                content_score = None
                if synopsis or keyword_count:
                    content_score = min(10.0, (5.0 if synopsis else 0.0) + min(keyword_count, 5) * 1.0)
                    components.append(("Thông tin nội dung", content_score, 0.10))

                profile = load_profile(current_owner_id())
                preferred = {str(x).casefold() for x in profile.get("favorite_genres", [])}
                genres = {g.casefold() for g in _battle_genres(movie)}
                if preferred and genres:
                    overlap = len(preferred & genres)
                    personal_score = 10.0 * overlap / max(1, len(preferred))
                    components.append(("Hợp gu cá nhân", personal_score, 0.20))

                duration_score, runtime, duration_ok = _duration_fit(movie, duration)
                if duration != "Không giới hạn" and runtime is not None:
                    components.append(("Thời lượng", duration_score, 0.15))

                if not components:
                    return None, [], mood_signals, runtime, duration_ok

                total_weight = sum(weight for _, _, weight in components)
                score = sum(value * weight for _, value, weight in components) / total_weight
                return round(score, 1), components, mood_signals, runtime, duration_ok

            # Lấy metadata chi tiết từ nguồn ngoài (Cinemeta/IMDb) trước khi chấm.
            # get_details có cache; nếu endpoint lỗi thì giữ dữ liệu tìm kiếm ban đầu.
            try:
                left_movie = get_details(left_movie) or left_movie
            except Exception:
                pass
            try:
                right_movie = get_details(right_movie) or right_movie
            except Exception:
                pass

            left_result = _score_movie(left_movie, battle_mood, battle_duration)
            right_result = _score_movie(right_movie, battle_mood, battle_duration)

            st.markdown("#### 🏆 Kết quả Movie Battle")
            st.caption(f"Nhu cầu xem: **{battle_mood}** · **{battle_duration}**")
            result_cols = st.columns(2, gap="large")
            for col, movie, result in (
                (result_cols[0], left_movie, left_result),
                (result_cols[1], right_movie, right_result),
            ):
                score, components, signals, runtime, duration_ok = result
                with col:
                    if _poster(movie):
                        st.image(_poster(movie), use_container_width=True)
                    st.markdown(f"**{_battle_title(movie)}**")
                    if score is None:
                        st.warning("Chưa đủ dữ liệu để chấm điểm đáng tin cậy.")
                    else:
                        st.metric("Điểm phù hợp", f"{score:.1f}/10")
                    if runtime is not None:
                        st.caption(f"Thời lượng: {runtime} phút")
                    elif battle_duration != "Không giới hạn":
                        st.caption("Chưa có dữ liệu thời lượng; không dùng tiêu chí này.")
                    if components:
                        with st.expander("Xem căn cứ chấm điểm"):
                            for name, value, weight in components:
                                st.write(f"**{name}:** {value:.1f}/10 · trọng số cơ sở {weight:.0%}")
                            ext_score, ext_sources = _external_rating_bundle(movie)
                            if ext_sources:
                                st.markdown("**Nguồn đánh giá bên ngoài (đã quy đổi về thang tham chiếu /10):**")
                                for source_name, source_value in ext_sources:
                                    st.write(f"- {source_name}: {source_value:.1f}/10")
                            else:
                                st.caption("Chưa có điểm IMDb/TMDB/Metacritic/Rotten Tomatoes từ metadata nguồn.")
                    if signals:
                        st.caption("Tín hiệu phù hợp: " + ", ".join(signals))

            st.markdown("---")
            left_score, right_score = left_result[0], right_result[0]
            if left_score is None and right_score is None:
                st.warning("Hai phim chưa có đủ dữ liệu rating, thể loại hoặc nội dung để so sánh. Hãy chọn phim khác có thông tin đầy đủ hơn.")
            elif left_score is None:
                st.success(f"🏆 **Nên xem: {_battle_title(right_movie)}** — phim này có dữ liệu phù hợp để đánh giá hơn.")
            elif right_score is None:
                st.success(f"🏆 **Nên xem: {_battle_title(left_movie)}** — phim này có dữ liệu phù hợp để đánh giá hơn.")
            elif abs(left_score - right_score) < 0.15:
                st.info("🤝 Hai phim có mức độ phù hợp gần như ngang nhau. Bạn có thể chọn theo sở thích cá nhân.")
            else:
                winner = left_movie if left_score > right_score else right_movie
                difference = abs(left_score - right_score)
                st.success(
                    f"🏆 **Ứng dụng đề xuất bạn xem: {_battle_title(winner)}** "
                    f"với mức phù hợp cao hơn {difference:.1f} điểm."
                )
            st.caption(
                "Điểm được tính từ dữ liệu thực có của phim. Những tiêu chí thiếu dữ liệu sẽ được bỏ qua "
                "và trọng số còn lại tự chuẩn hóa; ứng dụng không gán điểm giả khi không có căn cứ."
            )
# -------------------- RECOMMENDATIONS PAGE --------------------
elif st.session_state.page == "Gợi ý phim":
    render_hero()
    username = current_owner_id()
    st.markdown("### ✨ Gợi ý phim dành cho bạn")
    profile = load_profile(username)
    if not profile["favorite_genres"]:
        st.info("Hãy chọn thể loại yêu thích trong Hồ sơ cá nhân để nhận gợi ý phù hợp hơn.")
    recommendations = get_recommendations(username)
    if recommendations:
        st.caption("Gợi ý dựa trên thể loại yêu thích, lịch sử review của tài khoản, rating có sẵn và thư viện phim đã khám phá. Phim đã review hoặc nằm trong Watchlist được loại khỏi danh sách.")
        render_movie_grid(recommendations, "recommend")
    else:
        st.info("Chưa đủ dữ liệu để gợi ý. Hãy chọn thể loại yêu thích và tìm kiếm thêm phim.")

# -------------------- PROFILE PAGE --------------------
elif st.session_state.page == "Hồ sơ cá nhân":
    render_hero()
    username = current_owner_id()
    st.markdown("### 👤 Hồ sơ cá nhân")
    st.caption("🔒 RIÊNG TƯ · Hồ sơ, sở thích và thống kê cá nhân không được công khai cho cộng đồng.")
    if not st.session_state.account_username:
        st.info("Bạn đang xem hồ sơ khách. Thông tin cá nhân chỉ lưu theo phiên hiện tại; đăng nhập hoặc tạo tài khoản để lưu hồ sơ lâu dài.")
    profile = load_profile(username)
    with st.form("profile_form"):
        st.text_input("Mã hồ sơ ẩn danh", value=f"{username[:8]}••••", disabled=True)
        bio = st.text_area("Giới thiệu", value=profile["bio"], placeholder="Một chút về gu điện ảnh của bạn...")
        genres = st.multiselect(
            "Thể loại yêu thích",
            ["Action", "Adventure", "Animation", "Comedy", "Crime", "Drama",
             "Fantasy", "Horror", "Mystery", "Romance", "Sci-Fi", "Thriller"],
            default=profile["favorite_genres"]
        )
        save_profile_button = st.form_submit_button("Lưu hồ sơ")
    if save_profile_button:
        save_profile(username, bio.strip(), genres)
        st.success("Đã lưu hồ sơ!")
        st.rerun()

    my_reviews = load_reviews(limit=5000)
    if not my_reviews.empty:
        my_reviews = my_reviews[
            my_reviews["owner_id"].fillna("").astype(str) == username
        ]
    else:
        my_reviews = pd.DataFrame()
    watch_items = load_watchlist(username)
    p1, p2, p3 = st.columns(3)
    p1.metric("Lượt đánh giá", len(my_reviews))
    p2.metric("Phim trong Watchlist", len(watch_items))
    p3.metric(
        "Điểm trung bình đã chấm",
        f"{my_reviews['score'].mean():.1f}/10" if not my_reviews.empty else "—"
    )
    st.metric("Bộ sưu tập đã tạo",len(load_collections(username)))
    st.markdown("#### 📝 Review gần đây")
    if my_reviews.empty:
        st.caption("Bạn chưa có đánh giá nào với tên hiển thị này.")
    else:
        for _, row in my_reviews.head(10).iterrows():
            with st.container(border=True):
                st.markdown(f"**{row['movie_name']}** · ⭐ {row['score']}/10")
                st.write(row["comment"])
                st.caption(row["created_at"])

# -------------------- COMMUNITY PAGE --------------------
elif st.session_state.page == "Cộng đồng review":
    render_hero()
    st.markdown("### 💬 Đánh giá từ cộng đồng")
    st.caption("🌐 CÔNG KHAI · Review đã đăng, điểm số, tên hiển thị, lượt thích và bình luận được chia sẻ với mọi người.")
    st.caption("Thông tin hồ sơ riêng tư, Watchlist, bộ sưu tập và ghi chú cá nhân không được hiển thị tại đây.")
    all_reviews = load_reviews(limit=5000)
    if all_reviews.empty:
        st.info("Chưa có đánh giá nào. Hãy tìm một bộ phim và viết review đầu tiên!")
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("Tổng đánh giá", len(all_reviews))
        c2.metric("Số phim được review", all_reviews["movie_id"].nunique())
        c3.metric("Điểm trung bình", f"{all_reviews['score'].mean():.1f}/10")

        movie_options = ["Tất cả phim"] + sorted(all_reviews["movie_name"].dropna().unique().tolist())
        selected_name = st.selectbox("Lọc theo phim", movie_options)
        filtered = all_reviews if selected_name == "Tất cả phim" else all_reviews[all_reviews["movie_name"] == selected_name]

        # Phân nhóm màu theo yêu cầu:
        # 1–3: đỏ (thấp); 4–7: vàng (trung bình); 8–10: xanh (cao).
        def score_color(value):
            value = int(value)
            if 1 <= value <= 3:
                return "#E05252"
            if 4 <= value <= 7:
                return "#EBC978"
            return "#36B89A"

        st.markdown("#### 📊 Phân phối điểm đánh giá")
        score_counts = (
            filtered["score"].value_counts().sort_index()
            .reindex(range(1, 11), fill_value=0)
        )
        score_labels = [f"{score}/10" for score in score_counts.index]
        score_values = score_counts.values.tolist()
        score_colors = [score_color(int(score)) for score in score_counts.index]

        render_dark_bar_chart(
            "Số lượt đánh giá theo mức điểm",
            score_labels, score_values, score_colors,
            max_value=max(score_values + [1])
        )

        st.markdown("#### 👥 Điểm đánh giá theo từng lượt")
        review_chart = filtered.reset_index(drop=True).copy()
        review_labels = [
            f"{str(row['reviewer'])[:14]} · Lượt {i+1}"
            for i, row in review_chart.iterrows()
        ]
        review_values = review_chart["score"].astype(int).tolist()
        review_colors = [score_color(v) for v in review_values]

        render_dark_bar_chart(
            "Điểm của từng lượt đánh giá",
            review_labels, review_values, review_colors,
            max_value=10, value_suffix="/10"
        )

        for _, row in filtered.iterrows():
            with st.container(border=True):
                likes, liked_by_me, comment_rows = review_social_stats(row["id"],current_owner_id())
                st.markdown(f"**{row['movie_name']}** · ⭐ {row['score']}/10")
                st.caption(f"Review bởi {row['reviewer']} · {row['created_at']}")
                if int(row.get("spoiler",0) or 0):
                    with st.expander("⚠ Nội dung có spoiler — nhấn để xem"):
                        st.write(row["comment"])
                else:
                    st.write(row["comment"])
                lc1,lc2=st.columns([1,4])
                with lc1:
                    if st.button(("♥" if liked_by_me else "♡")+f" {likes}",key=f"community_like_{row['id']}"):
                        toggle_review_like(row["id"],current_owner_id()); st.rerun()
                with st.expander(f"💬 Bình luận ({len(comment_rows)})"):
                    for cr in comment_rows:
                        st.markdown(f"**{cr['display_name']}** · {cr['comment']}")
                    with st.form(f"community_comment_form_{row['id']}"):
                        cn=st.text_input("Tên hiển thị",key=f"community_cn_{row['id']}")
                        ct=st.text_input("Bình luận",key=f"community_ct_{row['id']}")
                        cs=st.form_submit_button("Gửi")
                    if cs:
                        if cn.strip() and ct.strip():
                            add_review_comment(row["id"],current_owner_id(),cn,ct); st.rerun()
                        else: st.warning("Vui lòng nhập tên và bình luận.")

        csv_data = filtered.to_csv(index=False).encode("utf-8-sig")
        st.download_button("⬇️ Xuất review CSV", csv_data, "movie_reviews.csv", "text/csv")

# -------------------- FOOTER --------------------
st.markdown("""
<div class="muted" style="text-align:center;padding:28px 0 8px">
Movie Review · Discover · Review · Collect<br>
Metadata by StreamX and its upstream providers. Images and metadata belong to their respective owners.
</div>
""", unsafe_allow_html=True)
