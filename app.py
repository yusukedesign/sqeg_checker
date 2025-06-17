# ───────────────── app.py ─────────────────
import os, json, textwrap, datetime, requests, bs4, pandas as pd, warnings
import streamlit as st
from newspaper import Article
from duckduckgo_search import DDGS
import openai

# ─── 環境設定 ──────────────────────────────
warnings.filterwarnings("ignore", category=SyntaxWarning)
openai.api_key = st.secrets["OPENAI_API_KEY"]  # Secrets にキー必須
MODEL_NAME = "gpt-3.5-turbo"                   # 旧APIでも使えるモデル

st.set_page_config(page_title="SQEG クイックチェッカー", page_icon="🔍")
st.title("🔍 SQEG 2025-01 簡易評価ツール")

# ─── 本文取得 ─────────────────────────────
def fetch(src: str):
    """URL なら newspaper3k → 失敗時 requests+BS4。本文が取れなければ空文字。"""
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

# ─── 類似ページ候補 (DuckDuckGo) ─────────────
def search_ddg(query: str, k: int = 5):
    q = query[:100]  # 長すぎると失敗するので 100 文字で切る
    try:
        with DDGS() as ddgs:
            return [f"{r['title']} — {r['body']}" for r in ddgs.text(q, max_results=k)]
    except Exception:
        return []

# ─── プロンプト ───────────────────────────
PROMPT = """
あなたは Google Search Quality Evaluator です。
記事本文と類似ページ候補を渡します。
SQEG 2025-01 (3.2 / 4.6.6 / 5.2.1 / 7.1) に従い次の JSON を返してください。

{
  "pq":"Lowest|Low|Medium|High|Highest",
  "nm":"Fails|Slightly|Moderately|Highly|Fully",
  "effort":0-5,"originality":0-5,"duplication_rate":0-100,
  "skill":0-5,"accuracy":0-5,
  "eeat_summary":"<100字以内>",
  "improvement_advice":"<200字以内>"
}

必ず **JSON オブジェクトのみ** を出力し、前後に説明文や ``` は付けないでください。
"""

# ─── UI ───────────────────────────────────
src = st.text_area("URL または本文を入力して『評価する』を押してください", height=200)
if st.button("評価する") and src.strip():
    with st.spinner("評価中…"):
        title, body = fetch(src.strip())
        if not body:
            st.error("❌ 記事本文を取得できませんでした。URL でなく本文を直接貼って試してください。")
            st.stop()

        query = title or " ".join(body.split()[:15])
        user_content = (
            "###本文\n"
            + textwrap.shorten(body, width=12000, placeholder='...[cut]...')
            + "\n\n###類似\n"
            + "\n".join(search_ddg(query))
        )

        try:
            # 旧 openai<=0.28.x インターフェース
            chat = openai.ChatCompletion.create(
                model=MODEL_NAME,
                temperature=0.1,
                messages=[
                    {"role": "system", "content": PROMPT},
                    {"role": "user",   "content": user_content}
                ]
            )
            raw = chat.choices[0].message.content.strip()
            # ```json ... ``` で返る場合の囲み除去
            if raw.startswith("```"):
                raw = raw.split("```")[1]
            result = json.loads(raw)

        except json.JSONDecodeError:
            st.error("❌ JSON の解析に失敗しました。モデル出力を確認してください。")
            st.write("受信内容:", raw)
            st.stop()
        except Exception as e:
            st.error("❌ 予期しないエラーが発生しました")
            st.exception(e)
            st.stop()

    # ─── 結果表示 ────────────────────────
    st.subheader("評価結果")
    st.json(result, expanded=False)
    if result["pq"] in ["Lowest", "Low"]:
        st.error("⚠️ PQ が低評価です。リライトを検討してください。")

    # ─── CSV ログ ───────────────────────
    pd.DataFrame([{
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "source": src[:100], **result
    }]).to_csv("sqeg_log.csv", mode="a", index=False, header=not os.path.exists("sqeg_log.csv"))
    st.success("結果を sqeg_log.csv に追記しました ✅")
# ─────────────────────────────────────────
