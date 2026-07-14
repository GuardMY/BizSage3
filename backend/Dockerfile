FROM python:3.12.12-slim-bookworm

ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    PYTHONPATH=/app

WORKDIR /app

RUN groupadd --system --gid 1001 bizsage \
    && useradd --system --uid 1001 --gid bizsage bizsage \
    && mkdir -p /data \
    && chown bizsage:bizsage /data

COPY pyproject.toml ./

RUN --mount=type=cache,target=/root/.cache/pip \
    python -c "import subprocess, sys, tomllib; config = tomllib.load(open('pyproject.toml', 'rb')); subprocess.check_call([sys.executable, '-m', 'pip', 'install', *config['project']['dependencies']])"

COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic

USER bizsage

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=3)"]

CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
