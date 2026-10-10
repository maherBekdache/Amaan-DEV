# Amaan: backend API + built frontend in one image, served on :8000.
# URL.vet runs separately (see scripts/amaan.ps1 and docs/DECISIONS.md).

FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends libzbar0 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 amaan
WORKDIR /app
COPY backend/pyproject.toml ./
COPY backend/amaan ./amaan
RUN pip install --no-cache-dir .
COPY --from=web /web/dist /app/frontend
ENV AMAAN_FRONTEND_DIST=/app/frontend \
    AMAAN_URLVET_BASE_URL=http://urlvet-backend:8080 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
USER amaan
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/health',timeout=4)"
CMD ["uvicorn", "amaan.main:app", "--host", "0.0.0.0", "--port", "8000"]
