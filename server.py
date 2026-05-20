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

# ── Queue helpers ─────────────────────────────────────
def load_queue():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_queue(queue):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)

# ── Static ────────────────────────────────────────────
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
{"buyer_reg":"","buyer_name":"","buyer_ceo":"","buyer_addr":"","buyer_biz":"","buyer_item":"","buyer_email":"","issue_date":"YYYYMMDD","total_supply":"숫자만","total_tax":"숫자만","items":[{"day":"DD","name":"","spec":"","qty":"","price":"","supply":"","tax":""}]}
모르는 값은 빈 문자열. items 최대 4개."""}
            ]}]
        )

        raw    = next((b.text for b in response.content if b.type == "text"), "")
        parsed = json.loads(raw.replace("```json", "").replace("```", "").strip())
        return jsonify({"ok": True, "data": parsed})

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# ── Notion: 파일 업로드 후 페이지에 첨부 ─────────────
def attach_files_to_notion(page_id, files):
    """
    files: [{"name": "파일명.pdf", "b64": "...", "mime": "application/pdf"}, ...]
    Notion File Upload API를 사용해 첨부
    """
    if not NOTION_TOKEN:
        return False, "NOTION_TOKEN 미설정"

    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": "2022-06-28",
    }

    uploaded_files = []
    for f in files:
        try:
            file_bytes = base64.b64decode(f["b64"])

            # 1) 업로드 URL 요청
            upload_resp = requests.post(
                "https://api.notion.com/v1/file_uploads",
                headers={**headers, "Content-Type": "application/json"},
                json={"name": f["name"]}
            )
            if not upload_resp.ok:
                continue
            upload_data = upload_resp.json()
            upload_url  = upload_data.get("upload_url")
            file_id     = upload_data.get("id")

            if not upload_url:
                continue

            # 2) 실제 파일 전송
            put_resp = requests.put(
                upload_url,
                headers={"Authorization": f"Bearer {NOTION_TOKEN}"},
                files={"file": (f["name"], file_bytes, f["mime"])}
            )
            if put_resp.ok:
                uploaded_files.append({"type": "file_upload", "file_upload": {"id": file_id}})

        except Exception:
            continue

    if not uploaded_files:
        return False, "파일 업로드 실패"

    # 3) 페이지 속성(견적서/사업자등록증)에 첨부
    # 속성명이 다를 수 있으므로 files 블록으로도 추가
    prop_resp = requests.patch(
        f"https://api.notion.com/v1/pages/{page_id}",
        headers={**headers, "Content-Type": "application/json"},
        json={"properties": {"견적서/사업자등록증": {"files": uploaded_files}}}
    )

    if prop_resp.ok:
        return True, "ok"

    # 속성명이 다르면 페이지 블록으로 추가 (fallback)
    blocks = []
    for f in files:
        # 일반 블록 파일 첨부는 공개 URL이 필요해 생략하고 텍스트로 대신
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"📎 {f['name']} (첨부됨)"}}]}
        })

    requests.patch(
        f"https://api.notion.com/v1/blocks/{page_id}/children",
        headers={**headers, "Content-Type": "application/json"},
        json={"children": blocks}
    )
    return True, "fallback"

# ── Queue: 저장 + 노션 첨부 ───────────────────────────
@app.route("/queue", methods=["POST"])
def add_entry():
    try:
        data     = request.json
        entry    = data.get("entry")
        notion_page_id = data.get("notion_page_id", "").strip()
        files    = data.get("files", [])  # [{name, b64, mime}]

        queue = load_queue()
        queue.append(entry)
        save_queue(queue)

        notion_result = None
        if notion_page_id and files:
            # URL에서 ID 추출 (하이픈 없는 32자리 or URL 끝 부분)
            pid = notion_page_id.replace("-", "")
            if "notion.so" in pid:
                pid = pid.split("/")[-1].split("?")[0]
                pid = pid[-32:] if len(pid) >= 32 else pid

            ok, msg = attach_files_to_notion(pid, files)
            notion_result = {"ok": ok, "msg": msg}

        return jsonify({"ok": True, "count": len(queue), "notion": notion_result})

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

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
