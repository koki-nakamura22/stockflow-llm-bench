FROM python:3.12-slim
WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir .
CMD ["uvicorn", "stockflow.main:app", "--host", "0.0.0.0", "--port", "8000"]
