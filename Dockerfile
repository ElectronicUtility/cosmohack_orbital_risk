FROM python:3.12-slim@sha256:2f17fc044b579bab302c2e8054d3a686e2cb9a83de48e70534b94cd8ebbe06a9
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 COSMO_DB=/var/lib/orbital/analyses.db
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --system --uid 10001 orbital \
    && mkdir -p /var/lib/orbital \
    && chown orbital /var/lib/orbital
COPY app ./app
COPY data ./data
COPY research_results ./research_results
COPY scripts ./scripts
USER orbital
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"
CMD ["python", "-m", "uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000"]
