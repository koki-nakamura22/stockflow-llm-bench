# A00: StockFlow Miniを0→1実装

作業directoryは環境設定だけを持つ空のapplication skeletonです。ファイルを読み、注文・在庫管理APIを完成させてください。質問できる人はいません。利用できるcheckを実行し、最後まで進めてください。

技術: Python 3.12 / FastAPI / SQLAlchemy 2 / Alembic / PostgreSQL 16。

共通規約:

- JSON API。全APIでUUIDの `X-Tenant-Id` headerを必須にする。
- IDはUUID、日時はUTC、金額は整数の円。
- errorは `{"error":{"code":"...","message":"...","details":{}}}`。
- 他tenantのresourceは404に見せる。
- DB schemaはAlembic migrationで作成する。
- evaluatorやbenchmark-owned testを変更しない。

API:

1. `POST /products`: `sku`, `name`, `unit_price`, `stock`。201。skuはtenant内unique。
2. `GET /products/{id}`: 自tenantの商品だけ返す。
3. `POST /orders`: `items: [{product_id, quantity}]`。201。
   - 同じproductは数量を合算。
   - 価格・名称・skuを明細へsnapshot。
   - 注文作成と全在庫減算はatomic。
   - missing product / 他tenant / 在庫不足では全rollback。
   - 同時注文でもstockを負数にしない。
4. `GET /orders/{id}`: 明細込み。
5. `POST /orders/{id}/cancel`: PENDINGだけ。cancelと在庫復元はatomic。再cancelは409。
6. `GET /health`: DB接続時だけ200 `{"status":"ok"}`。

status/error:

- invalid tenant: 400 `INVALID_TENANT`
- invalid body: 422 `VALIDATION_ERROR`
- not found: 404 `NOT_FOUND`
- duplicate SKU: 409 `SKU_ALREADY_EXISTS`
- insufficient stock: 409 `INSUFFICIENT_STOCK`
- invalid state: 409 `INVALID_ORDER_STATE`

response key:

- Product: `id, tenant_id, sku, name, unit_price, stock, created_at, updated_at`
- Order: `id, tenant_id, status, total_amount, created_at, updated_at, items`
- OrderItem: `id, order_id, product_id, sku, product_name, unit_price, quantity, line_amount`

