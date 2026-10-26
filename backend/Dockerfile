# Se construye desde la raíz del repositorio: usa nlp/ (diccionario compartido) y data/ (cuestionarios).
FROM python:3.12-slim
WORKDIR /app
COPY nlp/pyproject.toml nlp/
COPY nlp/minos_nlp/ nlp/minos_nlp/
COPY backend/pyproject.toml backend/
COPY backend/minos/ backend/minos/
RUN pip install --no-cache-dir ./nlp ./backend
COPY data/ data/
ENV MINOS_SURVEYS_PATH=/app/data/surveys.json
EXPOSE 8080
CMD ["uvicorn", "minos.main:app", "--host", "0.0.0.0", "--port", "8080"]
