FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8000 \
    FLEET_DB_PATH=/data/fleet.db

WORKDIR /app
COPY app/ /app/
RUN addgroup --system app && adduser --system --ingroup app app \
    && mkdir -p /data /logs \
    && chown -R app:app /app /data /logs

USER app
EXPOSE 8000
VOLUME ["/data", "/logs"]
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)" || exit 1

CMD ["python", "server.py"]
