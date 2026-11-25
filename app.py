
import streamlit as st
import requests
import sqlite3
import pandas as pd
import re
from urllib.parse import quote
from datetime import datetime

# =====================================================
# 1. CẤU HÌNH ỨNG DỤNG
# =====================================================

st.set_page_config(
    page_title="Movie Review",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded"
)

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
WIKIPEDIA_API = "https://en.wikipedia.org/api/rest_v1/page/summary/"
VI_WIKIPEDIA_API = "https://vi.wikipedia.org/api/rest_v1/page/summary/"
COMMONS_URL = "https://commons.wikimedia.org/wiki/Special:FilePath/"

HEADERS = {
    "User-Agent": "MovieReviewStreamlit/1.0 (educational project)"
}

DB_NAME = "movie_reviews.db"

# =====================================================
# 2. GIAO DIỆN CSS
# =====================================================

st.markdown("""
<style>

.stApp {
    background-color: #101014;
    color: #FFFFFF;
}

[data-testid="stSidebar"] {
    background-color: #1C1C25;
}

h1, h2, h3 {
    color: #F5C518 !important;
}

.movie-title {
    color: #F5C518;
    font-size: 30px;
    font-weight: bold;
}

.movie-card {
    background-color: #202029;
    padding: 18px;
    border-radius: 14px;
}

div.stButton > button {
    background-color: #F5C518;
    color: #111111;
    border: none;
    border-radius: 8px;
    font-weight: bold;
}

div.stButton > button:hover {
    background-color: #D9A900;
    color: black;
}

[data-testid="stMetric"] {
    background-color: #202029;
    padding: 15px;
    border-radius: 10px;
}

</style>
""", unsafe_allow_html=True)


# =====================================================
# 3. DATABASE SQLITE
# =====================================================

def get_connection():
    return sqlite3.connect(DB_NAME)


def init_database():

    conn = get_connection()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            movie_id TEXT NOT NULL,
            movie_name TEXT NOT NULL,
            reviewer TEXT NOT NULL,
            score INTEGER NOT NULL,
            comment TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()


init_database()


# =====================================================
# 4. HÀM GỌI WIKIDATA
# =====================================================

def wikidata_request(params):

    response = requests.get(
        WIKIDATA_API,
        params=params,
        headers=HEADERS,
        timeout=25
    )

    response.raise_for_status()

    return response.json()


# =====================================================
# 5. TÌM KIẾM PHIM
# =====================================================

@st.cache_data(ttl=1800, show_spinner=False)
def search_movies(keyword):

    results = []
    seen_ids = set()

    for language in ["vi", "en"]:

        params = {
            "action": "wbsearchentities",
            "search": keyword,
            "language": language,
            "uselang": language,
            "type": "item",
            "limit": 20,
            "format": "json"
        }

        data = wikidata_request(params)

        for item in data.get("search", []):

            qid = item.get("id")

            if not qid or qid in seen_ids:
                continue

            # Chỉ giữ thực thể có mô tả liên quan đến phim
            description = item.get("description", "").lower()

            is_movie = any(
                word in description
                for word in [
                    "film",
                    "movie",
                    "motion picture",
                    "phim",
                    "điện ảnh"
                ]
            )

            # Một số kết quả tiếng Việt không có mô tả
            if not is_movie and language == "vi":
                continue

            seen_ids.add(qid)

            results.append({
                "id": qid,
                "label": item.get("label", "Unknown"),
                "description": item.get(
                    "description",
                    "Chưa có mô tả"
                )
            })

        if len(results) >= 20:
            break

    return results


# =====================================================
# 6. LẤY CHI TIẾT THỰC THỂ WIKIDATA
# =====================================================

@st.cache_data(ttl=3600, show_spinner=False)
def get_entity_details(qid):

    params = {
        "action": "wbgetentities",
        "ids": qid,
        "props": "labels|descriptions|claims|sitelinks",
        "languages": "vi|en",
        "format": "json"
    }

    data = wikidata_request(params)

    return data.get("entities", {}).get(qid, {})


# =====================================================
# 7. HÀM LẤY GIÁ TRỊ PROPERTY
# =====================================================

def get_claims(entity, property_id):

    claims = entity.get("claims", {})

    property_data = claims.get(property_id, [])

    values = []

    for claim in property_data:

        try:

            value = claim["mainsnak"]["datavalue"]["value"]

            values.append(value)

        except (KeyError, TypeError):
            continue

    return values


# =====================================================
# 8. LẤY NHÃN CÁC THỰC THỂ LIÊN QUAN
# =====================================================

@st.cache_data(ttl=3600, show_spinner=False)
def get_entity_labels(entity_ids):

    entity_ids = list(dict.fromkeys(entity_ids))

    if not entity_ids:
        return {}

    labels = {}

    # Wikidata cho phép truy vấn nhiều ID cùng lúc
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

            item_labels = item.get("labels", {})

            label = (
                item_labels.get("vi", {}).get("value")
                or item_labels.get("en", {}).get("value")
                or qid
            )

            labels[qid] = label

    return labels


def get_related_names(entity, property_id):

    values = get_claims(entity, property_id)

    ids = [
        value["id"]
        for value in values
        if isinstance(value, dict) and "id" in value
    ]

    labels = get_entity_labels(ids)

    return [
        labels.get(qid, qid)
        for qid in ids
    ]


# =====================================================
# 9. LẤY NĂM PHÁT HÀNH
# =====================================================

def get_release_year(entity):

    dates = get_claims(entity, "P577")

    if not dates:
        return "Chưa cập nhật"

    time_value = dates[0].get("time", "")

    match = re.search(r"\+?(-?\d{1,6})-", time_value)

    if match:

        year = int(match.group(1))

        if year < 0:
            return f"{abs(year)} TCN"

        return str(year)

    return "Chưa cập nhật"


# =====================================================
# 10. LẤY THỜI LƯỢNG
# =====================================================

def get_duration(entity):

    durations = get_claims(entity, "P2047")

    if not durations:
        return "Chưa cập nhật"

    amount = durations[0].get("amount", "")

    try:

        minutes = float(amount.replace("+", ""))

        if minutes.is_integer():
            return f"{int(minutes)} phút"

        return f"{minutes:.1f} phút"

    except (ValueError, AttributeError):
        return "Chưa cập nhật"


# =====================================================
# 11. LẤY POSTER
# =====================================================

def get_poster(entity):

    images = get_claims(entity, "P18")

    if images:

        filename = images[0]

        return COMMONS_URL + quote(
            filename.replace(" ", "_"),
            safe=""
        )

    return None


# =====================================================
# 12. LẤY WIKIPEDIA
# =====================================================

@st.cache_data(ttl=3600, show_spinner=False)
def get_wikipedia_summary(title, language):

    base_url = (
        VI_WIKIPEDIA_API
        if language == "vi"
        else WIKIPEDIA_API
    )

    url = base_url + quote(title.replace(" ", "_"), safe="")

    try:

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=15
        )

        if response.status_code == 200:

            return response.json()

    except requests.RequestException:
        pass

    return {}


def get_movie_overview(entity):

    sitelinks = entity.get("sitelinks", {})

    # Ưu tiên Wikipedia tiếng Việt
    for site in ["viwiki", "enwiki"]:

        if site in sitelinks:

            title = sitelinks[site]["title"]

            language = (
                "vi" if site == "viwiki" else "en"
            )

            summary = get_wikipedia_summary(
                title,
                language
            )

            extract = summary.get("extract")

            if extract:

                return {
                    "text": extract,
                    "url": summary.get("content_urls", {})
                    .get("desktop", {})
                    .get("page", ""),
                    "language": language
                }

    return {
        "text": "Chưa có nội dung giới thiệu trên Wikipedia.",
        "url": "",
        "language": ""
    }


# =====================================================
# 13. LẤY TRAILER
# =====================================================

def get_trailer(entity):

    videos = get_claims(entity, "P1651")

    if videos:

        video_id = videos[0]

        return f"https://www.youtube.com/watch?v={video_id}"

    return None


# =====================================================
# 14. LẤY MÃ IMDB
# =====================================================

def get_imdb(entity):

    values = get_claims(entity, "P345")

    if values:

        imdb_id = values[0]

        return f"https://www.imdb.com/title/{imdb_id}/"

    return None


# =====================================================
# 15. TỔNG HỢP THÔNG TIN PHIM
# =====================================================

def build_movie_details(qid, entity):

    labels = entity.get("labels", {})

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
        entity.get("descriptions", {})
        .get("vi", {})
        .get("value")
        or entity.get("descriptions", {})
        .get("en", {})
        .get("value")
        or "Chưa có mô tả."
    )

    directors = get_related_names(entity, "P57")

    actors = get_related_names(entity, "P161")

    genres = get_related_names(entity, "P136")

    countries = get_related_names(entity, "P495")

    companies = get_related_names(entity, "P272")

    overview = get_movie_overview(entity)

    return {
        "id": qid,
        "name": name,
        "original_name": original_name,
        "description": description,
        "year": get_release_year(entity),
        "duration": get_duration(entity),
        "poster": get_poster(entity),
        "directors": directors,
        "actors": actors,
        "genres": genres,
        "countries": countries,
        "companies": companies,
        "overview": overview,
        "trailer": get_trailer(entity),
        "imdb": get_imdb(entity),
        "wikidata_url": f"https://www.wikidata.org/wiki/{qid}"
    }


# =====================================================
# 16. DATABASE REVIEW
# =====================================================

def save_review(movie_id, movie_name, reviewer, score, comment):

    conn = get_connection()

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
        score,
        comment,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))

    conn.commit()
    conn.close()


def load_reviews(movie_id=None):

    conn = get_connection()

    if movie_id:

        df = pd.read_sql_query(
            """
            SELECT * FROM reviews
            WHERE movie_id = ?
            ORDER BY id DESC
            """,
            conn,
            params=(movie_id,)
        )

    else:

        df = pd.read_sql_query(
            """
            SELECT * FROM reviews
            ORDER BY id DESC
            """,
            conn
        )

    conn.close()

    return df


# =====================================================
# 17. SIDEBAR
# =====================================================

st.sidebar.title("🎬 MOVIE REVIEW")

st.sidebar.caption(
    "Discover - Watch - Review"
)

st.sidebar.markdown("---")

menu = st.sidebar.radio(
    "ĐIỀU HƯỚNG",
    [
        "🏠 Trang chủ",
        "🔍 Tìm kiếm phim",
        "⭐ Đánh giá phim",
        "📊 Thống kê"
    ]
)

st.sidebar.markdown("---")

st.sidebar.info(
    "Nguồn dữ liệu: Wikidata & Wikipedia"
)

st.sidebar.caption(
    "Không cần API Key"
)


# =====================================================
# 18. TRANG CHỦ
# =====================================================

if menu == "🏠 Trang chủ":

    st.title("🎬 MOVIE REVIEW")

    st.subheader(
        "Khám phá thế giới điện ảnh"
    )

    st.write(
        "Tìm kiếm thông tin phim trên Wikidata, "
        "khám phá nội dung, diễn viên, đạo diễn "
        "và chia sẻ cảm nhận của bạn."
    )

    st.markdown("---")

    reviews = load_reviews()

    total_reviews = len(reviews)

    if total_reviews > 0:

        average_score = reviews["score"].mean()

        total_movies = reviews["movie_id"].nunique()

    else:

        average_score = 0

        total_movies = 0

    col1, col2, col3 = st.columns(3)

    col1.metric(
        "💬 Tổng lượt review",
        total_reviews
    )

    col2.metric(
        "⭐ Điểm review trung bình",
        f"{average_score:.1f}/10"
    )

    col3.metric(
        "🎥 Số phim được review",
        total_movies
    )

    st.markdown("---")

    st.header("✨ KHÁM PHÁ ĐIỆN ẢNH")

    st.write(
        "Bạn có thể tìm kiếm tên bất kỳ bộ phim nào "
        "được ghi nhận trong cơ sở dữ liệu Wikidata."
    )

    st.markdown("""
    - 🔍 Tìm kiếm phim quốc tế và phim Việt Nam.
    - 🎭 Khám phá diễn viên và đạo diễn.
    - 📖 Đọc nội dung phim từ Wikipedia.
    - ▶️ Xem trailer nếu có dữ liệu.
    - ⭐ Chấm điểm và viết đánh giá.
    """)

    st.markdown("---")

    st.subheader("🔥 ĐÁNH GIÁ GẦN ĐÂY")

    if not reviews.empty:

        for _, review in reviews.head(5).iterrows():

            with st.container(border=True):

                st.write(f"🎬 **{review['movie_name']}**")

                st.write(
                    f"👤 {review['reviewer']} "
                    f"| ⭐ {review['score']}/10"
                )

                st.write(review["comment"])

    else:

        st.info(
            "Chưa có đánh giá nào. "
            "Hãy tìm kiếm phim và viết review đầu tiên!"
        )


# =====================================================
# 19. TÌM KIẾM PHIM
# =====================================================

elif menu == "🔍 Tìm kiếm phim":

    st.title("🔍 TÌM KIẾM PHIM")

    st.write(
        "Nhập tên phim để tìm kiếm dữ liệu trực tiếp "
        "từ Wikidata."
    )

    # Form tìm kiếm
    with st.form("search_form"):

        keyword = st.text_input(
            "Tên bộ phim",
            placeholder="Ví dụ: Avatar, Titanic, Inception..."
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

            st.session_state.search_results = []

        else:

            try:

                with st.spinner("Đang tìm kiếm trên Wikidata..."):

                    results = search_movies(keyword.strip())

                st.session_state.search_results = results

                st.session_state.search_keyword = keyword.strip()

            except requests.RequestException as e:

                st.error(
                    f"Không thể kết nối Wikidata: {e}"
                )

                st.session_state.search_results = []

    # Hiển thị kết quả
    results = st.session_state.get(
        "search_results",
        []
    )

    if results:

        st.markdown("---")

        st.success(
            f"Tìm thấy {len(results)} kết quả."
        )

        selected_id = st.selectbox(
            "🎬 Chọn bộ phim muốn xem",
            options=[item["id"] for item in results],
            format_func=lambda qid: next(
                (
                    f"{item['label']} ({qid}) - {item['description']}"
                    for item in results
                    if item["id"] == qid
                ),
                qid
            ),
            key="movie_selector"
        )

        try:

            with st.spinner("Đang tải chi tiết phim..."):

                entity = get_entity_details(selected_id)

                movie = build_movie_details(
                    selected_id,
                    entity
                )

            # ==========================================
            # CHI TIẾT PHIM
            # ==========================================

            st.markdown("---")

            st.markdown(
                f'<div class="movie-title">{movie["name"]}</div>',
                unsafe_allow_html=True
            )

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

                else:

                    st.info(
                        "Phim chưa có hình ảnh trong Wikidata."
                    )

            with col2:

                st.subheader("📌 THÔNG TIN CHI TIẾT")

                st.write(
                    f"**Mã Wikidata:** {movie['id']}"
                )

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
                        if movie["directors"]
                        else "Chưa cập nhật"
                    )
                )

                st.write(
                    "**Thể loại:** "
                    + (
                        ", ".join(movie["genres"])
                        if movie["genres"]
                        else "Chưa cập nhật"
                    )
                )

                st.write(
                    "**Quốc gia:** "
                    + (
                        ", ".join(movie["countries"])
                        if movie["countries"]
                        else "Chưa cập nhật"
                    )
                )

                st.write(
                    "**Hãng sản xuất:** "
                    + (
                        ", ".join(movie["companies"])
                        if movie["companies"]
                        else "Chưa cập nhật"
                    )
                )

                st.markdown(
                    f"[🌐 Xem trên Wikidata]({movie['wikidata_url']})"
                )

                if movie["imdb"]:

                    st.markdown(
                        f"[⭐ Xem hồ sơ IMDb]({movie['imdb']})"
                    )

            # ==========================================
            # MÔ TẢ PHIM
            # ==========================================

            st.markdown("---")

            st.subheader("📖 GIỚI THIỆU PHIM")

            st.write(movie["description"])

            st.markdown("---")

            st.subheader("📚 NỘI DUNG CHI TIẾT")

            st.write(movie["overview"]["text"])

            if movie["overview"]["url"]:

                st.markdown(
                    f"[Đọc thêm trên Wikipedia]({movie['overview']['url']})"
                )

            # ==========================================
            # DIỄN VIÊN
            # ==========================================

            st.markdown("---")

            st.subheader("🎭 DÀN DIỄN VIÊN")

            if movie["actors"]:

                actor_cols = st.columns(4)

                for i, actor in enumerate(movie["actors"][:20]):

                    with actor_cols[i % 4]:

                        st.write(f"🎭 {actor}")

            else:

                st.info(
                    "Wikidata chưa có thông tin diễn viên."
                )

            # ==========================================
            # TRAILER
            # ==========================================

            st.markdown("---")

            st.subheader("▶️ TRAILER")

            if movie["trailer"]:

                st.video(movie["trailer"])

            else:

                st.info(
                    "Chưa có mã trailer YouTube trong Wikidata."
                )

                search_url = (
                    "https://www.youtube.com/results?search_query="
                    + quote(movie["name"] + " official trailer")
                )

                st.markdown(
                    f"[🔎 Tìm trailer trên YouTube]({search_url})"
                )

            # ==========================================
            # REVIEW
            # ==========================================

            st.markdown("---")

            st.subheader("⭐ VIẾT ĐÁNH GIÁ PHIM")

            with st.form(f"review_form_{selected_id}"):

                reviewer = st.text_input(
                    "Tên của bạn",
                    placeholder="Nhập tên người đánh giá"
                )

                score = st.slider(
                    "Chấm điểm bộ phim",
                    min_value=1,
                    max_value=10,
                    value=8
                )

                comment = st.text_area(
                    "Nhận xét của bạn",
                    placeholder="Bạn cảm thấy thế nào về bộ phim?",
                    height=130
                )

                submit_review = st.form_submit_button(
                    "📩 GỬI ĐÁNH GIÁ",
                    use_container_width=True
                )

                if submit_review:

                    if not reviewer.strip() or not comment.strip():

                        st.warning(
                            "Vui lòng nhập tên và nội dung đánh giá."
                        )

                    else:

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

            # ==========================================
            # REVIEW CỦA BỘ PHIM
            # ==========================================

            st.markdown("---")

            st.subheader("💬 CỘNG ĐỒNG REVIEW")

            movie_reviews = load_reviews(movie["id"])

            if not movie_reviews.empty:

                average = movie_reviews["score"].mean()

                c1, c2 = st.columns(2)

                c1.metric(
                    "⭐ Điểm review cộng đồng",
                    f"{average:.1f}/10"
                )

                c2.metric(
                    "💬 Số lượt đánh giá",
                    len(movie_reviews)
                )

                for _, review in movie_reviews.iterrows():

                    with st.container(border=True):

                        st.write(
                            f"👤 **{review['reviewer']}**"
                        )

                        st.write(
                            f"⭐ {review['score']}/10"
                        )

                        st.write(review["comment"])

                        st.caption(review["created_at"])

            else:

                st.info(
                    "Bộ phim này chưa có đánh giá từ cộng đồng."
                )

        except requests.RequestException as e:

            st.error(
                f"Lỗi khi lấy dữ liệu: {e}"
            )

    elif st.session_state.get("search_keyword"):

        st.warning(
            "Không tìm thấy phim phù hợp. "
            "Hãy thử tên tiếng Anh hoặc tên gốc."
        )


# =====================================================
# 20. TRANG ĐÁNH GIÁ
# =====================================================

elif menu == "⭐ Đánh giá phim":

    st.title("⭐ CỘNG ĐỒNG REVIEW")

    reviews = load_reviews()

    if not reviews.empty:

        st.metric(
            "Tổng số đánh giá",
            len(reviews)
        )

        for _, review in reviews.iterrows():

            with st.container(border=True):

                st.subheader(
                    f"🎬 {review['movie_name']}"
                )

                st.write(
                    f"👤 Người đánh giá: {review['reviewer']}"
                )

                st.write(
                    f"⭐ Điểm: {review['score']}/10"
                )

                st.write(review["comment"])

                st.caption(review["created_at"])

    else:

        st.info(
            "Chưa có đánh giá nào. "
            "Hãy tìm kiếm phim để bắt đầu review!"
        )


# =====================================================
# 21. TRANG THỐNG KÊ
# =====================================================

elif menu == "📊 Thống kê":

    st.title("📊 THỐNG KÊ MOVIE REVIEW")

    df = load_reviews()

    if not df.empty:

        col1, col2, col3 = st.columns(3)

        col1.metric(
            "💬 Tổng lượt review",
            len(df)
        )

        col2.metric(
            "⭐ Điểm trung bình",
            f"{df['score'].mean():.2f}/10"
        )

        col3.metric(
            "🎬 Số phim được review",
            df["movie_id"].nunique()
        )

        st.markdown("---")

        st.subheader("⭐ ĐIỂM REVIEW THEO PHIM")

        chart = (
            df.groupby("movie_name")["score"]
            .mean()
            .sort_values(ascending=False)
        )

        st.bar_chart(chart)

        st.markdown("---")

        st.subheader("📈 SỐ LƯỢT ĐÁNH GIÁ THEO PHIM")

        count_chart = (
            df.groupby("movie_name")["score"]
            .count()
            .sort_values(ascending=False)
        )

        st.bar_chart(count_chart)

        st.markdown("---")

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
            "📥 TẢI DỮ LIỆU CSV",
            data=csv,
            file_name="movie_reviews.csv",
            mime="text/csv"
        )

    else:

        st.info(
            "Chưa có dữ liệu để thống kê."
        )


# =====================================================
# 22. FOOTER
# =====================================================

st.markdown("---")

st.markdown(
    """
    <div style="text-align:center; color:#999999;">
        🎬 MOVIE REVIEW <br>
        Discover - Watch - Review <br>
        Powered by Wikidata & Wikipedia <br>
        © 2026 Movie Review
    </div>
    """,
    unsafe_allow_html=True
)
