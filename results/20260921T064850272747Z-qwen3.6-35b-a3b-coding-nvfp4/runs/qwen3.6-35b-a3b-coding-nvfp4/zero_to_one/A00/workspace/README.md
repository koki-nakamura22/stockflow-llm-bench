# StockFlow Mini

Stock and Order Management API.

## API

- `POST /products` - Create a product
- `GET /products/{id}` - Get a product
- `POST /orders` - Create an order
- `GET /orders/{id}` - Get an order
- `POST /orders/{id}/cancel` - Cancel an order
- `GET /health` - Health check

## Usage

```bash
make migrate
uvicorn stockflow.main:app --reload
```
