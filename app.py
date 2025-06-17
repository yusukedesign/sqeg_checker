import os, json, textwrap, datetime, pandas as pd, streamlit as st
from newspaper import Article
from duckduckgo_search import DDGS
import openai

# ───────────────────────────────────────────────────────────────
# OpenAI APIキーは .streamlit/secrets.toml に書いてください
#   OPENAI_API_KEY = "sk-xxxxxxxx"
# Streamlit Cloud では「Secrets」タブに同じキーを登録
# ───────────────────────────────────────────────────────────────
openai.api_key = st.secrets["OPENAI_API_KEY"]

st.set_page_config(page_title="SQEG クイックチェッカー", page_icon="🔍", layout="centered")
st.title("🔍 SQEG 2025-01 簡易評価ツール")

src = st.text_area("URL または本文を入力し、下のボタンを押してください", height=200)
if st.button("評価する"):

    # ─── 1. URLなら本文抽出 ────────────────────────────────
    import requests, bs4   # ← 先頭付近の import に追加

def fetch(src: str):
    """URLなら本文抽出。失敗したら空文字を返す。"""
    if src.startswith("http"):
        try:
            art = Article(src, language="ja")
            art.download(); art.parse()
            return art.title or "", art.text
        except Exception:
            # newspaper3k 失敗→ requests + BeautifulSoup
            try:
                html = requests.get(src, timeout=10).text
                soup = bs4.BeautifulSoup(html, "html.parser")
                # <title>タグでタイトルを取得
                title = soup.title.string.strip() if soup.title else ""
                # 本文は <p> を全部つなぐ（簡易）
                body = "\n".join(p.get_text(" ", strip=True) for p in soup.find_all("p"))
                return title, body[:20000]  # 2万字で切る
            except Exception:
                return "", ""
    # 直接本文
    return "", src


    # ─── 2. DuckDuckGoで類似タイトル取得（コピー疑惑チェック用） ───
    def search_ddg(query: str, k: int = 5):
        out = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=k):
                out.append(f"{r['title']} — {r['body']}")
        return out

    query = title if title else " ".join(body.split()[:15])
    similar_snips = search_ddg(query)

    # ─── 3. LLM へ評価依頼 ────────────────────────────────
    SYSTEM_PROMPT = """
あなたは Google Search Quality Evaluator です。
記事本文とウェブ検索で得た類似ページ候補を渡します。
SQEG 2025-01 (3.2 / 4.6.6 / 5.2.1 / 7.1) に従い採点し、次のJSONで出力してください。

{
  "pq": "Lowest|Low|Medium|High|Highest",
  "nm": "Fails|Slightly|Moderately|Highly|Fully",
  "effort": 0-5,
  "originality": 0-5,
  "duplication_rate": 0-100,
  "skill": 0-5,
  "accuracy": 0-5,
  "eeat_summary": "<100字以内>",
  "improvement_advice": "<200字以内>"
}
"""

    with st.spinner("OpenAI で評価中…"):
        truncated_body = textwrap.shorten(body, 12000, placeholder="...[cut]...")
        user_msg = f"### 記事本文\n{truncated_body}\n\n### 類似ページ候補\n" + "\n".join(similar_snips)

        chat = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            temperature=0.1,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg}
            ]
        )
        result = json.loads(chat.choices[0].message.content)

    # ─── 4. 表示 ────────────────────────────────────────
    st.subheader("評価結果")
    st.json(result, expanded=False)

    if result["pq"] in ["Lowest", "Low"]:
        st.error("⚠️ PQ が低評価です。リライト推奨 → 改善アドバイスを確認してください。")

    # ─── 5. CSV ログ保存 ──────────────────────────────
    log_row = {
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "source": src[:100],
        **result
    }
    pd.DataFrame([log_row]).to_csv("sqeg_log.csv", mode="a", index=False, header=not os.path.exists("sqeg_log.csv"))
    st.success("結果を sqeg_log.csv に追記しました ✅")
