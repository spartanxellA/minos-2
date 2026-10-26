FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY pyproject.toml ./
COPY minos_nlp/ minos_nlp/
RUN pip install . && rm -rf minos_nlp pyproject.toml
RUN useradd --system --uid 10001 minos
USER minos
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2)"
CMD ["uvicorn", "minos_nlp.app:app", "--host", "0.0.0.0", "--port", "8000"]
