FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py ./
COPY entrypoint.sh ./

RUN chmod +x /app/entrypoint.sh

VOLUME ["/app/sessions", "/app/state"]

CMD ["/app/entrypoint.sh"]

