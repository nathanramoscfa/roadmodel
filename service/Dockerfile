# service/Dockerfile
FROM python:3.12-slim AS base
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
COPY pyproject.toml ./
COPY app ./app
RUN pip install --upgrade pip && \
    pip install .
# Non-root user for Phase-7-friendly posture
RUN useradd -r -u 1001 svc
USER svc
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
