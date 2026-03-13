FROM python:3.13-slim AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.13-slim
WORKDIR /app
RUN useradd -r -s /bin/false appuser && mkdir -p /app/data && chown appuser:appuser /app/data
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY src/ src/
# data/ must be volume-mounted in production: docker run -v /host/data:/app/data
USER appuser
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health/live')" || exit 1
CMD ["python", "-m", "src.main"]
