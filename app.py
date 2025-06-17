import os, json, textwrap, datetime, requests, bs4, pandas as pd, warnings
import streamlit as st
from newspaper import Article
from duckduckgo_search import DDGS
import openai

# ─── 環境設定 ─────────────────────────────
warnings.filterwarnings("ignore", category=SyntaxWarning)
openai.api_key = st.secrets["OPENAI_API_KEY"]

PRIMARY_MODEL   = "gpt-4o-mini"     # 4o が使えない場合は自動で fallback
FALLBACK_MODEL  = "gpt-3.5-turbo"

st.set_page_config(page_title="SQEG クイックチェッカー", page_icon="🔍")
st.title("🔍 SQEG 2025-01 簡易評価ツール（Jina API 対応）")

# ─── 本文取得 ─────────────────────────────
def fetch(src: str):
    """URL→ newspaper3k → requests+BS4 → Jina AI の 3 段階で本文抽出"""
    ua = {"User-Agent": "Mozilla/5.0"}
    if src.startswith("http"):
        # ① newspaper3k
        try:
            art = Article(src, language="ja")
            art.download(); art.parse()
            return art.title or "", art.text
        except Exception:
            pass

        # ② requests + BeautifulSoup
        try:
            html = requests.get(src, timeout=10, headers=ua).text
            soup = bs4.BeautifulSoup(html, "html.parser")
            title = soup.title.string.strip() if soup.title else ""
            body  = "\n".join(p.get_text(" ", strip=True) for p in soup.find_all("p"))
            if body.strip():
                return title, body[:20000]
        except Exception:
            pass

        # ③ Jina AI Readability API
        try:
            api = "https://r.jina.ai/http://" + src.lstrip("https://").lstrip("http://")
            jres = requests.get(api, timeout=10, headers=ua).json()
            title = jres.get("title", "").strip()
            body  = jres.get("content", "").strip()
            return title, body[:20000]
        except Exception:
            return "", ""

    # 直接本文
    return "", src

# ─── 類似ページ候補 ────────────────────────
def search_ddg(query: str, k: int = 5):
    q = query[:100]
    try:
        with DDGS() as ddgs:
            return [f"{r['title']} — {r['body']}" for r in ddgs.text(q, max_results=k)]
    except Exception:
        return []

# ─── プロンプト ───────────────────────────
PROMPT = """
あなたは Google Search Quality Evaluator です。
記事本文と類似ページ候補を渡します。
SQEG 2025-01 に従い、日本語で次の JSON を返してください。

{
  "pq":"Lowest|Low|Medium|High|Highest",
  "nm":"Fails|Slightly|Moderately|Highly|Fully",
  "effort":0-5,"originality":0-5,"duplication_rate":0-100,
  "skill":0-5,"accuracy":0-5,
  "eeat_summary":"<100字以内>",
  "improvement_advice":"<200字以内>"
}

必ず JSON オブジェクトのみを出力してください。
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

        def call_llm(model):
            return openai.ChatCompletion.create(
                model=model, temperature=0.1,
                messages=[{"role":"system","content":PROMPT},
                          {"role":"user","content":user_content}]
            )

        try:
            chat = call_llm(PRIMARY_MODEL)
        except Exception:
            chat = call_llm(FALLBACK_MODEL)

        raw = chat.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            st.error("❌ JSON の解析に失敗しました。モデル出力を確認してください。")
            st.write("受信内容:", raw)
            st.stop()

    # ─── 日本語ラベル変換 ─────────────────
    label = {
        "pq":"ページ品質 (PQ)","nm":"ニーズ充足度 (NM)",
        "effort":"労力","originality":"独自性","duplication_rate":"重複率 (%)",
        "skill":"スキル/技巧","accuracy":"正確性",
        "eeat_summary":"E-E-A-T 要約","improvement_advice":"改善アドバイス"
    }
    st.subheader("評価結果")
    st.json({label[k]:v for k,v in data.items()}, expanded=False)

    if data["pq"] in ["Lowest","Low"]:
        st.error("⚠️ ページ品質が低評価です。リライトを検討してください。")

    # ─── CSV ログ ───────────────────────
    pd.DataFrame([{
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "source": src[:100], **data
    }]).to_csv("sqeg_log.csv", mode="a", index=False, header=not os.path.exists("sqeg_log.csv"))
    st.success("結果を sqeg_log.csv に追記しました ✅")
# ─────────────────────────────────────────
