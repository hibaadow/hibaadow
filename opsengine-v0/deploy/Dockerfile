# OpsEngine: stdlib-only Python, so the image is just Python plus the code.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY . /app
# run as an unprivileged user; data lives on mounted volumes, never in the image
RUN useradd --system --uid 10001 --home /app opsengine \
 && mkdir -p /app/state /app/data/customers /backups /checkpoints \
 && chown -R opsengine /app/state /app/data/customers /backups /checkpoints
USER opsengine
EXPOSE 8000
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"
CMD ["python", "-m", "opsengine", "web", "--host", "0.0.0.0", "--port", "8000"]
