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
# Data: TVmaze + Wikidata + optional IMDb ratings TSV
# Storage: SQLite
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

# =========================================================
# CSS - CINEMA DARK
# =========================================================

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600;700;800&display=swap');

.stApp {
    background:#0D1420;
    color:#EDF1F7;
    font-family:'Be Vietnam Pro',sans-serif;
}

[data-testid="stSidebar"] {
    background:#151E2C;
    border-right:1px solid #2D3A4E;
}

.block-container {
    max-width:1280px;
    padding-top:1.7rem;
    padding-bottom:3rem;
}

h1,h2,h3 {
    color:#EBC978 !important;
}

p,label {
    color:#D6DDE8;
}

.hero {
    background:linear-gradient(115deg,#1B2A40,#3A3028);
    border:1px solid #4C5360;
    border-radius:20px;
    padding:34px;
    margin-bottom:24px;
}

.hero h1 {
    font-size:38px;
    margin:0;
    color:#F2D38A !important;
}

.hero p {
    margin:8px 0 0;
    color:#D4DCE8;
    line-height:1.8;
}

.kicker {
    color:#EBC978;
    font-size:12px;
    font-weight:800;
    letter-spacing:2px;
}

.section {
    font-size:22px;
    font-weight:800;
    color:#EBC978;
    margin:22px 0 12px;
}

div[data-testid="stMetric"] {
    background:#182334;
    border:1px solid #334258;
    border-radius:15px;
    padding:16px;
}

div[data-testid="stMetricValue"] {
    color:#EBC978;
}

div[data-testid="stForm"] {
    background:#172233;
    border:1px solid #344258;
    border-radius:15px;
    padding:18px;
}

div.stButton>button,
div.stFormSubmitButton>button {
    background:#EBC978;
    color:#151B25;
    border:0;
    border-radius:10px;
    font-weight:800;
    min-height:42px;
}

div.stButton>button:hover,
div.stFormSubmitButton>button:hover {
    background:#F5DEA5;
    color:#111827;
}

.stTextInput input,
.stTextArea textarea {
    background:#1A2638;
    color:#F4F6FA;
    border:1px solid #3B4B63;
    border-radius:9px;
}

div[data-testid="stVerticalBlockBorderWrapper"] {
    border-color:#344258;
    border-radius:14px;
    background:#141E2C;
}

a {
    color:#F2D38A !important;
}

.small-muted {
    font-size:12px;
    color:#98A7BB;
}

.footer {
    text-align:center;
    color:#8795A9;
    padding:28px 0;
    line-height:2;
}

.poster-note {
    font-size:11px;
    color:#9CAAC0;
}
</style>
""", unsafe_allow_html=True)


# =========================================================
# HTTP REQUEST
# =========================================================

@st.cache_data(ttl=1800, show_spinner=False)
def get_json(url, params=None):
    response = requests.get(
        url,
        params=params,
        headers=HEADERS,
        timeout=25
    )

    if response.status_code == 429:
        time.sleep(2)
        response = requests.get(
            url,
            params=params,
            headers=HEADERS,
            timeout=25
        )

    response.raise_for_status()
    return response.json()


# =========================================================
# SQLITE DATABASE
# =========================================================

def db_connect():
    conn = sqlite3.connect(
        str(DB_PATH),
        timeout=30,
        check_same_thread=False
    )
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

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_reviews_movie
            ON reviews(movie_id)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_reviews_date
            ON reviews(created_at)
        """)

        conn.commit()


init_db()


def save_review(
    movie_id,
    movie_name,
    source,
    reviewer,
    score,
    comment
):
    created = datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    )

    with db_connect() as conn:
        conn.execute("""
            INSERT INTO reviews(
                movie_id,
                movie_name,
                source,
                reviewer,
                score,
                comment,
                created_at
            )
            VALUES(?,?,?,?,?,?,?)
        """, (
            movie_id,
            movie_name,
            source,
            reviewer,
            int(score),
            comment,
            created
        ))

        conn.commit()


def load_reviews(movie_id=None, limit=5000):
    with db_connect() as conn:

        if movie_id:
            df = pd.read_sql_query(
                """
                SELECT *
                FROM reviews
                WHERE movie_id=?
                ORDER BY id DESC
                LIMIT ?
                """,
                conn,
                params=(movie_id, limit)
            )

        else:
            df = pd.read_sql_query(
                """
                SELECT *
                FROM reviews
                ORDER BY id DESC
                LIMIT ?
                """,
                conn,
                params=(limit,)
            )

    return df


# =========================================================
# OPTIONAL IMDb RATINGS DATASET
# =========================================================

@st.cache_data(ttl=3600, show_spinner=False)
def load_imdb_ratings_file(file_path, modified_time):
    """
    Đọc file IMDb title.ratings.tsv.gz nếu người dùng
    tự tải và đặt vào thư mục data.
    """

    ratings = {}

    if not Path(file_path).exists():
        return ratings

    with gzip.open(
        file_path,
        "rt",
        encoding="utf-8",
        newline=""
    ) as f:

        reader = csv.DictReader(f, delimiter="\t")

        for row in reader:
            tconst = row.get("tconst")
            rating = row.get("averageRating")
            votes = row.get("numVotes")

            if tconst and rating and rating != r"\N":
                try:
                    ratings[tconst] = {
                        "rating": float(rating),
                        "votes": int(votes)
                        if votes and votes != r"\N"
                        else 0
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


# =========================================================
# TVMAZE SEARCH AND DETAILS
# =========================================================

@st.cache_data(ttl=1800, show_spinner=False)
def search_tvmaze(query):

    data = get_json(
        f"{TVMAZE}/search/shows",
        {"q": query}
    )

    results = []

    for item in data[:15]:
        show = item.get("show", {})
        results.append(normalize_tvmaze(show))

    return results


@st.cache_data(ttl=1800, show_spinner=False)
def get_tvmaze_show(show_id):

    show = get_json(
        f"{TVMAZE}/shows/{show_id}",
        {
            "embed[]": [
                "cast",
                "crew",
                "images"
            ]
        }
    )

    return normalize_tvmaze(show, expanded=True)


def normalize_tvmaze(show, expanded=False):

    image = show.get("image") or {}
    externals = show.get("externals") or {}

    network = (
        show.get("network")
        or show.get("webChannel")
        or {}
    )

    genres = show.get("genres") or []
    schedule = show.get("schedule") or {}
    embedded = show.get("_embedded") or {}

    # CAST
    cast = []

    for item in embedded.get("cast", [])[:20]:

        person = item.get("person") or {}
        character = item.get("character") or {}

        cast.append({
            "name": person.get("name", ""),
            "character": character.get("name", ""),
            "image": (
                person.get("image") or {}
            ).get("medium")
        })

    # CREW
    crew = []

    for item in embedded.get("crew", [])[:15]:

        person = item.get("person") or {}

        crew.append({
            "name": person.get("name", ""),
            "type": item.get("type", "")
        })

    # DESCRIPTION
    summary = re.sub(
        r"<[^>]+>",
        " ",
        show.get("summary") or ""
    )

    summary = html.unescape(
        re.sub(r"\s+", " ", summary)
    ).strip()

    return {
        "id": f"tvmaze:{show.get('id')}",
        "provider_id": show.get("id"),
        "source": "TVmaze",
        "title": show.get("name") or "Untitled",
        "original_title": show.get("name") or "",
        "year": (
            show.get("premiered") or ""
        )[:4] or "Chưa cập nhật",
        "release_date": (
            show.get("premiered")
            or "Chưa cập nhật"
        ),
        "runtime": (
            show.get("runtime")
            or show.get("averageRuntime")
        ),
        "genres": genres,
        "overview": (
            summary
            or "Chưa có nội dung giới thiệu."
        ),
        "poster": (
            image.get("original")
            or image.get("medium")
        ),
        "backdrop": None,
        "rating": (
            show.get("rating") or {}
        ).get("average"),
        "rating_votes": None,
        "imdb_id": externals.get("imdb"),
        "tvmaze_url": show.get("url"),
        "network": network.get("name"),
        "country": (
            network.get("country") or {}
        ).get("name"),
        "status": show.get("status"),
        "language": show.get("language"),
        "schedule": schedule,
        "cast": cast,
        "crew": crew,
        "trailer": None,
        "wikidata_id": None
    }


# =========================================================
# WIKIDATA
# =========================================================
