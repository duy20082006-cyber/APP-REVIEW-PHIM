
import streamlit as st
import requests
import pandas as pd
import sqlite3
import re
import html
import os

from pathlib import Path
from urllib.parse import quote
from contextlib import contextmanager
from datetime import datetime, timezone


# =====================================================
# 1. PAGE CONFIG
# =====================================================

st.set_page_config(
    page_title="Movie Review | Cinema Community",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded"
)

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "movie_reviews.db"

WD_API = "https://www.wikidata.org/w/api.php"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
COMMONS_FILE = "https://commons.wikimedia.org/wiki/Special:FilePath/"

HEADERS = {
    "User-Agent": "MovieReviewApp/3.0 (educational project)",
    "Accept": "application/json"
}

# =====================================================
# 2. CSS - CINEMA DESIGN
# =====================================================

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600;700;800&display=swap');

.stApp {
    background: #10141D;
    color: #F1F3F7;
    font-family: 'Be Vietnam Pro', sans-serif;
}

[data-testid="stSidebar"] {
    background: #171D29;
    border-right: 1px solid #303B50;
}

[data-testid="stSidebar"] * {
    color: #E8EAF0;
}

.block-container {
    max-width: 1250px;
    padding-top: 2rem;
    padding-bottom: 3rem;
}

h1, h2, h3 {
    color: #F4CA68 !important;
}

.hero {
    background: linear-gradient(120deg, #202B40, #38302B);
    border: 1px solid #48516A;
    padding: 32px;
    border-radius: 18px;
    margin-bottom: 25px;
}

.hero-title {
    color: #F4CA68;
    font-size: 35px;
    font-weight: 800;
}

.hero-subtitle {
    color: #D5DCE8;
    font-size: 15px;
    line-height: 1.9;
}

.section-title {
    color: #F4CA68;
    font-size: 22px;
    font-weight: 700;
    margin: 20px 0 15px;
}

div[data-testid="stMetric"] {
    background: #1C2432;
    border: 1px solid #303C51;
    border-radius: 14px;
    padding: 18px;
}

div[data-testid="stMetricValue"] {
    color: #F4CA68;
}

div[data-testid="stMetricLabel"] {
    color: #B7C1D2;
}

div.stButton > button,
div.stFormSubmitButton > button {
    background: #E7BB60;
    color: #151923;
    border: none;
    border-radius: 9px;
    font-weight: 700;
    min-height: 42px;
}

div.stButton > button:hover,
div.stFormSubmitButton > button:hover {
    background: #F5D48D;
    color: #10141D;
}

div[data-testid="stForm"] {
    background: #1A2230;
    border: 1px solid #303C51;
    padding: 18px;
    border-radius: 14px;
}

div[data-testid="stVerticalBlockBorderWrapper"] {
    border-color: #303C51;
    border-radius: 13px;
}

.stTextInput input,
.stTextArea textarea {
    background: #202A3A;
    color: white;
    border: 1px solid #39465D;
    border-radius: 8px;
}

hr {
    border-color: #303C51;
}

a {
    color: #F4CA68 !important;
}

.footer {
    text-align: center;
    color: #8994A8;
    padding: 25px 0;
    line-height: 2;
}

@media (max-width: 768px) {
    .hero {
        padding: 20px;
    }

    .hero-title {
        font-size: 25px;
    }

    .block-container {
        padding-top: 1rem;
    }
}
</style>
""", unsafe_allow_html=True)


# =====================================================
# 3. SQLITE DATABASE
# =====================================================

def get_db_connection():

    conn = sqlite3.connect(
        str(DB_PATH),
        timeout=30
    )

    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA busy_timeout = 30000")

    return conn


def init_database():

    conn = get_db_connection()

    try:

        conn.execute("PRAGMA journal_mode = WAL")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                movie_id TEXT NOT NULL,
                movie_name TEXT NOT NULL,
                reviewer TEXT NOT NULL,
                score INTEGER NOT NULL
                    CHECK(score BETWEEN 1 AND 10),
                comment TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_reviews_movie
            ON reviews(movie_id)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_reviews_created
            ON reviews(created_at)
        """)

        conn.commit()

    finally:
        conn.close()


init_database()


# =====================================================
# 4. SAVE REVIEW
# =====================================================

def save_review(
    movie_id,
    movie_name,
    reviewer,
    score,
    comment
):

    conn = get_db_connection()

    try:

        created_at = datetime.now(
            timezone.utc
        ).isoformat(timespec="seconds")

        conn.execute("""
            INSERT INTO reviews (
                movie_id,
                movie_name,
                reviewer,
                score,
                comment,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            movie_id,
            movie_name,
            reviewer,
            int(score),
            comment,
            created_at
        ))

        conn.commit()

        return True

    finally:
        conn.close()


# =====================================================
# 5. LOAD REVIEWS
# =====================================================

def load_reviews(movie_id=None, limit=5000):

    conn = get_db_connection()

    try:

        if movie_id:

            query = """
                SELECT *
                FROM reviews
                WHERE movie_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
            """

            df = pd.read_sql_query(
                query,
                conn,
                params=(movie_id, limit)
            )

        else:

            query = """
                SELECT *
                FROM reviews
                ORDER BY created_at DESC, id DESC
                LIMIT ?
            """

            df = pd.read_sql_query(
                query,
                conn,
                params=(limit,)
            )

        return df

    finally:
        conn.close()


# =====================================================
# 6. WIKIDATA REQUEST
# =====================================================

def wikidata_request(params):

    response = requests.get(
        WD_API,
        params=params,
        headers=HEADERS,
        timeout=25
    )

    response.raise_for_status()

    return response.json()


# =====================================================
# 7. SEARCH MOVIES
# =====================================================

@st.cache_data(ttl=1800, show_spinner=False)
def search_movies(keyword):

    results = {}

    for language in ["vi", "en"]:

        params = {
            "action": "wbsearchentities",
            "search": keyword,
            "language": language,
            "uselang": language,
            "type": "item",
            "limit": 50,
            "format": "json"
        }

        data = wikidata_request(params)

        for item in data.get("search", []):

            qid = item.get("id")

            if not qid:
                continue

            if qid not in results:

                results[qid] = {
                    "id": qid,
                    "name": item.get("label", qid),
                    "description": item.get(
                        "description",
                        "Chưa có mô tả"
                    )
                }

    return list(results.values())


# =====================================================
# 8. GET MOVIE ENTITY
# =====================================================

@st.cache_data(ttl=3600, show_spinner=False)
def get_movie_entity(qid):

    params = {
        "action": "wbgetentities",
        "ids": qid,
        "props": "labels|descriptions|claims",
        "languages": "vi|en",
        "format": "json"
    }

    data = wikidata_request(params)

    return data.get("entities", {}).get(qid, {})


# =====================================================
# 9. GET CLAIMS
# =====================================================

def get_claims(entity, property_id):

    claims = entity.get("claims", {})

    values = []

    for claim in claims.get(property_id, []):

        try:

            value = claim["mainsnak"]["datavalue"]["value"]

            values.append(value)

        except (KeyError, TypeError):
            continue

    return values


# =====================================================
# 10. GET ENTITY LABELS
# =====================================================

@st.cache_data(ttl=3600, show_spinner=False)
def get_entity_labels(entity_ids):

    labels = {}

    entity_ids = list(dict.fromkeys(entity_ids))

    for start in range(0, len(entity_ids), 40):

        batch = entity_ids[start:start + 40]

        params = {
            "action": "wbgetentities",
            "ids": "|".join(batch),
            "props": "labels",
            "languages": "vi|en",
            "format": "json"
        }

        data = wikidata_request(params)

        for qid, item in data.get("entities", {}).items():

            names = item.get("labels", {})

            labels[qid] = (
                names.get("vi", {}).get("value")
                or names.get("en", {}).get("value")
                or qid
            )

    return labels


def get_related_names(entity, property_id):

    ids = [
        value["id"]
        for value in get_claims(entity, property_id)
        if isinstance(value, dict) and "id" in value
    ]

    labels = get_entity_labels(ids)

    return [
        labels.get(qid, qid)
        for qid in ids
    ]


# =====================================================
# 11. MOVIE YEAR
# =====================================================

def get_year(entity):

    dates = get_claims(entity, "P577")

    if not dates:
        return "Chưa cập nhật"

    value = dates[0].get("time", "")

    match = re.search(r"\+?(-?\d+)-", value)

    if match:

        year = int(match.group(1))

        return (
            f"{abs(year)} TCN"
            if year < 0 else str(year)
        )

    return "Chưa cập nhật"


# =====================================================
# 12. MOVIE DURATION
# =====================================================

def get_duration(entity):

    values = get_claims(entity, "P2047")

    if not values:
        return "Chưa cập nhật"

    try:

        minutes = float(
            values[0]["amount"].replace("+", "")
        )

        return f"{minutes:g} phút"

    except (KeyError, ValueError, TypeError):
        return "Chưa cập nhật"


# =====================================================
# 13. GET POSTER
# =====================================================

def get_wikidata_poster(entity):

    images = get_claims(entity, "P18")

    if images and isinstance(images[0], str):

        return (
            COMMONS_FILE
            + quote(
                images[0].replace(" ", "_"),
                safe=""
            )
        )

    return None


@st.cache_data(ttl=3600, show_spinner=False)
def search_commons_poster(movie_name):

    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": f'"{movie_name}" film poster',
        "gsrnamespace": 6,
        "gsrlimit": 10,
        "prop": "imageinfo",
        "iiprop": "url",
        "iiurlwidth": 600,
        "format": "json"
    }

    try:

        response = requests.get(
            COMMONS_API,
            params=params,
            headers=HEADERS,
            timeout=20
        )

        response.raise_for_status()

        pages = (
            response.json()
            .get("query", {})
            .get("pages", {})
        )

        for page in pages.values():

            title = page.get("title", "").lower()

            if "poster" not in title:
                continue

            images = page.get("imageinfo", [])

            if images:

                return (
                    images[0].get("thumburl")
                    or images[0].get("url")
                )

    except requests.RequestException:
        pass

    return None


def get_poster(entity, movie_name):

    poster = get_wikidata_poster(entity)

    if poster:
        return poster, "Wikidata"

    poster = search_commons_poster(movie_name)

    if poster:
        return poster, "Wikimedia Commons"

    return None, None


# =====================================================
# 14. TRAILER AND IMDB
# =====================================================

def get_trailer(entity):

    videos = get_claims(entity, "P1651")

    if videos and isinstance(videos[0], str):

        return (
            "https://www.youtube.com/watch?v="
            + videos[0]
        )

    return None


def get_imdb(entity):

    values = get_claims(entity, "P345")

    if values and isinstance(values[0], str):

        return (
            "https://www.imdb.com/title/"
            + values[0]
            + "/"
        )

    return None


# =====================================================
# 15. BUILD MOVIE
# =====================================================

def build_movie(qid, entity):

    labels = entity.get("labels", {})
    descriptions = entity.get("descriptions", {})

    name = (
        labels.get("vi", {}).get("value")
        or labels.get("en", {}).get("value")
        or qid
    )

    original_name = (
        labels.get("en", {}).get("value")
        or name
    )

    description = (
        descriptions.get("vi", {}).get("value")
        or descriptions.get("en", {}).get("value")
        or "Chưa có mô tả."
    )

    poster, image_source = get_poster(
        entity,
        name
    )

    return {
        "id": qid,
        "name": name,
        "original_name": original_name,
        "description": description,
        "year": get_year(entity),
        "duration": get_duration(entity),
        "poster": poster,
        "image_source": image_source,
        "directors": get_related_names(entity, "P57"),
        "actors": get_related_names(entity, "P161"),
        "genres": get_related_names(entity, "P136"),
        "countries": get_related_names(entity, "P495"),
        "companies": get_related_names(entity, "P272"),
        "trailer": get_trailer(entity),
        "imdb": get_imdb(entity),
        "wikidata_url": f"https://www.wikidata.org/wiki/{qid}"
    }


# =====================================================
# 16. DISPLAY REVIEW
# =====================================================

def show_review(review, show_movie=True):

    with st.container(border=True):

        if show_movie:

            st.markdown(
                f"🎬 **{html.escape(str(review['movie_name']))}**"
            )

        col1, col2 = st.columns([3, 1])

        with col1:

            st.markdown(
                f"👤 **{html.escape(str(review['reviewer']))}**"
            )

        with col2:

            st.markdown(
                f"⭐ **{int(review['score'])}/10**"
            )

        st.write(review["comment"])

        st.caption(
            str(review["created_at"])[:19]
            .replace("T", " ")
        )


# =====================================================
# 17. STATISTICS HELPER
# =====================================================

def get_statistics(df):

    if df.empty:

        return {
            "total": 0,
            "average": 0,
            "movies": 0
        }

    return {
        "total": len(df),
        "average": df["score"].mean(),
        "movies": df["movie_id"].nunique()
    }


# =====================================================
# 18. SESSION STATE
# =====================================================

if "search_results" not in st.session_state:
    st.session_state.search_results = []

if "selected_movie_id" not in st.session_state:
    st.session_state.selected_movie_id = None


# =====================================================
# 19. SIDEBAR
# =====================================================

st.sidebar.markdown(
    "<h2 style='color:#F4CA68'>🎬 MOVIE REVIEW</h2>",
    unsafe_allow_html=True
)

st.sidebar.caption("CINEMA COMMUNITY")

st.sidebar.divider()

menu = st.sidebar.radio(
    "ĐIỀU HƯỚNG",
    [
        "🏠 Trang chủ",
        "🔍 Tìm kiếm phim",
        "⭐ Cộng đồng Review",
        "📊 Thống kê"
    ]
)

st.sidebar.divider()

st.sidebar.markdown("""
🎥 Khám phá phim

⭐ Chia sẻ cảm nhận

💬 Kết nối cộng đồng
""")

st.sidebar.divider()

st.sidebar.success("🟢 SQLite Database hoạt động")

st.sidebar.caption(
    "Dữ liệu được lưu trong movie_reviews.db"
)


# =====================================================
# 20. HOME PAGE
# =====================================================

if menu == "🏠 Trang chủ":

    st.markdown("""
    <div class="hero">
        <div class="hero-title">🎬 MOVIE REVIEW</div>
        <div class="hero-subtitle">
            Khám phá thế giới điện ảnh.<br>
            Tìm kiếm phim, chia sẻ cảm nhận và kết nối
            cùng cộng đồng yêu phim.
        </div>
    </div>
    """, unsafe_allow_html=True)

    try:

        reviews = load_reviews()

        stats = get_statistics(reviews)

        c1, c2, c3 = st.columns(3)

        c1.metric(
            "💬 Tổng lượt review",
            stats["total"]
        )

        c2.metric(
            "⭐ Điểm trung bình",
            f"{stats['average']:.1f}/10"
        )

        c3.metric(
            "🎬 Phim được review",
            stats["movies"]
        )

        st.divider()

        st.markdown(
            '<div class="section-title">✨ KHÁM PHÁ ĐIỆN ẢNH</div>',
            unsafe_allow_html=True
        )

        st.write(
            "Tìm kiếm bộ phim yêu thích và chia sẻ "
            "đánh giá với cộng đồng."
        )

        if st.button(
            "🔍 TÌM KIẾM PHIM",
            use_container_width=True
        ):

            st.session_state.search_results = []
            st.session_state.selected_movie_id = None

            st.session_state.page_search = True

            st.rerun()

        st.divider()

        st.markdown(
            '<div class="section-title">💬 REVIEW MỚI NHẤT</div>',
            unsafe_allow_html=True
        )

        if reviews.empty:

            st.info(
                "Chưa có đánh giá nào. "
                "Hãy là người đầu tiên review phim!"
            )

        else:

            for _, review in reviews.head(5).iterrows():

                show_review(review)

    except sqlite3.Error as e:

        st.error(f"Lỗi cơ sở dữ liệu: {e}")


# =====================================================
# 21. SEARCH PAGE
# =====================================================

elif menu == "🔍 Tìm kiếm phim":

    st.title("🔍 TÌM KIẾM PHIM")

    st.caption(
        "Tra cứu phim bằng Wikidata - Không cần API Key."
    )

    with st.form("movie_search_form"):

        keyword = st.text_input(
            "Tên phim",
            placeholder="Avengers, Titanic, Doraemon..."
        )

        search_button = st.form_submit_button(
            "🔍 TÌM KIẾM",
            use_container_width=True
        )

    if search_button:

        if len(keyword.strip()) < 2:

            st.warning(
                "Vui lòng nhập ít nhất 2 ký tự."
            )

        else:

            try:

                with st.spinner("Đang tìm kiếm phim..."):

                    results = search_movies(
                        keyword.strip()
                    )

                st.session_state.search_results = results

                if results:

                    st.session_state.selected_movie_id = (
                        results[0]["id"]
                    )

                else:

                    st.warning("Không tìm thấy phim.")

            except requests.RequestException as e:

                st.error(
                    f"Lỗi kết nối Wikidata: {e}"
                )

    results = st.session_state.search_results

    if results:

        st.divider()

        st.success(
            f"Tìm thấy {len(results)} kết quả."
        )

        ids = [item["id"] for item in results]

        default_index = (
            ids.index(st.session_state.selected_movie_id)
            if st.session_state.selected_movie_id in ids
            else 0
        )

        selected_id = st.selectbox(
            "Chọn phim muốn xem",
            options=ids,
            index=default_index,
            format_func=lambda qid: next(
                (
                    f"{item['name']} ({qid})"
                    for item in results
                    if item["id"] == qid
                ),
                qid
            )
        )

        st.session_state.selected_movie_id = selected_id

        try:

            with st.spinner("Đang tải thông tin phim..."):

                entity = get_movie_entity(selected_id)

                movie = build_movie(
                    selected_id,
                    entity
                )

            st.divider()

            st.title(movie["name"])

            st.caption(
                f"Tên gốc: {movie['original_name']}"
            )

            col1, col2 = st.columns([1, 2])

            with col1:

                if movie["poster"]:

                    st.image(
                        movie["poster"],
                        use_container_width=True
                    )

                    st.caption(
                        f"Nguồn ảnh: {movie['image_source']}"
                    )

                else:

                    st.info("Chưa tìm thấy poster.")

            with col2:

                st.subheader("📌 THÔNG TIN PHIM")

                st.write(
                    f"**Năm phát hành:** {movie['year']}"
                )

                st.write(
                    f"**Thời lượng:** {movie['duration']}"
                )

                st.write(
                    "**Đạo diễn:** "
                    + (
                        ", ".join(movie["directors"])
                        or "Chưa cập nhật"
                    )
                )

                st.write(
                    "**Thể loại:** "
                    + (
                        ", ".join(movie["genres"])
                        or "Chưa cập nhật"
                    )
                )

                st.write(
                    "**Quốc gia:** "
                    + (
                        ", ".join(movie["countries"])
                        or "Chưa cập nhật"
                    )
                )

                st.write(
                    "**Hãng sản xuất:** "
                    + (
                        ", ".join(movie["companies"])
                        or "Chưa cập nhật"
                    )
                )

                st.markdown(
                    f"[🌐 Wikidata]({movie['wikidata_url']})"
                )

                if movie["imdb"]:

                    st.markdown(
                        f"[⭐ IMDb]({movie['imdb']})"
                    )

            st.divider()

            st.subheader("📖 GIỚI THIỆU")

            st.write(movie["description"])

            st.divider()

            st.subheader("🎭 DIỄN VIÊN")

            if movie["actors"]:

                actor_cols = st.columns(4)

                for i, actor in enumerate(movie["actors"][:20]):

                    with actor_cols[i % 4]:

                        st.write(f"🎭 {actor}")

            else:

                st.info("Chưa có thông tin diễn viên.")

            st.divider()

            st.subheader("▶️ TRAILER")

            if movie["trailer"]:

                st.video(movie["trailer"])

            else:

                trailer_url = (
                    "https://www.youtube.com/results?search_query="
                    + quote(movie["name"] + " official trailer")
                )

                st.link_button(
                    "🔎 Tìm trailer trên YouTube",
                    trailer_url
                )

            # -----------------------------------------
            # REVIEW FORM
            # -----------------------------------------

            st.divider()

            st.subheader("⭐ VIẾT ĐÁNH GIÁ")

            with st.form(f"review_form_{selected_id}"):

                reviewer = st.text_input(
                    "Tên người đánh giá",
                    max_chars=50,
                    placeholder="Nhập tên của bạn"
                )

                score = st.slider(
                    "Điểm đánh giá",
                    min_value=1,
                    max_value=10,
                    value=8
                )

                comment = st.text_area(
                    "Cảm nhận của bạn",
                    max_chars=2000,
                    height=120,
                    placeholder="Chia sẻ cảm nhận về bộ phim..."
                )

                submit = st.form_submit_button(
                    "📩 GỬI ĐÁNH GIÁ",
                    use_container_width=True
                )

                if submit:

                    if not reviewer.strip() or not comment.strip():

                        st.warning(
                            "Vui lòng nhập tên và nội dung đánh giá."
                        )

                    else:

                        try:

                            save_review(
                                movie["id"],
                                movie["name"],
                                reviewer.strip(),
                                score,
                                comment.strip()
                            )

                            st.success(
                                "Đánh giá đã được lưu thành công!"
                            )

                            st.rerun()

                        except sqlite3.Error as e:

                            st.error(
                                f"Không thể lưu đánh giá: {e}"
                            )

            # -----------------------------------------
            # COMMUNITY REVIEW
            # -----------------------------------------

            st.divider()

            st.subheader("💬 CỘNG ĐỒNG REVIEW")

            movie_reviews = load_reviews(selected_id)

            if not movie_reviews.empty:

                c1, c2 = st.columns(2)

                c1.metric(
                    "⭐ Điểm cộng đồng",
                    f"{movie_reviews['score'].mean():.1f}/10"
                )

                c2.metric(
                    "💬 Số lượt đánh giá",
                    len(movie_reviews)
                )

                for _, review in movie_reviews.iterrows():

                    show_review(
                        review,
                        show_movie=False
                    )

            else:

                st.info(
                    "Bộ phim này chưa có đánh giá nào."
                )

        except requests.RequestException as e:

            st.error(
                f"Không thể tải thông tin phim: {e}"
            )

        except Exception as e:

            st.error(
                f"Đã xảy ra lỗi: {e}"
            )


# =====================================================
# 22. COMMUNITY PAGE
# =====================================================

elif menu == "⭐ Cộng đồng Review":

    st.title("💬 CỘNG ĐỒNG REVIEW")

    if st.button("🔄 LÀM MỚI DỮ LIỆU"):

        st.rerun()

    try:

        df = load_reviews()

        if df.empty:

            st.info(
                "Chưa có đánh giá từ cộng đồng."
            )

        else:

            stats = get_statistics(df)

            c1, c2 = st.columns(2)

            c1.metric(
                "⭐ Điểm review cộng đồng",
                f"{stats['average']:.1f}/10"
            )

            c2.metric(
                "💬 Tổng lượt đánh giá",
                stats["total"]
            )

            st.divider()

            movie_options = (
                df[["movie_id", "movie_name"]]
                .drop_duplicates("movie_id")
            )

            selected_movie = st.selectbox(
                "Lọc đánh giá theo phim",
                ["Tất cả phim"]
                + movie_options["movie_name"].tolist()
            )

            if selected_movie != "Tất cả phim":

                df = df[
                    df["movie_name"] == selected_movie
                ]

            st.write(
                f"Hiển thị {len(df)} đánh giá."
            )

            for _, review in df.iterrows():

                show_review(review)

    except sqlite3.Error as e:

        st.error(f"Lỗi cơ sở dữ liệu: {e}")


# =====================================================
# 23. STATISTICS PAGE
# =====================================================

elif menu == "📊 Thống kê":

    st.title("📊 THỐNG KÊ CỘNG ĐỒNG")

    if st.button("🔄 CẬP NHẬT THỐNG KÊ"):

        st.rerun()

    try:

        df = load_reviews()

        if df.empty:

            st.info(
                "Chưa có dữ liệu để thống kê."
            )

        else:

            stats = get_statistics(df)

            c1, c2, c3 = st.columns(3)

            c1.metric(
                "💬 Tổng review",
                stats["total"]
            )

            c2.metric(
                "⭐ Điểm trung bình",
                f"{stats['average']:.2f}/10"
            )

            c3.metric(
                "🎬 Số phim",
                stats["movies"]
            )

            st.divider()

            st.subheader("🏆 XẾP HẠNG PHIM")

            ranking = (
                df.groupby(["movie_id", "movie_name"])
                .agg(
                    diem_trung_binh=("score", "mean"),
                    so_luot=("score", "count")
                )
                .reset_index()
                .sort_values(
                    ["diem_trung_binh", "so_luot"],
                    ascending=[False, False]
                )
            )

            ranking_display = ranking.rename(
                columns={
                    "movie_name": "Tên phim",
                    "diem_trung_binh": "Điểm trung bình",
                    "so_luot": "Lượt đánh giá"
                }
            )

            st.dataframe(
                ranking_display[
                    [
                        "Tên phim",
                        "Điểm trung bình",
                        "Lượt đánh giá"
                    ]
                ],
                use_container_width=True,
                hide_index=True
            )

            st.divider()

            st.subheader("⭐ ĐIỂM REVIEW THEO PHIM")

            st.bar_chart(
                ranking.set_index("movie_name")[
                    "diem_trung_binh"
                ]
            )

            st.divider()

            st.subheader("📈 SỐ LƯỢT ĐÁNH GIÁ")

            st.bar_chart(
                ranking.set_index("movie_name")[
                    "so_luot"
                ]
            )

            st.divider()

            st.subheader("📋 DỮ LIỆU ĐÁNH GIÁ")

            st.dataframe(
                df,
                use_container_width=True,
                hide_index=True
            )

            csv = df.to_csv(
                index=False
            ).encode("utf-8-sig")

            st.download_button(
                "📥 TẢI DỮ LIỆU REVIEW CSV",
                data=csv,
                file_name="movie_reviews.csv",
                mime="text/csv",
                use_container_width=True
            )

    except sqlite3.Error as e:

        st.error(f"Lỗi thống kê: {e}")


# =====================================================
# 24. FOOTER
# =====================================================

st.divider()

st.markdown("""
<div class="footer">
    <div style="font-size:24px;color:#F4CA68;font-weight:800">
        🎬 MOVIE REVIEW
    </div>
    DISCOVER - WATCH - REVIEW<br>
    A COMMUNITY FOR MOVIE LOVERS<br>
    Powered by Wikidata & SQLite
</div>
""", unsafe_allow_html=True)
