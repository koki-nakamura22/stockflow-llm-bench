FROM python:3.12-slim
WORKDIR /evaluator
COPY requirements.txt /evaluator/
RUN pip install --no-cache-dir -r requirements.txt
ENTRYPOINT ["pytest"]

