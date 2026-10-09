FROM python:3.12.14-slim-trixie
COPY --from=ghcr.io/astral-sh/uv:0.12.7 /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends \
    openjdk-21-jre-headless procps ca-certificates libfontconfig1 fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /opt/homebrew/opt/openjdk@21/bin \
    && ln -s /usr/bin/java /opt/homebrew/opt/openjdk@21/bin/java
WORKDIR /app
COPY pyproject.toml uv.lock pnpm-lock.yaml sbom.json ./
COPY packages/proofops ./packages/proofops
COPY apps/api ./apps/api
COPY apps/worker ./apps/worker
COPY apps/agent ./apps/agent
COPY evaluation ./evaluation
COPY config ./config
COPY contracts ./contracts
COPY prompts ./prompts
COPY scripts/hosted_control.py ./scripts/hosted_control.py
COPY scripts/review_rulepack.py ./scripts/review_rulepack.py
COPY deploy/public/smoke.py ./deploy/public/smoke.py
RUN uv sync --frozen --no-dev --all-packages --no-cache \
    && useradd --uid 10001 --create-home proofops \
    && mkdir /data && chown proofops:proofops /data
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    APP_ENV=hosted MODEL_ADAPTER=disabled \
    HOSTED_DATA_DIR=/data HOSTED_EVENT_ID=dec19-event \
    HOSTED_ACCEPT_UPLOADS=false R108_ACCEPT_NEW_RUNS=false \
    ANALYSIS_BACKEND=static LIVE_DISABLED=true \
    HOSTED_RUN_USD=1.0 HOSTED_DAY_USD=7 HOSTED_EVENT_USD=7
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=5s --timeout=3s --start-period=10s --retries=6 \
    CMD python -c "import json,urllib.request; assert json.load(urllib.request.urlopen('http://127.0.0.1:8000/v1/health/live',timeout=2))['status']=='ok'"
CMD ["python", "-m", "uvicorn", "proofops_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--no-proxy-headers"]
