import streamlit as st
import requests
import sqlite3
import pandas as pd
import gzip
import csv
import re
import html
import time
from pathlib import Path
from urllib.parse import quote
from datetime import datetime, timezone

# =========================================================
# MOVIE REVIEW - Cinema Dark
# Data: TVmaze + Wikidata + optional official IMDb ratings TSV
# Storage: SQLite (single Streamlit instance)
# =========================================================

st.set_page_config(
    page_title="Movie Review | Cinema Community",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded"
)

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = BASE_DIR / "movie_reviews.db"
IMDB_RATINGS_FILE = DATA_DIR / "title.ratings.tsv.gz"

TVMAZE = "https://api.tvmaze.com"
WIKIDATA = "https://www.wikidata.org/w/api.php"
COMMONS = "https://commons.wikimedia.org/w/api.php"
COMMONS_FILE = "https://commons.wikimedia.org/wiki/Special:FilePath/"

HEADERS = {
    "User-Agent": "MovieReviewStreamlit/1.0 (educational project)",
    "Accept": "application/json"
}

# -------------------- CSS --------------------
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600;700;800&display=swap');
.stApp {background:#0D1420;color:#EDF1F7;font-family:'Be Vietnam Pro',sans-serif;}
[data-testid="stSidebar"] {background:#151E2C;border-right:1px solid #2D3A4E;}
.block-container {max-width:1280px;padding-top:1.7rem;padding-bottom:3rem;}
h1,h2,h3 {color:#EBC978 !important;}
p, label {color:#D6DDE8;}
.hero {background:linear-gradient(115deg,#1B2A40,#3A3028);border:1px solid #4C5360;border-radius:20px;padding:34px;margin-bottom:24px;}
.hero h1 {font-size:38px;margin:0;color:#F2D38A !important;}
.hero p {margin:8px 0 0;color:#D4DCE8;line-height:1.8;}
.kicker {color:#EBC978;font-size:12px;font-weight:800;letter-spacing:2px;}
.section {font-size:22px;font-weight:800;color:#EBC978;margin:22px 0 12px;}
div[data-testid="stMetric"] {background:#182334;border:1px solid #334258;border-radius:15px;padding:16px;}
div[data-testid="stMetricValue"] {color:#EBC978;}
div[data-testid="stForm"] {background:#172233;border:1px solid #344258;border-radius:15px;padding:18px;}
div.stButton>button, div.stFormSubmitButton>button {background:#EBC978;color:#151B25;border:0;border-radius:10px;font-weight:800;min-height:42px;}
div.stButton>button:hover, div.stFormSubmitButton>button:hover {background:#F5DEA5;color:#111827;}
.stTextInput input,.stTextArea textarea {background:#1A2638;color:#F4F6FA;border:1px solid #3B4B63;border-radius:9px;}
div[data-testid="stVerticalBlockBorderWrapper"] {border-color:#344258;border-radius:14px;background:#141E2C;}
a {color:#F2D38A !important;}
.small-muted {font-size:12px;color:#98A7BB;}
.footer {text-align:center;color:#8795A9;padding:28px 0;line-height:2;}
.poster-note {font-size:11px;color:#9CAAC0;}
</style>
""", unsafe_allow_html=True)


# -------------------- HTTP --------------------
@st.cache_data(ttl=1800, show_spinner=False)
def get_json(url, params=None):
    response = requests.get(url, params=params, headers=HEADERS, timeout=25)
    if response.status_code == 429:
        time.sleep(2)
        response = requests.get(url, params=params, headers=HEADERS, timeout=25)
    response.raise_for_status()
    return response.json()


# -------------------- SQLITE --------------------
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
        conn.execute("CREATE INDEX IF NOT EXISTS idx_reviews_movie ON reviews(movie_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_reviews_date ON reviews(created_at)")
        conn.commit()

init_db()

def save_review(movie_id, movie_name, source, reviewer, score, comment):
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with db_connect() as conn:
        conn.execute("""
            INSERT INTO reviews(movie_id,movie_name,source,reviewer,score,comment,created_at)
            VALUES(?,?,?,?,?,?,?)
        """, (movie_id, movie_name, source, reviewer, int(score), comment, created))
        conn.commit()

def load_reviews(movie_id=None, limit=5000):
    with db_connect() as conn:
        if movie_id:
            df = pd.read_sql_query(
                "SELECT * FROM reviews WHERE movie_id=? ORDER BY id DESC LIMIT ?",
                conn, params=(movie_id, limit)
            )
        else:
            df = pd.read_sql_query(
                "SELECT * FROM reviews ORDER BY id DESC LIMIT ?",
                conn, params=(limit,)
            )
    return df

# -------------------- IMDb non-commercial ratings --------------------
@st.cache_data(ttl=3600, show_spinner=False)
def load_imdb_ratings_file(file_path, modified_time):
    """Optional local IMDb title.ratings.tsv.gz. Does not download large IMDb dumps."""
    ratings = {}
    if not Path(file_path).exists():
        return ratings
    with gzip.open(file_path, "rt", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            tconst = row.get("tconst")
            rating = row.get("averageRating")
            votes = row.get("numVotes")
            if tconst and rating and rating != r"\N":
                try:
                    ratings[tconst] = {
                        "rating": float(rating),
                        "votes": int(votes) if votes and votes != r"\N" else 0
                    }
                except ValueError:
                    continue
    return ratings

def get_imdb_rating(imdb_id):
    if not imdb_id or not IMDB_RATINGS_FILE.exists():
        return None
    try:
        ratings = load_imdb_ratings_file(
            str(IMDB_RATINGS_FILE),
            IMDB_RATINGS_FILE.stat().st_mtime
        )
        return ratings.get(imdb_id)
    except Exception:
        return None

# -------------------- TVmaze search/details --------------------
@st.cache_data(ttl=1800, show_spinner=False)
def search_tvmaze(query):
    data = get_json(f"{TVMAZE}/search/shows", {"q": query})
    results = []
    for item in data[:15]:
        show = item.get("show", {})
        results.append(normalize_tvmaze(show))
    return results

@st.cache_data(ttl=1800, show_spinner=False)
def get_tvmaze_show(show_id):
    show = get_json(f"{TVMAZE}/shows/{show_id}", {"embed[]": ["cast", "crew", "images"]})
    return normalize_tvmaze(show, expanded=True)

def normalize_tvmaze(show, expanded=False):
    image = show.get("image") or {}
    externals = show.get("externals") or {}
    network = show.get("network") or show.get("webChannel") or {}
    genres = show.get("genres") or []
    schedule = show.get("schedule") or {}
    embedded = show.get("_embedded") or {}

    cast = []
    for item in embedded.get("cast", [])[:20]:
        person = item.get("person") or {}
        character = item.get("character") or {}
        cast.append({
            "name": person.get("name", ""),
            "character": character.get("name", ""),
            "image": (person.get("image") or {}).get("medium")
        })

    crew = []
    for item in embedded.get("crew", [])[:15]:
        person = item.get("person") or {}
        crew.append({
            "name": person.get("name", ""),
            "type": item.get("type", "")
        })

    summary = re.sub(r"<[^>]+>", " ", show.get("summary") or "")
    summary = html.unescape(re.sub(r"\s+", " ", summary)).strip()

    return {
        "id": f"tvmaze:{show.get('id')}",
        "provider_id": show.get("id"),
        "source": "TVmaze",
        "title": show.get("name") or "Untitled",
        "original_title": show.get("name") or "",
        "year": (show.get("premiered") or "")[:4] or "Chưa cập nhật",
        "release_date": show.get("premiered") or "Chưa cập nhật",
        "runtime": show.get("runtime") or show.get("averageRuntime"),
        "genres": genres,
        "overview": summary or "Chưa có nội dung giới thiệu.",
        "poster": (image.get("original") or image.get("medium")),
        "backdrop": None,
        "rating": (show.get("rating") or {}).get("average"),
        "rating_votes": None,
        "imdb_id": externals.get("imdb"),
        "tvmaze_url": show.get("url"),
        "network": network.get("name"),
        "country": (network.get("country") or {}).get("name"),
        "status": show.get("status"),
        "language": show.get("language"),
        "schedule": schedule,
        "cast": cast,
        "crew": crew,
        "trailer": None,
        "wikidata_id": None
    }

# -------------------- Wikidata --------------------
@st.cache_data(ttl=1800, show_spinner=False)
def search_wikidata(query):
    results = []
    for lang in ("en", "vi"):
        data = get_json(WIKIDATA, {
            "action": "wbsearchentities",
            "search": query,
            "language": lang,
            "uselang": lang,
            "type": "item",
            "limit": 20,
            "format": "json"
        })
        for item in data.get("search", []):
            qid = item.get("id")
            if qid and not any(x["id"] == qid for x in results):
                results.append({
                    "id": qid,
                    "title": item.get("label", qid),
                    "description": item.get("description", "")
                })
    return results

@st.cache_data(ttl=3600, show_spinner=False)
def get_wikidata_entity(qid):
    data = get_json(WIKIDATA, {
        "action": "wbgetentities",
        "ids": qid,
        "props": "labels|descriptions|claims",
        "languages": "en|vi",
        "format": "json"
    })
    return data.get("entities", {}).get(qid, {})

def wd_claim(entity, prop):
    values = []
    for claim in entity.get("claims", {}).get(prop, []):
        try:
            values.append(claim["mainsnak"]["datavalue"]["value"])
        except (KeyError, TypeError):
            pass
    return values

@st.cache_data(ttl=3600, show_spinner=False)
def wd_labels(ids):
    ids = list(dict.fromkeys(ids))
    output = {}
    for i in range(0, len(ids), 40):
        batch = ids[i:i+40]
        if not batch:
            continue
        data = get_json(WIKIDATA, {
            "action": "wbgetentities",
            "ids": "|".join(batch),
            "props": "labels",
            "languages": "en|vi",
            "format": "json"
        })
        for qid, entity in data.get("entities", {}).items():
            labels = entity.get("labels", {})
            output[qid] = (
                labels.get("en", {}).get("value")
                or labels.get("vi", {}).get("value")
                or qid
            )
    return output

def wd_related(entity, prop):
    ids = [
        v["id"] for v in wd_claim(entity, prop)
        if isinstance(v, dict) and v.get("id")
    ]
    labels = wd_labels(ids)
    return [labels.get(qid, qid) for qid in ids]

def wd_time_year(entity):
    values = wd_claim(entity, "P577")
    if not values:
        return None
    match = re.search(r"[+-]?(\d{1,4})-", values[0].get("time", ""))
    return match.group(1) if match else None

def wikidata_enrichment(qid):
    entity = get_wikidata_entity(qid)
    labels = entity.get("labels", {})
    descriptions = entity.get("descriptions", {})
    title = (
        labels.get("en", {}).get("value")
        or labels.get("vi", {}).get("value")
    )
    image_values = wd_claim(entity, "P18")
    poster = None
    if image_values and isinstance(image_values[0], str):
        poster = COMMONS_FILE + quote(image_values[0].replace(" ", "_"), safe="")
    youtube_ids = wd_claim(entity, "P1651")
    trailer = (
        "https://www.youtube.com/watch?v=" + youtube_ids[0]
        if youtube_ids and isinstance(youtube_ids[0], str)
        else None
    )
    imdb_ids = wd_claim(entity, "P345")
    return {
        "title": title,
        "overview": descriptions.get("en", {}).get("value") or descriptions.get("vi", {}).get("value"),
        "year": wd_time_year(entity),
        "poster": poster,
        "trailer": trailer,
        "directors": wd_related(entity, "P57"),
        "cast": wd_related(entity, "P161"),
        "genres": wd_related(entity, "P136"),
        "countries": wd_related(entity, "P495"),
        "imdb_id": imdb_ids[0] if imdb_ids else None
    }

# -------------------- Cross-source search --------------------
def search_all_sources(query):
    combined = []
    errors = []

    try:
        for item in search_tvmaze(query):
            combined.append(item)
    except Exception as e:
        errors.append(f"TVmaze: {e}")

    try:
        for item in search_wikidata(query):
            combined.append({
                "id": f"wikidata:{item['id']}",
                "provider_id": item["id"],
                "source": "Wikidata",
                "title": item["title"],
                "original_title": item["title"],
                "year": "Chưa cập nhật",
                "release_date": "",
                "runtime": None,
                "genres": [],
                "overview": item["description"],
                "poster": None,
                "backdrop": None,
                "rating": None,
                "rating_votes": None,
                "imdb_id": None,
                "tvmaze_url": None,
                "network": None,
                "country": None,
                "status": None,
                "language": None,
                "schedule": {},
                "cast": [],
                "crew": [],
                "trailer": None,
                "wikidata_id": item["id"]
            })
    except Exception as e:
        errors.append(f"Wikidata: {e}")

    # De-duplicate identical provider records; preserve distinct source IDs.
    seen = set()
    unique = []
    for item in combined:
        key = (item["source"], item["id"])
        if key not in seen:
            seen.add(key)
            unique.append(item)

    return unique, errors

# -------------------- Detail enrichment --------------------
def enrich_movie(item):
    result = dict(item)

    if item["source"] == "TVmaze":
        try:
            result = get_tvmaze_show(item["provider_id"])
        except Exception:
            result = dict(item)

    # Link Wikidata entity via IMDb identifier when available.
    qid = None
    imdb_id = result.get("imdb_id")
    if imdb_id:
        try:
            data = get_json(WIKIDATA, {
                "action": "wbsearchentities",
                "search": imdb_id,
                "language": "en",
                "type": "item",
                "limit": 5,
                "format": "json"
            })
            for candidate in data.get("search", []):
                desc = (candidate.get("description") or "").lower()
                if any(word in desc for word in ("film", "movie", "television", "series")):
                    qid = candidate["id"]
                    break
        except Exception:
            pass

    # If no IMDb-based match, search by title and choose a plausible film/series item.
    if not qid:
        try:
            candidates = search_wikidata(result.get("title", ""))
            for candidate in candidates:
                desc = (candidate.get("description") or "").lower()
                if any(word in desc for word in ("film", "movie", "television series", "tv series")):
                    qid = candidate["id"]
                    break
        except Exception:
            pass

    result["wikidata_id"] = qid

    if qid:
        try:
            wd = wikidata_enrichment(qid)
            result["overview"] = result.get("overview") or wd.get("overview")
            result["year"] = result.get("year") or wd.get("year") or "Chưa cập nhật"
            result["poster"] = result.get("poster") or wd.get("poster")
            result["trailer"] = result.get("trailer") or wd.get("trailer")
            result["cast"] = result.get("cast") or [
                {"name": name, "character": "", "image": None}
                for name in wd.get("cast", [])
            ]
            result["directors"] = wd.get("directors", [])
            result["genres"] = result.get("genres") or wd.get("genres", [])
            result["countries"] = wd.get("countries", [])
            result["imdb_id"] = result.get("imdb_id") or wd.get("imdb_id")
        except Exception:
            result.setdefault("directors", [])
            result.setdefault("countries", [])

    imdb_rating = get_imdb_rating(result.get("imdb_id"))
    if imdb_rating:
        result["imdb_rating"] = imdb_rating["rating"]
        result["imdb_votes"] = imdb_rating["votes"]
    else:
        result["imdb_rating"] = None
        result["imdb_votes"] = None

    result.setdefault("directors", [])
    result.setdefault("countries", [])
    result.setdefault("cast", [])
    result.setdefault("genres", [])
    return result

# -------------------- UI helpers --------------------
def section(title):
    st.markdown(f'<div class="section">{html.escape(title)}</div>', unsafe_allow_html=True)

def show_review(row, show_movie=True):
    with st.container(border=True):
        if show_movie:
            st.markdown(f"🎬 **{html.escape(str(row['movie_name']))}**")
        left, right = st.columns([4, 1])
        with left:
            st.markdown(f"👤 **{html.escape(str(row['reviewer']))}**")
        with right:
            st.markdown(f"⭐ **{int(row['score'])}/10**")
        st.write(row["comment"])
        st.caption(str(row["created_at"])[:19].replace("T", " "))

def movie_key(movie):
    return movie.get("id") or f"{movie.get('source')}:{movie.get('provider_id')}"

def poster_or_placeholder(movie):
    poster = movie.get("poster")
    if poster:
        st.image(poster, use_container_width=True)
        st.caption(f"Nguồn ảnh: {movie.get('source', 'Wikidata/TVmaze')}")
    else:
        st.markdown("""
        <div style="height:300px;background:linear-gradient(145deg,#25364B,#111A28);
        border:1px solid #3A4A60;border-radius:14px;display:flex;align-items:center;
        justify-content:center;color:#EBC978;font-size:54px;">🎬</div>
        """, unsafe_allow_html=True)
        st.caption("Chưa tìm thấy poster phù hợp.")

def open_movie_detail(item):
    """Callback chạy trước khi Streamlit render lại trang."""
    st.session_state.selected_movie = item
    st.session_state.page = "Chi tiết phim"
    st.session_state.nav_radio = "Chi tiết phim"


def navigate_to_search():
    st.session_state.page = "Tìm kiếm phim"
    st.session_state.nav_radio = "Tìm kiếm phim"


def navigate_to_detail():
    st.session_state.page = "Chi tiết phim"
    st.session_state.nav_radio = "Chi tiết phim"


def sync_sidebar_page():
    st.session_state.page = st.session_state.nav_radio


def movie_card(item, idx):
    with st.container(border=True):
        if item.get("poster"):
            st.image(item["poster"], use_container_width=True)
        else:
            st.markdown(
                '<div style="height:170px;background:#202D40;border-radius:10px;'
                'display:flex;align-items:center;justify-content:center;font-size:42px">🎬</div>',
                unsafe_allow_html=True
            )
        st.markdown(f"**{item.get('title','Untitled')}**")
        st.caption(f"{item.get('year','')} · {item.get('source','')}")
        st.button(
            "Xem chi tiết",
            key=f"open_{idx}_{movie_key(item)}",
            use_container_width=True,
            on_click=open_movie_detail,
            args=(item,)
        )

# -------------------- Session state --------------------
if "page" not in st.session_state:
    st.session_state.page = "Trang chủ"
if "search_results" not in st.session_state:
    st.session_state.search_results = []
if "selected_movie" not in st.session_state:
    st.session_state.selected_movie = None
if "search_errors" not in st.session_state:
    st.session_state.search_errors = []

# -------------------- Sidebar --------------------
st.sidebar.markdown(
    "<h2 style='color:#EBC978;margin-bottom:0'>🎬 MOVIE REVIEW</h2>",
    unsafe_allow_html=True
)
st.sidebar.caption("CINEMA COMMUNITY")
st.sidebar.divider()

pages = ["Trang chủ", "Tìm kiếm phim", "Chi tiết phim", "Cộng đồng Review", "Thống kê"]
if "nav_radio" not in st.session_state:
    st.session_state.nav_radio = st.session_state.page

st.sidebar.radio(
    "ĐIỀU HƯỚNG",
    pages,
    key="nav_radio",
    on_change=sync_sidebar_page
)

st.sidebar.divider()
st.sidebar.markdown("🎞️ Khám phá điện ảnh  \n⭐ Chia sẻ cảm nhận  \n💬 Kết nối cộng đồng")
st.sidebar.divider()
st.sidebar.success("SQLite: sẵn sàng")
st.sidebar.caption("Nguồn phim: TVmaze + Wikidata")
st.sidebar.caption("IMDb ratings: tùy chọn, dữ liệu TSV cục bộ")

# -------------------- Home --------------------
if st.session_state.page == "Trang chủ":
    st.markdown("""
    <div class="hero">
      <div class="kicker">DISCOVER · WATCH · REVIEW</div>
      <h1>Movie Review</h1>
      <p>Khám phá thế giới điện ảnh, tìm kiếm phim từ nhiều nguồn dữ liệu
      và chia sẻ cảm nhận cùng cộng đồng yêu phim.</p>
    </div>
    """, unsafe_allow_html=True)

    df = load_reviews()
    total = len(df)
    avg = float(df["score"].mean()) if total else 0
    movie_count = int(df["movie_id"].nunique()) if total else 0

    c1, c2, c3 = st.columns(3)
    c1.metric("💬 Tổng lượt review", total)
    c2.metric("⭐ Điểm cộng đồng", f"{avg:.1f}/10")
    c3.metric("🎬 Phim được review", movie_count)

    st.divider()
    section("🔎 Bắt đầu khám phá")
    q = st.text_input("Tìm nhanh tên phim hoặc series", placeholder="Ví dụ: Interstellar, Breaking Bad, Titanic...")
    if st.button("Tìm kiếm phim", use_container_width=True, key="home_search_button"):
        if len(q.strip()) >= 2:
            st.session_state.quick_query = q.strip()
            navigate_to_search()
            st.rerun()
        else:
            st.warning("Nhập ít nhất 2 ký tự.")

    st.divider()
    section("💬 Đánh giá mới nhất")
    if df.empty:
        st.info("Chưa có review. Hãy tìm một bộ phim và viết đánh giá đầu tiên!")
    else:
        for _, row in df.head(5).iterrows():
            show_review(row)

# -------------------- Search --------------------
elif st.session_state.page == "Tìm kiếm phim":
    st.title("🔍 Tìm kiếm phim")
    st.caption("Tìm đồng thời trên TVmaze và Wikidata. Không cần API key.")

    with st.form("search_form"):
        default_query = st.session_state.pop("quick_query", "")
        query = st.text_input("Tên phim / series", value=default_query, placeholder="Nhập tên phim...")
        submitted = st.form_submit_button("🔍 TÌM KIẾM", use_container_width=True)

    if submitted:
        if len(query.strip()) < 2:
            st.warning("Vui lòng nhập ít nhất 2 ký tự.")
        else:
            with st.spinner("Đang tìm trên TVmaze và Wikidata..."):
                try:
                    results, errors = search_all_sources(query.strip())
                    st.session_state.search_results = results
                    st.session_state.search_errors = errors
                except Exception as e:
                    st.error(f"Không thể tìm kiếm: {e}")

    results = st.session_state.search_results
    if st.session_state.search_errors:
        st.warning("Một số nguồn không phản hồi: " + " | ".join(st.session_state.search_errors))
    if results:
        st.success(f"Tìm thấy {len(results)} kết quả từ các nguồn dữ liệu.")
        source_filter = st.selectbox("Lọc nguồn", ["Tất cả", "TVmaze", "Wikidata"])
        filtered = results if source_filter == "Tất cả" else [x for x in results if x["source"] == source_filter]
        for start in range(0, len(filtered), 4):
            cols = st.columns(4)
            for col, (idx, item) in zip(cols, enumerate(filtered[start:start+4], start=start)):
                with col:
                    movie_card(item, idx)
    elif submitted:
        st.info("Không tìm thấy kết quả. Thử tên tiếng Anh hoặc tên gốc.")

# -------------------- Movie detail --------------------
elif st.session_state.page == "Chi tiết phim":
    movie = st.session_state.selected_movie
    if not movie:
        st.info("Chưa chọn phim. Hãy vào Tìm kiếm phim trước.")
        if st.button("Đi đến tìm kiếm", on_click=navigate_to_search):
            st.rerun()
    else:
        st.button(
            "← Quay lại tìm kiếm",
            key="back_to_search",
            on_click=navigate_to_search
        )
        with st.spinner("Đang tổng hợp thông tin từ các nguồn..."):
            try:
                detail = enrich_movie(movie)
            except Exception:
                detail = movie

        st.title(detail.get("title", "Chi tiết phim"))
        st.caption(f"Nguồn dữ liệu chính: {detail.get('source')}")

        col1, col2 = st.columns([1, 2.2])
        with col1:
            poster_or_placeholder(detail)
        with col2:
            st.subheader("📌 Thông tin phim")
            st.write(f"**Năm phát hành:** {detail.get('year') or 'Chưa cập nhật'}")
            runtime = detail.get("runtime")
            st.write(f"**Thời lượng:** {str(runtime) + ' phút' if runtime else 'Chưa cập nhật'}")
            st.write(f"**Thể loại:** {', '.join(detail.get('genres') or []) or 'Chưa cập nhật'}")
            st.write(f"**Quốc gia:** {', '.join(detail.get('countries') or []) or detail.get('country') or 'Chưa cập nhật'}")
            st.write(f"**Đạo diễn:** {', '.join(detail.get('directors') or []) or 'Chưa cập nhật'}")
            st.write(f"**Trạng thái:** {detail.get('status') or 'Chưa cập nhật'}")
            if detail.get("imdb_id"):
                st.markdown(f"[⭐ Mở trang IMDb](https://www.imdb.com/title/{detail['imdb_id']}/)")
            if detail.get("tvmaze_url"):
                st.markdown(f"[📺 Mở TVmaze]({detail['tvmaze_url']})")
            if detail.get("wikidata_id"):
                st.markdown(f"[🌐 Mở Wikidata](https://www.wikidata.org/wiki/{detail['wikidata_id']})")

            if detail.get("imdb_rating") is not None:
                st.metric("IMDb dataset rating", f"{detail['imdb_rating']:.1f}/10",
                          f"{detail.get('imdb_votes', 0):,} lượt bình chọn")
            elif detail.get("rating") is not None:
                st.metric("TVmaze rating", f"{detail['rating']}/10")

        st.divider()
        section("📖 Nội dung")
        st.write(detail.get("overview") or "Chưa có nội dung giới thiệu.")

        st.divider()
        section("🎭 Diễn viên")
        cast = detail.get("cast") or []
        if cast:
            cast_cols = st.columns(4)
            for i, person in enumerate(cast[:20]):
                with cast_cols[i % 4]:
                    if isinstance(person, dict):
                        if person.get("image"):
                            st.image(person["image"], use_container_width=True)
                        st.markdown(f"**{person.get('name','')}**")
                        if person.get("character"):
                            st.caption(f"Vai: {person['character']}")
                    else:
                        st.write(person)
        else:
            st.info("Nguồn dữ liệu chưa có danh sách diễn viên.")

        crew = detail.get("crew") or []
        if crew:
            st.divider()
            section("🎬 Đoàn làm phim")
            for member in crew[:12]:
                st.write(f"**{member.get('type','')}**: {member.get('name','')}")

        st.divider()
        section("▶️ Trailer")
        if detail.get("trailer"):
            st.video(detail["trailer"])
        else:
            yt = "https://www.youtube.com/results?search_query=" + quote(detail.get("title", "") + " official trailer")
            st.info("Chưa có liên kết trailer được xác minh trong dữ liệu.")
            st.link_button("Tìm trailer trên YouTube", yt)

        st.divider()
        section("⭐ Viết đánh giá")
        review_id = movie_key(detail)
        with st.form(f"review_{review_id}"):
            reviewer = st.text_input("Tên người đánh giá", max_chars=50)
            score = st.slider("Điểm đánh giá", 1, 10, 8)
            comment = st.text_area("Cảm nhận của bạn", max_chars=2000, height=130)
            send = st.form_submit_button("📩 GỬI ĐÁNH GIÁ", use_container_width=True)
            if send:
                if not reviewer.strip() or not comment.strip():
                    st.warning("Vui lòng nhập tên và nội dung đánh giá.")
                else:
                    try:
                        save_review(review_id, detail.get("title", "Phim"), detail.get("source", ""), reviewer.strip(), score, comment.strip())
                        st.success("Đã lưu đánh giá!")
                        st.rerun()
                    except sqlite3.Error as e:
                        st.error(f"Không thể lưu review: {e}")

        st.divider()
        section("💬 Review cộng đồng")
        reviews = load_reviews(review_id)
        if reviews.empty:
            st.info("Phim này chưa có đánh giá.")
        else:
            a, b = st.columns(2)
            a.metric("Điểm cộng đồng", f"{reviews['score'].mean():.1f}/10")
            b.metric("Số lượt review", len(reviews))
            for _, row in reviews.iterrows():
                show_review(row, show_movie=False)

# -------------------- Community --------------------
elif st.session_state.page == "Cộng đồng Review":
    st.title("💬 Cộng đồng Review")
    if st.button("🔄 Làm mới dữ liệu"):
        st.rerun()
    df = load_reviews()
    if df.empty:
        st.info("Chưa có đánh giá từ cộng đồng.")
    else:
        a, b = st.columns(2)
        a.metric("Tổng lượt review", len(df))
        b.metric("Điểm trung bình", f"{df['score'].mean():.1f}/10")
        names = ["Tất cả phim"] + sorted(df["movie_name"].dropna().unique().tolist())
        selected = st.selectbox("Lọc theo phim", names)
        if selected != "Tất cả phim":
            df = df[df["movie_name"] == selected]
        st.caption(f"Đang hiển thị {len(df)} đánh giá")
        for _, row in df.iterrows():
            show_review(row)

# -------------------- Statistics --------------------
elif st.session_state.page == "Thống kê":
    st.title("📊 Thống kê cộng đồng")
    if st.button("🔄 Cập nhật thống kê"):
        st.rerun()
    df = load_reviews()
    if df.empty:
        st.info("Chưa có dữ liệu thống kê.")
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("Tổng review", len(df))
        c2.metric("Điểm trung bình", f"{df['score'].mean():.2f}/10")
        c3.metric("Số phim", df["movie_id"].nunique())

        ranking = (
            df.groupby(["movie_id", "movie_name"])
            .agg(avg_score=("score", "mean"), review_count=("score", "count"))
            .reset_index()
            .sort_values(["avg_score", "review_count"], ascending=[False, False])
        )
        st.divider()
        section("🏆 Bảng xếp hạng phim")
        display = ranking.rename(columns={
            "movie_name": "Tên phim",
            "avg_score": "Điểm trung bình",
            "review_count": "Lượt đánh giá"
        })
        st.dataframe(display[["Tên phim", "Điểm trung bình", "Lượt đánh giá"]],
                     use_container_width=True, hide_index=True)
        st.divider()
        section("⭐ Điểm trung bình theo phim")
        st.bar_chart(ranking.set_index("movie_name")["avg_score"])
        section("📈 Số lượt đánh giá")
        st.bar_chart(ranking.set_index("movie_name")["review_count"])
        st.divider()
        section("📋 Dữ liệu review")
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.download_button(
            "📥 TẢI REVIEW CSV",
            data=df.to_csv(index=False).encode("utf-8-sig"),
            file_name="movie_reviews_backup.csv",
            mime="text/csv",
            use_container_width=True
        )

        # SQLite backup download: create a consistent copy via SQLite backup API.
        if st.button("Tạo bản sao lưu SQLite"):
            backup_path = BASE_DIR / "movie_reviews_backup.db"
            source = sqlite3.connect(str(DB_PATH))
            destination = sqlite3.connect(str(backup_path))
            try:
                source.backup(destination)
            finally:
                destination.close()
                source.close()
            st.success("Đã tạo bản sao lưu SQLite trên máy chủ. Hãy tải file từ môi trường quản lý hosting hoặc dùng CSV để sao lưu trực tiếp.")

# -------------------- Footer --------------------
st.divider()
st.markdown("""
<div class="footer">
  <div style="font-size:25px;color:#EBC978;font-weight:800">🎬 MOVIE REVIEW</div>
  DISCOVER · WATCH · REVIEW<br>
  A COMMUNITY FOR MOVIE LOVERS<br>
  Data: TVmaze · Wikidata · IMDb public datasets (optional)<br>
  SQLite community reviews
</div>
""", unsafe_allow_html=True)
