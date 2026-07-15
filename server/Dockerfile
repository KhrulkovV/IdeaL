FROM python:3.12-slim

WORKDIR /app
COPY server/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY server/ ./server/
WORKDIR /app/server

EXPOSE 8000
# IDEAL_DB_PATH defaults to /data/ideal.sqlite (a mounted volume). IDEAL_TOKEN
# is required and comes from the environment / .env via docker-compose.
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
