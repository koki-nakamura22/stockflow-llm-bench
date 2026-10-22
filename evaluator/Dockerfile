FROM python:3.12-slim
WORKDIR /evaluator
COPY requirements.txt /evaluator/
RUN pip install --no-cache-dir -U "pip>=26.2.2" && pip install --no-cache-dir -r requirements.txt
ENTRYPOINT ["pytest"]

