# Auth Server API. Multi-stage: dependencies are installed in a venv, and only the venv and the source reach the
# final image. Every dependency ships a manylinux wheel, so no compiler is needed.

FROM python:3.13-slim AS deps
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
COPY requirements.txt /tmp/requirements.txt
RUN python -m venv /venv && /venv/bin/pip install -r /tmp/requirements.txt

FROM python:3.13-slim
ENV PATH=/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    WORKERS=2 \
    FORWARDED_ALLOW_IPS=*
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin auth
WORKDIR /app
COPY --from=deps /venv /venv
COPY --chown=root:root . .
USER auth
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=2)"]

# Several workers are safe: the event hub uses LISTEN/NOTIFY and background jobs take advisory locks.
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port 8000 --workers \"$WORKERS\" --proxy-headers --forwarded-allow-ips \"$FORWARDED_ALLOW_IPS\" --no-server-header"]
