FROM python:3.11-slim

WORKDIR /app

# RUN apt-get update && apt-get install -y \
#     gcc \
#     postgresql-client \
#     && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
COPY requirements2.txt .

RUN pip install -U pip
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir -r requirements2.txt


COPY app/ ./app/
COPY alembic/ ./alembic/
COPY worker/ ./worker/

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
