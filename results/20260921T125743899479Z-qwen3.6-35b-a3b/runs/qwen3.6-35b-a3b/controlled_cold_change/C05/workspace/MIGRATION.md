# Rolling Migration: tax_amount expansion

## 判断記録

### 1. 移行戦略: expand/contract を別 revision・別 command に分ける

`make migrate-expand` と `make migrate-contract` を別々の alembic revision として実装。
旧 app が稼働中に expand を実行し、その後 contract を実行する。

### 2. 旧物理 column `total_amount` の互換性

expand 中は旧物理 column `total_amount` を維持し、意味は「税抜合計」のまま。
新 column `subtotal_amount` に同じ値をコピーし、`tax_amount` = floor(subtotal_amount * 0.10) を計算。
旧 app の read/write は一切壊さない。

### 3. 既存行と旧 app の新規 write の新 column への反映

- **既存行**: migrate-expand の backfill で `subtotal_amount` と `tax_amount` に反映
- **旧 app の新規 write**: app code で `total_amount` と `subtotal_amount`/`tax_amount` の両方に書き込み
- **migration 再実行**: backfill 時に `WHERE subtotal_amount IS NULL` で二重加算を防ぐ

### 4. API request から金額指定を受けない

`OrderCreate` schema に金額フィールドは含めず、サーバーサイドで計算のみ。

### 5. 新 column 定義

- `subtotal_amount`: 税抜合計 (既存 `total_amount` と同じ値)
- `tax_amount`: floor(subtotal_amount * 0.10)
- `total_amount`: subtotal_amount + tax_amount (税抜合計)

### 6. contract 実行のタイミング

旧 app の停止後に明示的に `make migrate-contract` を実行する。
contract 後は旧 `total_amount` column を削除し、新 `total_amount` (税込) のみを使用。

### 7. migration 再実行の安全性

- expand: `WHERE subtotal_amount IS NULL` で既存行の二重更新を防ぐ
- contract: 旧 column が存在しない場合は error となるが、既存行は新 column でカバーされている
