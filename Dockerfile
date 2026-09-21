# バックエンド（FastAPI）を Render / Fly.io / Railway などに置くための Dockerfile。
# 環境変数: PUBLIC_MODE=1, CORS_ORIGINS, FRONTEND_URL, DISCOGS_TOKEN, MB_USER_AGENT（README「公開する」参照）
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 MALLOC_ARENA_MAX=2
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY frontend ./frontend
COPY fonts ./fonts
COPY cli.py .
# 点検の記録。起動時に metrics/r2.jsonl の最後の行から R2 の使用量を持ち越し、
# 全件の一覧（Class A 214 回）を imgcache/ だけ（134 回）に減らすために要る（2026-09-21）。
# **buildFilter には入れない**（点検の push でデプロイを走らせないため。焼かれる値が数日古くても、
# 歯止めの用途では多めにずれるだけで安全）
COPY metrics ./metrics
RUN mkdir -p outputs grids uploads shares \
    && useradd --system --no-create-home --uid 10001 app \
    && chown -R app:app /app
USER app

EXPOSE 8000
# ホスティング側が PORT を渡す（Render など）。無ければ 8000
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000} --no-access-log"]
