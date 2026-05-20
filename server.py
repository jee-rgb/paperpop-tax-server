from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import anthropic
import os
import json
import requests
import base64

app = Flask(__name__, static_folder='.')
CORS(app)

ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY")
NOTION_TOKEN  = os.environ.get("NOTION_TOKEN")
DATA_FILE     = "queue.json"

client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

def load_queue():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_queue(queue):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)

@app.route("/")
def index():
    return send_from_directory(".", "index.html")

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

# ── AI Extract ────────────────────────────────────────
@app.route("/extract", methods=["POST"])
def extract():
    try:
        data      = request.json
        biz_b64   = data.get("biz_b64")
        biz_mt    = data.get("biz_mt", "image/jpeg")
        quote_b64 = data.get("quote_b64")
        quote_mt  = data.get("quote_mt", "image/jpeg")

        def make_block(b64, mt):
            if mt == "application/pdf":
                return {"type": "document", "source": {"type": "base64", "media_type": mt, "data": b64}}
            return {"type": "image", "source": {"type": "base64", "media_type": mt, "data": b64}}

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            messages=[{"role": "user", "content": [
                make_block(biz_b64, biz_mt),
                make_block(quote_b64, quote_mt),
                {"type": "text", "text": """첫 번째 문서는 공급받는자의 사업자등록증 또는 고유번호증, 두 번째는 견적서입니다.
JSON만 출력하세요:
{"buyer_reg":"","buyer_name":"","buyer_ceo":"","buyer_addr":"","buyer_biz":"","buyer_item":"","buyer_email":"","issue_date":"YYYYMMDD","total_supply":"숫자만","total_tax":"숫자만","total_vat_included":"VAT포함총액숫자만","items":[{"day":"DD","name":"","spec":"","qty":"","price":"","supply":"","tax":""}]}
모르는 값은 빈 문자열. items 최대 4개."""}
            ]}]
        )

        raw    = next((b.text for b in response.content if b.type == "text"), "")
        parsed = json.loads(raw.replace("```json", "").replace("```", "").strip())
        return jsonify({"ok": True, "data": parsed})

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# ── Queue: 저장 ───────────────────────────────────────
@app.route("/queue", methods=["POST"])
def add_entry():
    try:
        data  = request.json
        entry = data.get("entry")
        queue = load_queue()
        queue.append(entry)
        save_queue(queue)
        return jsonify({"ok": True, "count": len(queue)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# ── Queue: 조회 ───────────────────────────────────────
@app.route("/queue", methods=["GET"])
def get_queue():
    try:
        return jsonify({"ok": True, "data": load_queue()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# ── Queue: 삭제 ───────────────────────────────────────
@app.route("/queue/<int:entry_id>", methods=["DELETE"])
def delete_entry(entry_id):
    try:
        queue = [e for e in load_queue() if e.get("id") != entry_id]
        save_queue(queue)
        return jsonify({"ok": True, "count": len(queue)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# ── 발급 완료 → 노션 자동 기입 ───────────────────────
@app.route("/notion-complete", methods=["POST"])
def notion_complete():
    try:
        data           = request.json
        notion_url     = data.get("notion_url", "")
        issue_date     = data.get("issue_date", "")   # YYYYMMDD
        buyer_name     = data.get("buyer_name", "")
        total_vat      = data.get("total_vat", "")    # VAT 포함 총액

        if not NOTION_TOKEN:
            return jsonify({"ok": False, "error": "NOTION_TOKEN 미설정"}), 500

        # 페이지 ID 추출
        page_id = notion_url.split("?")[0].split("/")[-1].replace("-", "")
        if len(page_id) > 32:
            page_id = page_id[-32:]

        # 날짜 포맷 변환 YYYYMMDD → YYYY-MM-DD
        if len(issue_date) == 8:
            fmt_date = f"{issue_date[:4]}-{issue_date[4:6]}-{issue_date[6:8]}"
        else:
            fmt_date = issue_date

        headers = {
            "Authorization": f"Bearer {NOTION_TOKEN}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json"
        }

        properties = {}

        # 업체명
        if buyer_name:
            properties["업체명"] = {
                "rich_text": [{"type": "text", "text": {"content": buyer_name}}]
            }

        # 최종매출액(vat포함)
        if total_vat:
            properties["최종매출액(vat포함)"] = {
                "rich_text": [{"type": "text", "text": {"content": str(total_vat)}}]
            }

        # [★]계산서발행일/결제일
        if fmt_date:
            properties["[★]계산서발행일/결제일"] = {
                "date": {"start": fmt_date}
            }

        resp = requests.patch(
            f"https://api.notion.com/v1/pages/{page_id}",
            headers=headers,
            json={"properties": properties}
        )

        if resp.ok:
            return jsonify({"ok": True})
        else:
            return jsonify({"ok": False, "error": resp.text}), 500

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
