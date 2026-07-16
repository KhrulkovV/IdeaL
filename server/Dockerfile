FROM python:3.12-slim

WORKDIR /app
COPY server/requirements.txt ./requirements.txt

# Install the CPU-only torch wheel first so the CUDA build (multi-GB) is never
# pulled in transitively by sentence-transformers. Then the rest of the deps.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt

COPY server/ ./server/
WORKDIR /app/server

# Cache the sentence-transformers model on the persisted /data volume so it is
# downloaded once and survives container rebuilds.
ENV HF_HOME=/data/hf-cache

EXPOSE 8000
# IDEAL_DB_PATH defaults to /data/ideal.sqlite (a mounted volume). IDEAL_TOKEN
# is required and comes from the environment / .env via docker-compose.
# IDEAL_RAG_ENABLED=false disables the semantic index (no model load).
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
