# service/Dockerfile
FROM python:3.12-slim AS base
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ROADMODEL_USER_CONTEXT=/app/user-context.md
COPY pyproject.toml ./
COPY app ./app
RUN pip install --upgrade pip && \
    pip install .
# Bootstrap a default user-context.md from the roadmodel bundled template.
# load_config() requires this file to exist; the CLI auto-creates it on first
# run, but a container has no first-run hook so we do it at build time.
RUN python -c "from pathlib import Path; from roadmodel import user_context; user_context.bootstrap(Path('/app/user-context.md'))" && \
    chmod 644 /app/user-context.md
# Non-root user for Phase-7-friendly posture
RUN useradd -r -u 1001 svc
USER svc
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
