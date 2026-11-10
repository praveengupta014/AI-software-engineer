FROM python:3.13-slim
RUN pip install --no-cache-dir uv
WORKDIR /srv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY app ./app
COPY migrations ./migrations
RUN useradd --create-home countersign && mkdir /data && chown countersign /data
USER countersign
ENV COUNTERSIGN_DATA_DIR=/data
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD ["/srv/.venv/bin/python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/api/health')"]
CMD ["/srv/.venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
