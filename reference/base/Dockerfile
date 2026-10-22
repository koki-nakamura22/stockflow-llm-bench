FROM python:3.12-slim
# make: the C05 task and evaluator run `make migrate-expand` inside this image.
RUN apt-get update && apt-get install -y --no-install-recommends make && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir -U "pip>=26.2.2" && pip install --no-cache-dir .
CMD ["uvicorn", "stockflow.main:app", "--host", "0.0.0.0", "--port", "8000"]
