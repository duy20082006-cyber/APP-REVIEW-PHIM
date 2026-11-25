import streamlit as st
import requests
import sqlite3
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
    response = requests.get(url, params=params or {}, headers=HEADERS, timeout=25)
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
def db_connect():
    conn = sqlite3.connect(str(DB_PATH), timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    return conn

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
        migrated = conn.execute(
            "SELECT meta_value FROM app_meta WHERE meta_key='private_data_reset_v1'"
        ).fetchone()
        if not migrated:
            conn.execute("DELETE FROM profiles")
            conn.execute("DELETE FROM watchlist")
            conn.execute(
                "INSERT INTO app_meta(meta_key,meta_value) VALUES('private_data_reset_v1','done')"
            )
        conn.commit()

init_db()


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
            return pd.read_sql_query(
                "SELECT * FROM reviews WHERE movie_id=? ORDER BY id DESC LIMIT ?",
                conn, params=(str(movie_id), limit)
            )
        return pd.read_sql_query(
            "SELECT * FROM reviews ORDER BY id DESC LIMIT ?",
            conn, params=(limit,)
        )


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

def get_recommendations(username, limit=20):
    """Gợi ý đơn giản từ thể loại yêu thích và phim đã chấm điểm cao."""
    profile = load_profile(username)
    preferred = set(profile["favorite_genres"])

    reviews = load_reviews(limit=5000)
    if not reviews.empty:
        mine = reviews[reviews["reviewer"].astype(str).str.casefold() == username.casefold()]
        # Tên phim/điểm được dùng để ưu tiên hồ sơ; thể loại lấy từ catalog nếu có.
        liked_ids = set(mine[mine["score"] >= 8]["movie_id"].astype(str))
    else:
        liked_ids = set()

    watch_items = load_watchlist(username)
    excluded = {
        str(item.get("imdb_id") or item.get("id"))
        for item in watch_items
    }
    candidates = []
    with db_connect() as conn:
        rows = conn.execute("SELECT movie_id,movie_json FROM movie_catalog").fetchall()

    for row in rows:
        try:
            movie = json.loads(row["movie_json"])
        except Exception:
            continue
        movie_id = str(movie.get("imdb_id") or movie.get("id"))
        if movie_id in excluded:
            continue
        genres = movie.get("genres") or []
        if genres and isinstance(genres[0], dict):
            genres = [g.get("name", "") for g in genres]
        genre_set = {str(g).casefold() for g in genres}
        overlap = len({g.casefold() for g in preferred} & genre_set)
        rating = movie.get("rating")
        try:
            rating_score = float(rating) if rating is not None else 0
        except (TypeError, ValueError):
            rating_score = 0
        score = overlap * 3 + (1 if rating_score >= 7 else 0)
        if score > 0:
            candidates.append((score, movie))
    candidates.sort(key=lambda x: x[0], reverse=True)
    return [movie for _, movie in candidates[:limit]]

# -------------------- SEARCH --------------------
@st.cache_data(ttl=600, show_spinner=False)
def search_movies(query, category):
    found = []
    errors = []

    # IMDb suggestion endpoint: broad title coverage and poster suggestions.
    try:
        payload = api_get("imdb/search", {"q": query})
        for raw in unwrap_results(payload):
            item = normalize_search_item(raw, "movie", "IMDb suggestion")
            if item:
                found.append(item)
    except Exception as exc:
        errors.append(f"IMDb search: {exc}")

    # Cinemeta search: movie and series catalogues.
    types = ["movie", "series"] if category == "Tất cả" else (
        ["movie"] if category == "Phim điện ảnh" else ["series"]
    )
    if category == "Anime":
        types = []
    for media_type in types:
        try:
            payload = api_get("search", {"q": query, "type": media_type})
            for raw in unwrap_results(payload):
                item = normalize_search_item(raw, media_type, "Cinemeta")
                if item:
                    found.append(item)
        except Exception as exc:
            errors.append(f"Cinemeta {media_type}: {exc}")

    # AniList-backed anime endpoint.
    if category in ("Tất cả", "Anime"):
        try:
            payload = api_get("anime/search", {"q": query})
            for raw in unwrap_results(payload):
                item = normalize_search_item(raw, "anime", "AniList")
                if item:
                    item["type"] = "anime"
                    found.append(item)
        except Exception as exc:
            errors.append(f"AniList: {exc}")

    # De-duplicate by stable IMDb id, otherwise normalized title/year/type.
    unique = {}
    for item in found:
        key = item["imdb_id"] or f'{item["type"]}:{item["title"].casefold()}:{item["year"]}'
        if key not in unique:
            unique[key] = item
        else:
            old = unique[key]
            for field in ("poster", "background", "overview", "rating", "imdb_id"):
                if not old.get(field) and item.get(field):
                    old[field] = item[field]

    return list(unique.values())[:40], errors

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

# -------------------- SIDEBAR --------------------
st.sidebar.markdown("""
<div class="sidebar-brand">
  <div class="sidebar-brand-mark"><span class="sidebar-brand-icon">✦</span><span>MOVIE REVIEW</span></div>
  <div class="sidebar-brand-sub">THE CINEMA EXPERIENCE</div>
</div>
<div class="sidebar-profile">
  <div class="sidebar-profile-top">
    <div class="sidebar-avatar">◉</div>
    <div>
      <div class="sidebar-profile-title">KHÔNG GIAN CỦA BẠN</div>
      <div class="sidebar-profile-status">● Hồ sơ đã sẵn sàng</div>
    </div>
  </div>
  <div class="sidebar-profile-note">Trải nghiệm cá nhân hóa · Không cần đăng ký hoặc đăng nhập</div>
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
    cols_per_row = 5
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
    visitor = st.session_state.visitor_id
    catalog_rows = []
    with db_connect() as conn:
        catalog_rows = conn.execute("SELECT movie_json FROM movie_catalog ORDER BY updated_at DESC LIMIT 80").fetchall()
    catalog = []
    for row in catalog_rows:
        try: catalog.append(json.loads(row["movie_json"]))
        except Exception: pass
    watch_items_home = load_watchlist(visitor)
    reviews_home = load_reviews(limit=30)
    total_reviews_home = len(load_reviews(limit=5000))
    h1,h2,h3 = st.columns(3)
    h1.metric("Phim đã khám phá", len(catalog))
    h2.metric("Review cộng đồng", total_reviews_home)
    h3.metric("Trong Watchlist", len(watch_items_home))
    st.markdown("### 🎞️ Featured discovery")
    if catalog:
        featured = catalog[0]
        fc1,fc2 = st.columns([1,2])
        with fc1:
            if featured.get("poster"): st.image(featured["poster"],use_container_width=True)
            else: st.markdown('<div class="poster-placeholder">🎬</div>',unsafe_allow_html=True)
        with fc2:
            st.markdown('<div class="eyebrow">CURATED FOR MOVIE LOVERS</div>',unsafe_allow_html=True)
            st.markdown(f'<div class="featured-title">{html.escape(featured.get("title","Khám phá điện ảnh"))}</div>',unsafe_allow_html=True)
            st.markdown(f'<div class="featured-copy">{html.escape((featured.get("overview") or "Khám phá bộ phim này, đọc cảm nhận từ cộng đồng và lưu vào bộ sưu tập cá nhân.")[:420])}</div>',unsafe_allow_html=True)
            st.caption(f'{featured.get("year","")} · {featured.get("type","").upper()} · {featured.get("source","")}')
            if st.button("Khám phá phim nổi bật",key="home_featured_open",type="primary"):
                select_movie(featured); st.rerun()
    else:
        st.info("Bắt đầu tìm kiếm phim để xây dựng thư viện khám phá của bạn. Các phim đã tìm sẽ xuất hiện tại đây.")
    if catalog:
        st.markdown("### 🔥 Khám phá gần đây")
        render_movie_grid(catalog[:10],"home_catalog")
    if not reviews_home.empty:
        st.markdown("### 💬 Tiếng nói cộng đồng")
        for _, rr in reviews_home.head(3).iterrows():
            with st.container(border=True):
                st.markdown(f"**{rr['movie_name']}** · ⭐ {rr['score']}/10")
                st.write(f"{rr['reviewer']}: {rr['comment'][:220]}")
                st.caption(rr["created_at"])
    st.markdown("### 🔎 Tìm phim nhanh")
    with st.form("home_search_form"):
        home_query = st.text_input("Nhập tên phim", placeholder="Ví dụ: Parasite, Mai, Squid Game, Naruto...")
        home_category = st.selectbox("Thể loại nội dung", ["Tất cả", "Phim điện ảnh", "Phim truyền hình", "Anime"])
        submitted = st.form_submit_button("Tìm kiếm")
    if submitted:
        if len(home_query.strip()) < 2:
            st.warning("Vui lòng nhập ít nhất 2 ký tự.")
        else:
            st.session_state.last_query = home_query.strip()
            st.session_state.search_category = home_category
            st.session_state.page = "Tìm kiếm phim"
            st.rerun()

    st.markdown("### ⭐ Khám phá phim")
    st.caption("Bạn có thể tìm phim theo tên ở ô tìm kiếm phía trên.")
    st.markdown("""
    <div class="muted">Movie Review sử dụng các nguồn dữ liệu công khai không yêu cầu API key. Dữ liệu và ảnh phụ thuộc vào khả năng cung cấp của từng nguồn.</div>
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
        watch_items = load_watchlist(st.session_state.visitor_id)
        current_movie_key = str(movie.get("imdb_id") or movie.get("id"))
        already_saved = any(
            str(item.get("imdb_id") or item.get("id")) == current_movie_key
            for item in watch_items
        )
        if already_saved:
            st.success("Phim này đã có trong Watchlist riêng của trình duyệt này.")
        elif st.button("♡ Thêm vào Watchlist", key="add_watchlist_detail", type="primary"):
            add_to_watchlist(st.session_state.visitor_id, movie)
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
                    likes, liked_by_me, comment_rows = review_social_stats(row["id"], st.session_state.visitor_id)
                    st.markdown(f"**{row['reviewer']}** · ⭐ {row['score']}/10")
                    if int(row.get("spoiler",0) or 0):
                        st.warning("Nội dung có thể tiết lộ tình tiết phim.")
                    st.write(row["comment"])
                    st.caption(f"{row['created_at']} · {likes} lượt thích")
                    if st.button(("♥ Đã thích" if liked_by_me else "♡ Thích review"),key=f"like_review_detail_{row['id']}"):
                        toggle_review_like(row["id"],st.session_state.visitor_id); st.rerun()
                    with st.expander(f"💬 Bình luận ({len(comment_rows)})"):
                        for cr in comment_rows:
                            st.markdown(f"**{cr['display_name']}** · {cr['comment']}")
                        with st.form(f"comment_form_detail_{row['id']}"):
                            cn=st.text_input("Tên hiển thị",key=f"comment_name_{row['id']}")
                            ct=st.text_input("Viết bình luận",key=f"comment_text_{row['id']}")
                            cs=st.form_submit_button("Gửi bình luận")
                        if cs:
                            if cn.strip() and ct.strip():
                                add_review_comment(row["id"],st.session_state.visitor_id,cn,ct)
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
            send = st.form_submit_button("Gửi đánh giá")
        if send:
            if not reviewer_name.strip() or not comment.strip():
                st.error("Vui lòng nhập tên hiển thị và nội dung đánh giá.")
            else:
                try:
                    save_review(
                        movie_id,
                        detail.get("title", movie["title"]),
                        movie.get("source", "StreamX"),
                        reviewer_name.strip(),
                        score,
                        comment.strip(),
                        owner_id=st.session_state.visitor_id,
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
    st.caption("Quản lý phim muốn xem, phim đang xem, phim đã xem và những bộ sưu tập theo sở thích trong cùng một nơi.")
    watch_tab, collection_tab = st.tabs(["♡ Watchlist", "▦ Bộ sưu tập"])
    with watch_tab:
            render_hero()
            username = st.session_state.visitor_id
            st.markdown("### ♡ Watchlist của bạn")
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
            owner=st.session_state.visitor_id
            st.markdown("### ▦ Bộ sưu tập phim của bạn")
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
    st.caption("So sánh dữ liệu phim và tìm ra lựa chọn phù hợp nhất với gu xem phim của bạn.")

    battle_catalog = []
    with db_connect() as conn:
        rows = conn.execute(
            "SELECT movie_json FROM movie_catalog ORDER BY updated_at DESC LIMIT 150"
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

    if len(battle_catalog) < 2:
        st.info("Hãy tìm kiếm và khám phá ít nhất hai bộ phim để mở màn Movie Battle.")
    else:
        def _battle_title(movie):
            return movie.get("title") or movie.get("name") or "Phim chưa có tên"

        def _battle_year(movie):
            return movie.get("year") or movie.get("release_year") or "Chưa rõ năm"

        def _battle_genres(movie):
            value = movie.get("genres") or movie.get("genre") or []
            if isinstance(value, str):
                value = re.split(r"[,|/]", value)
            if not isinstance(value, (list, tuple, set)):
                value = [value]
            return [str(x).strip() for x in value if str(x).strip()]

        def _battle_rating(movie):
            raw = movie.get("rating")
            if raw in (None, ""):
                raw = movie.get("imdb_rating") or movie.get("score") or movie.get("averageScore")
            try:
                match = re.search(r"\d+(?:[.,]\d+)?", str(raw))
                if not match:
                    return None
                value = float(match.group(0).replace(",", "."))
                # Chuẩn hóa rating về thang 10; không tự suy đoán nếu dữ liệu ngoài thang hợp lệ.
                if 0 <= value <= 10:
                    return value
                if 0 <= value <= 100:
                    return value / 10
            except (TypeError, ValueError):
                pass
            return None

        def _battle_genre_fit(movie, favorite_genres):
            genres = {g.casefold() for g in _battle_genres(movie)}
            favorites = {str(g).strip().casefold() for g in favorite_genres if str(g).strip()}
            if not favorites or not genres:
                return None
            overlap = len(genres & favorites)
            return round(10 * overlap / max(1, len(favorites)), 1)

        def _battle_score(movie, favorite_genres):
            rating = _battle_rating(movie)
            fit = _battle_genre_fit(movie, favorite_genres)
            if rating is None:
                return None, rating, fit
            if fit is None:
                return round(rating, 1), rating, fit
            return round(rating * 0.7 + fit * 0.3, 1), rating, fit

        battle_labels = [
            f"{_battle_title(movie)} ({_battle_year(movie)}) · #{i + 1}"
            for i, movie in enumerate(battle_catalog)
        ]
        label_to_movie = dict(zip(battle_labels, battle_catalog))

        left_key, right_key = "battle_left_v2", "battle_right_v2"
        if st.session_state.get(left_key) not in battle_labels:
            st.session_state[left_key] = battle_labels[0]
        left_label = st.selectbox("ĐỐI THỦ 1", battle_labels, key=left_key)
        left_movie = label_to_movie[left_label]

        right_labels = [label for label in battle_labels if label != left_label]
        if st.session_state.get(right_key) not in right_labels:
            st.session_state[right_key] = right_labels[0]
        right_label = st.selectbox(
            "ĐỐI THỦ 2", right_labels, key=right_key,
            help="Phim đang chọn ở Đối thủ 1 được tự động loại khỏi danh sách."
        )
        right_movie = label_to_movie[right_label]

        visitor = st.session_state.get("visitor_id", "")
        profile = load_profile(visitor) if visitor else {"favorite_genres": []}
        favorite_genres = profile.get("favorite_genres", [])

        def _render_battle_movie(movie, side):
            title = _battle_title(movie)
            poster = movie.get("poster") or movie.get("poster_url") or movie.get("image")
            rating = _battle_rating(movie)
            genres = _battle_genres(movie)
            with st.container(border=True):
                st.markdown(
                    f"<div style='text-align:center;color:#D9B875;font-size:12px;"
                    f"font-weight:800;letter-spacing:2px'>{side}</div>",
                    unsafe_allow_html=True
                )
                if poster:
                    st.image(poster, use_container_width=True)
                else:
                    st.markdown(
                        "<div style='height:260px;display:flex;align-items:center;"
                        "justify-content:center;background:#172438;border-radius:12px;"
                        "color:#AAB6C7'>Chưa có poster</div>",
                        unsafe_allow_html=True
                    )
                st.markdown(f"### {title}")
                st.caption(str(_battle_year(movie)))
                st.markdown("**Thể loại:** " + (", ".join(genres) if genres else "Chưa có dữ liệu"))
                if rating is not None:
                    st.metric("Rating từ nguồn dữ liệu", f"{rating:.1f}/10")
                else:
                    st.metric("Rating từ nguồn dữ liệu", "Chưa có")
                overview = movie.get("overview") or movie.get("description") or movie.get("plot") or ""
                if overview:
                    with st.expander("Xem giới thiệu phim"):
                        st.write(overview)

        left_col, right_col = st.columns(2, gap="large")
        with left_col:
            _render_battle_movie(left_movie, "ĐỐI THỦ 1")
        with right_col:
            _render_battle_movie(right_movie, "ĐỐI THỦ 2")

        left_score, left_rating, left_fit = _battle_score(left_movie, favorite_genres)
        right_score, right_rating, right_fit = _battle_score(right_movie, favorite_genres)

        st.markdown("#### 🧠 Đánh giá tự động")
        st.caption(
            "Điểm đề xuất = 70% rating từ nguồn dữ liệu + 30% độ khớp thể loại yêu thích. "
            "Nếu hồ sơ chưa có thể loại yêu thích, ứng dụng chỉ dùng rating."
        )
        if not favorite_genres:
            st.info("Bạn chưa thiết lập thể loại yêu thích. Hãy cập nhật Hồ sơ cá nhân để điểm đề xuất phản ánh đúng gu xem phim.")
        score_cols = st.columns(2)
        with score_cols[0]:
            st.markdown(f"**{_battle_title(left_movie)}**")
            st.metric("Điểm đề xuất", f"{left_score:.1f}/10" if left_score is not None else "Chưa đủ dữ liệu")
            st.caption(
                f"Rating: {left_rating:.1f}/10" if left_rating is not None else "Rating: chưa có dữ liệu"
            )
            st.caption(
                f"Độ khớp thể loại: {left_fit:.1f}/10" if left_fit is not None else "Độ khớp thể loại: chưa xác định"
            )
        with score_cols[1]:
            st.markdown(f"**{_battle_title(right_movie)}**")
            st.metric("Điểm đề xuất", f"{right_score:.1f}/10" if right_score is not None else "Chưa đủ dữ liệu")
            st.caption(
                f"Rating: {right_rating:.1f}/10" if right_rating is not None else "Rating: chưa có dữ liệu"
            )
            st.caption(
                f"Độ khớp thể loại: {right_fit:.1f}/10" if right_fit is not None else "Độ khớp thể loại: chưa xác định"
            )

        st.markdown("#### 🏆 Đề xuất của ứng dụng")
        if left_score is not None and right_score is not None:
            gap = abs(left_score - right_score)
            if gap < 0.2:
                st.info("Hai bộ phim có điểm đề xuất gần như ngang nhau. Bạn có thể chọn theo tâm trạng hoặc nội dung yêu thích.")
            else:
                winner = left_movie if left_score > right_score else right_movie
                other = right_movie if left_score > right_score else left_movie
                st.success(
                    f"Ứng dụng đề xuất **{_battle_title(winner)}** "
                    f"({max(left_score, right_score):.1f}/10) vì có điểm phù hợp tổng thể cao hơn "
                    f"{gap:.1f} điểm so với **{_battle_title(other)}**."
                )
        else:
            st.warning(
                "Chưa thể kết luận phim nào tốt hơn vì thiếu rating từ nguồn dữ liệu. "
                "Ứng dụng không tự tạo điểm thay thế. Hãy thử chọn hai phim có thông tin đánh giá đầy đủ hơn."
            )

        if favorite_genres:
            st.caption("Thể loại yêu thích trong hồ sơ: " + ", ".join(favorite_genres))

        st.markdown("#### ✨ Gợi ý thêm từ thư viện phim")
        excluded_ids = {
            str(left_movie.get("imdb_id") or left_movie.get("id") or left_movie.get("title")),
            str(right_movie.get("imdb_id") or right_movie.get("id") or right_movie.get("title")),
        }
        suggestions = []
        for candidate in battle_catalog:
            candidate_id = str(candidate.get("imdb_id") or candidate.get("id") or candidate.get("title"))
            if candidate_id in excluded_ids:
                continue
            candidate_score, candidate_rating, candidate_fit = _battle_score(candidate, favorite_genres)
            if candidate_score is not None:
                suggestions.append((candidate_score, candidate))
        suggestions.sort(key=lambda item: item[0], reverse=True)
        if suggestions:
            suggestion_cols = st.columns(min(3, len(suggestions)))
            for col, (score, movie) in zip(suggestion_cols, suggestions[:3]):
                with col:
                    poster = movie.get("poster") or movie.get("poster_url") or movie.get("image")
                    if poster:
                        st.image(poster, use_container_width=True)
                    st.markdown(f"**{_battle_title(movie)}**")
                    st.caption(f"Điểm đề xuất: {score:.1f}/10")
        else:
            st.caption("Chưa có phim khác đủ dữ liệu trong thư viện để đưa ra gợi ý.")
        st.caption(
            "Lưu ý: Đây là điểm đề xuất dựa trên metadata sẵn có, không phải đánh giá chuyên môn "
            "về kịch bản, diễn xuất hay chất lượng nghệ thuật. Kết quả phụ thuộc vào độ đầy đủ và độ tin cậy của nguồn rating."
        )
# -------------------- RECOMMENDATIONS PAGE --------------------
elif st.session_state.page == "Gợi ý phim":
    render_hero()
    username = st.session_state.visitor_id
    st.markdown("### ✨ Gợi ý phim dành cho bạn")
    profile = load_profile(username)
    if not profile["favorite_genres"]:
        st.info("Hãy chọn thể loại yêu thích trong Hồ sơ cá nhân để nhận gợi ý phù hợp hơn.")
    recommendations = get_recommendations(username)
    if recommendations:
        st.caption("Gợi ý dựa trên thể loại yêu thích và dữ liệu phim đã được tìm kiếm trong ứng dụng.")
        render_movie_grid(recommendations, "recommend")
    else:
        st.info("Chưa đủ dữ liệu để gợi ý. Hãy chọn thể loại yêu thích và tìm kiếm thêm phim.")

# -------------------- PROFILE PAGE --------------------
elif st.session_state.page == "Hồ sơ cá nhân":
    render_hero()
    username = st.session_state.visitor_id
    st.markdown("### 👤 Hồ sơ cá nhân")
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

        # Màu theo thang điểm: thấp -> đỏ, trung bình -> cam,
        # tốt -> xanh ngọc, xuất sắc -> vàng champagne.
        def score_color(value):
            if value <= 4:
                return "#D97777"
            if value <= 6:
                return "#E7A85B"
            if value <= 8:
                return "#4DB6AC"
            return "#EBC978"

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
                likes, liked_by_me, comment_rows = review_social_stats(row["id"],st.session_state.visitor_id)
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
                        toggle_review_like(row["id"],st.session_state.visitor_id); st.rerun()
                with st.expander(f"💬 Bình luận ({len(comment_rows)})"):
                    for cr in comment_rows:
                        st.markdown(f"**{cr['display_name']}** · {cr['comment']}")
                    with st.form(f"community_comment_form_{row['id']}"):
                        cn=st.text_input("Tên hiển thị",key=f"community_cn_{row['id']}")
                        ct=st.text_input("Bình luận",key=f"community_ct_{row['id']}")
                        cs=st.form_submit_button("Gửi")
                    if cs:
                        if cn.strip() and ct.strip():
                            add_review_comment(row["id"],st.session_state.visitor_id,cn,ct); st.rerun()
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
