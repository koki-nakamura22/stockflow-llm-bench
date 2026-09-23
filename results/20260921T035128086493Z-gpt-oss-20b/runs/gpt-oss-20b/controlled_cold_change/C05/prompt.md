# C05: rolling migration

既存 `orders.total_amount` は税抜合計です。税率10%でAPIを `subtotal_amount`, `tax_amount`, `total_amount` へ拡張してください。

- `tax_amount = floor(subtotal_amount * 0.10)`
- `total_amount = subtotal_amount + tax_amount`
- expand/backfillとcontractを別revision・別commandにする。
- `make migrate-expand` は旧appのread/writeを壊さない。
- `make migrate-contract` は旧app停止後に明示実行する。
- compatibility中、旧物理column `total_amount` の意味は税抜のまま。
- 既存行と旧appの新規writeも新columnへ反映する。
- migration再実行で二重加算しない。
- API requestから金額指定は受けない。
- `MIGRATION.md` に判断を記録する。

