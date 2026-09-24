FROM python:3.12-slim
RUN useradd --create-home --uid 10001 app
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
COPY src/ ./src/
COPY fixtures/ ./fixtures/
USER app
EXPOSE 8002
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8002/health', timeout=2)"]
CMD ["python", "src/local_server.py"]
