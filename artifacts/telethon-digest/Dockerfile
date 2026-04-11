FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py ./

# Sessions stored in volume
VOLUME ["/app/sessions", "/app/state"]

CMD ["python", "digest_worker.py"]
