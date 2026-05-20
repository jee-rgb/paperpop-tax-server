# PaperPop 세금계산서 자동화 서버

## 배포 방법 (Render 무료)
1. 이 폴더를 GitHub에 업로드
2. render.com → New Web Service → GitHub 연결
3. Environment Variable: ANTHROPIC_API_KEY 입력
4. Deploy

## 로컬 테스트
```
pip install -r requirements.txt
ANTHROPIC_API_KEY=your_key python server.py
```
