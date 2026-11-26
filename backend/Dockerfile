FROM python:3.11-slim AS runtime

ARG TORCH_VERSION=2.10.0

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    EMBEDDING_DEVICE=cpu

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/* \
    && addgroup --system finassist \
    && adduser --system --ingroup finassist finassist

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install --index-url https://download.pytorch.org/whl/cpu "torch==${TORCH_VERSION}" \
    && pip install -r requirements.txt

COPY app ./app
COPY tessdata ./tessdata
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini
COPY docker-entrypoint.sh /usr/local/bin/finassist-entrypoint

RUN chmod 0755 /usr/local/bin/finassist-entrypoint \
    && mkdir -p /app/uploads /app/model-cache \
    && chown -R finassist:finassist /app

ENTRYPOINT ["finassist-entrypoint"]
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
