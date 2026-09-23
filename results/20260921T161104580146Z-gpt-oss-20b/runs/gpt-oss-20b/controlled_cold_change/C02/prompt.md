# C02: 注文作成の冪等性

`POST /orders` に `Idempotency-Key` を追加してください。

- ASCII 1〜128文字、必須。
- scopeは `tenant_id + endpoint + key`。
- 同key・同一論理requestは最初の201 responseを返し、在庫を再減算しない。
- 同keyで正規化後requestが異なる場合409 `IDEMPOTENCY_CONFLICT`。
- validation / 在庫不足 / rollbackは成功結果として記録しない。
- 同時同keyでも注文は1件、在庫減算は1回。
- tenantが異なれば同keyを使える。
- migrationと既存成功response schemaを維持する。

