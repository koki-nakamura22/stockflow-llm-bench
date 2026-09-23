# Rolling Migration: subtotal_amount, tax_amount, total_amount

## 判断記録

### 設計方針

既存 `orders.total_amount` は税抜合計（subtotal）として運用されていた。
これを `subtotal_amount`（税抜）、`tax_amount`（税額）、`total_amount`（税込）に拡張する。

- `tax_amount = floor(subtotal_amount * 0.10)`
- `total_amount = subtotal_amount + tax_amount`

### 互換性

- 拡張中、旧物理 column `total_amount` は税抜のまま維持（旧appのread/writeを壊さない）
- 新appは旧columnにも書き込む（旧appとの互換性維持）
- API response の `total_amount` は `subtotal_amount + tax_amount` を返す

### 展開手順

1. **migrate-expand**: 新columnを追加し、既存行をバックフィル
   - 旧appは停止せず、旧columnへのread/writeを継続
   - 新appは両columnに書き込む
2. **旧appの移行**: 新appに置き換え
3. **migrate-contract**: 旧app停止後に明示実行
   - 新columnに依存する形で最終化

### 再実行安全性

- backfillは既存行のみを対象とし、二重加算しない
- 新appのwriteは毎回計算し直すため、再実行でも二重加算しない

### API 制限

- 金額指定はAPI requestから受けない（すべてサーバー計算）
