# syntax=docker/dockerfile:1.7
# Langdesk production image: gunicorn web, Celery worker and beat share this image.

ARG PYTHON_VERSION=3.13

FROM python:${PYTHON_VERSION}-slim AS deps
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
COPY requirements.txt /tmp/requirements.txt
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip \
 && /opt/venv/bin/pip install -r /tmp/requirements.txt

FROM python:${PYTHON_VERSION}-slim AS runtime

ARG VERSION=dev
ARG BUILD_NUMBER=dev
ARG GIT_SHA=""
ARG BUILD_DATE=""

LABEL org.opencontainers.image.title="Langdesk" \
      org.opencontainers.image.description="Self-hosted interpreter scheduling for clinics, schools and legal aid offices" \
      org.opencontainers.image.source="https://github.com/lobojoel2003/Langdesk" \
      org.opencontainers.image.documentation="https://github.com/lobojoel2003/Langdesk#readme" \
      org.opencontainers.image.licenses="AGPL-3.0-only" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      io.langdesk.build-number="${BUILD_NUMBER}"

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DJANGO_SETTINGS_MODULE=langdesk.settings \
    LANGDESK_BUILD_NUMBER="${BUILD_NUMBER}" \
    LANGDESK_GIT_SHA="${GIT_SHA}" \
    LANGDESK_BUILD_DATE="${BUILD_DATE}"

RUN groupadd --system --gid 10001 langdesk \
 && useradd --system --uid 10001 --gid langdesk --home-dir /app --shell /usr/sbin/nologin langdesk \
 && mkdir -p /app/data \
 && chown langdesk:langdesk /app/data

WORKDIR /app
COPY --from=deps /opt/venv /opt/venv
COPY manage.py ./
COPY langdesk ./langdesk
COPY docker/entrypoint.sh /usr/local/bin/langdesk-entrypoint

RUN chmod 0755 /usr/local/bin/langdesk-entrypoint \
 && DJANGO_SECRET_KEY=build-only python manage.py collectstatic --noinput --verbosity 0 \
 && python -m compileall -q langdesk

USER langdesk
VOLUME ["/app/data"]
EXPOSE 8000

ENTRYPOINT ["langdesk-entrypoint"]
CMD ["web"]
