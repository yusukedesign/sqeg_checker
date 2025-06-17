import os, json, textwrap, datetime, requests, bs4, pandas as pd
import streamlit as st
from newspaper import Article
from duckduckgo_search import DDGS
import openai, warnings

warnings.filterwarnings("ignore", category=SyntaxWarning)
openai.api_key = st.secrets["OPENAI_API_KEY"]

st.set_page_config(page_title="SQEG クイックチェッカー", page_icon="🔍")
st.title("🔍 SQEG 2025-01 簡易評価ツール")

# ───────── 本文取得 ─────────
def fetch(src: str):
    if src.startswith("http"):
        try:
            art = Article(src, language="ja")
            art.download(); art.parse()
            return art.title or "", art.text
        except Exception:
            try:
                html = requests.get(src, timeout=10, headers={"User-Agent": "Mozilla/5.0"}).text
                soup = bs4.BeautifulSoup(html, "html.parser")
                title = soup.title.string.strip() if soup.title else ""
                body  = "\n".join(p.get_text(" ", strip=True) for p in soup.find_all("p"))
                return title, body[:20000]
            except Exception:
                return "", ""
    return "", src

# ───────── 類似ページ候補 ─────────
def search_ddg(query: str, k: int = 5):
    """DuckDuckGo 検索。失敗したら空リストを返す"""
    # クエリが長すぎるとエラーが出やすいので 100 文字で切る
    q = query[:100]
    try:
        with DDGS() as ddgs:
            return [f"{r['title']} — {r['body']}" for r in ddgs.text(q, max_results=k)]
    except Exception:
        return []

PROMPT = """
あなたは Google Search Quality Evaluator です。
記事本文と類似ページ候補を渡します。
SQEG 2025-01 に従い次のJSONで採点してください。
{
  "pq":"Lowest|Low|Medium|High|Highest",
  "nm":"Fails|Slightly|Moderately|Highly|Fully",
  "effort":0-5,"originality":0-5,"duplication_rate":0-100,
  "skill":0-5,"accuracy":0-5,
  "eeat_summary":"<100字以内>","improvement_advice":"<200字以内>"
}
"""

src = st.text_area("URL または本文を入力して『評価する』を押してください", height=200)
if st.button("評価する") and src.strip():
    with st.spinner("評価中…"):
        title, body = fetch(src.strip())
        if not body:
            st.error("❌ 記事本文を取得できませんでした。URL でなく本文を直接貼って試してください。")
            st.stop()

        query = title or " ".join(body.split()[:15])
        try:
            chat = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                temperature=0.1,
                messages=[
                    {"role": "system", "content": PROMPT},
                    {"role": "user",
                     "content": (
                         "###本文\n"
                         + textwrap.shorten(body, width=12000, placeholder='...[cut]...')
                         + "\n\n###類似\n"
                         + "\n".join(search_ddg(query))
                     )},
                ],
            )
            result = json.loads(chat.choices[0].message.content)
        except Exception as e:
            st.error("❌ 予期しないエラーが発生しました")
            st.exception(e)
            st.stop()

    st.subheader("評価結果")
    st.json(result, expanded=False)
    if result["pq"] in ["Lowest", "Low"]:
        st.error("⚠️ PQ が低評価です。リライトを検討してください。")

    pd.DataFrame([{
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "source": src[:100], **result
    }]).to_csv("sqeg_log.csv", mode="a", index=False, header=not os.path.exists("sqeg_log.csv"))
    st.success("結果を sqeg_log.csv に追記しました ✅")
