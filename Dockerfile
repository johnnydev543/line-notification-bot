FROM python:3.12-slim

LABEL maintainer="johnny"
LABEL description="Grafana Alert → LINE Messaging API webhook bridge"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

EXPOSE 5000

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--timeout", "30", "app:app"]