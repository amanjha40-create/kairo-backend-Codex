FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ARG APP_GIT_SHA=unknown
ARG APP_BUILD_ID=unknown

LABEL org.opencontainers.image.revision="${APP_GIT_SHA}"

ENV APP_GIT_SHA="${APP_GIT_SHA}"
ENV APP_BUILD_ID="${APP_BUILD_ID}"

WORKDIR /app

RUN useradd --create-home appuser

COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY alembic.ini alembic.ini
COPY alembic ./alembic
COPY pyproject.toml pyproject.toml

FROM base AS development

USER root
ENV PYTEST_ADDOPTS="-o cache_dir=/tmp/pytest-cache"
COPY requirements-dev.txt requirements-dev.txt
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY tests ./tests
COPY scripts ./scripts
RUN chmod 755 scripts/reset_test_data.py

USER appuser

FROM base AS runtime

USER root

# Perl is inherited from the slim base but not used by the Kairo runtime.
RUN apt-get purge -y --allow-remove-essential perl-base \
    && rm -rf /var/lib/apt/lists/*

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/live', timeout=5)"

CMD ["gunicorn", "-k", "uvicorn.workers.UvicornWorker", "app.main:app", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "60"]
