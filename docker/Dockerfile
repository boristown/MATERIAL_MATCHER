# syntax=docker/dockerfile:1
# Source-visible Docker deployment. The final offline base-image tar is prepared later by OpenCode.
ARG NODE_BASE_IMAGE=node:20-bookworm-slim
ARG PYTHON_BASE_IMAGE=python:3.11-slim

FROM ${NODE_BASE_IMAGE} AS web-builder
WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM ${PYTHON_BASE_IMAGE} AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    MATERIAL_MATCHER_WEB_DIST_DIR=/app/web-dist \
    MATERIAL_MATCHER_DEPLOYMENT_MODE=docker-source
WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN python -m pip install --no-cache-dir .
COPY --from=web-builder /build/web/dist/ ./web-dist/

EXPOSE 18080
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import json,urllib.request; assert json.load(urllib.request.urlopen('http://127.0.0.1:18080/api/health/ready', timeout=2))['status']=='ready'"

CMD ["python", "-m", "material_matcher.cli", "serve", "--host", "0.0.0.0", "--port", "18080"]
