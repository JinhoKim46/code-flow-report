FROM python:3.12-slim
WORKDIR /app
COPY . .
CMD ["gunicorn", "-k", "uvicorn.workers.UvicornWorker", "app.main:app"]
