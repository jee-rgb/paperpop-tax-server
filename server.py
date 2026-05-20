from flask import Flask, request, jsonify
from flask_cors import CORS
import anthropic
import base64
import os

app = Flask(__name__)
CORS(app)

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})

@app.route("/extract", methods=["POST"])
def extract():
    try:
        data = request.json
        biz_b64 = data.get("biz_b64")
        biz_mt  = data.get("biz_mt", "image/jpeg")
        quote_b64 = data.get("quote_b64")
        quote_mt  = data.get("quote_mt", "image/jpeg")

        def make_block(b64, mt):
            if mt == "application/pdf":
                return {"type": "document", "source": {"type": "base64", "media_type": mt, "data": b64}}
            return {"type": "image", "source": {"type": "base64", "media_type": mt, "data": b64}}

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            messages=[{
                "role": "user",
                "content": [
                    make_block(biz_b64, biz_mt),
                    make_block(quote_b64, quote_mt),
                    {
                        "type": "text",
                        "text": """첫 번째 문서는 공급받는자(거래처)의 사업자등록증 또는 고유번호증이고,
두 번째 문서는 견적서입니다.
세금계산서 발행에 필요한 정보를 추출해주세요.

반드시 아래 JSON만 출력하세요 (다른 텍스트 없이):
{
  "buyer_reg": "사업자등록번호 또는 고유번호(하이픈 없이)",
  "buyer_name": "상호 또는 기관명",
  "buyer_ceo": "대표자 또는 기관장 성명",
  "buyer_addr": "사업장 또는 기관 주소",
  "buyer_biz": "업태",
  "buyer_item": "종목",
  "buyer_email": "",
  "issue_date": "견적서 작성일자 YYYYMMDD",
  "total_supply": "공급가액 합계 숫자만",
  "total_tax": "세액 합계 숫자만",
  "items": [
    { "day": "일자 DD 2자리", "name": "품목명", "spec": "규격", "qty": "수량", "price": "단가", "supply": "공급가액", "tax": "세액" }
  ]
}
알 수 없는 값은 빈 문자열. items 최대 4개."""
                    }
                ]
            }]
        )

        raw = next((b.text for b in response.content if b.type == "text"), "")
        clean = raw.replace("```json", "").replace("```", "").strip()

        import json
        parsed = json.loads(clean)
        return jsonify({"ok": True, "data": parsed})

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
