from fastapi import FastAPI

app = FastAPI(title="StockFlow Mini")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "not-implemented"}

