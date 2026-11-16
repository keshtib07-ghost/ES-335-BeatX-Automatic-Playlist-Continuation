FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src \
    OPENBLAS_NUM_THREADS=1 \
    OMP_NUM_THREADS=1 \
    BEATX_DATA_DIR=/data \
    PORT=8080

COPY requirements.txt requirements-serve.txt ./
RUN python -m pip install --no-cache-dir -r requirements-serve.txt
COPY src ./src
COPY scripts/serve_million_demo.py scripts/serve_model_api.py ./scripts/
COPY deploy/gunicorn.conf.py ./deploy/gunicorn.conf.py

RUN useradd --uid 10001 --create-home beatx
USER beatx
EXPOSE 8080
CMD ["gunicorn", "--config", "deploy/gunicorn.conf.py", "scripts.serve_model_api:create_app()"]
