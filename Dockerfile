FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY site ./site
COPY run.py .

RUN mkdir -p /app/data/uploads

EXPOSE 8000
CMD ["python", "run.py"]
