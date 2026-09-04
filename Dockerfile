FROM python:3.12-slim

LABEL maintainer="johnny"
LABEL description="Line Notification Bot — generic webhook → LINE Messaging API bridge"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY line_notification_bot/ ./line_notification_bot/
COPY app.py .

EXPOSE 5000

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--timeout", "30", "app:app"]