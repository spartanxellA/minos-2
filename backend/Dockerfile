# Se construye desde la raíz del repositorio: usa nlp/ (diccionario compartido) y data/ (cuestionarios).
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY nlp/pyproject.toml nlp/
COPY nlp/minos_nlp/ nlp/minos_nlp/
COPY backend/pyproject.toml backend/
COPY backend/minos/ backend/minos/
RUN pip install ./nlp ./backend && rm -rf nlp backend
COPY data/ data/
RUN useradd --system --uid 10001 minos
USER minos
ENV MINOS_SURVEYS_PATH=/app/data/surveys.json
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health', timeout=2)"
# Las migraciones se aplican aparte (servicio "migrate" en docker-compose): python -m minos.migrate
CMD ["uvicorn", "minos.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers"]
