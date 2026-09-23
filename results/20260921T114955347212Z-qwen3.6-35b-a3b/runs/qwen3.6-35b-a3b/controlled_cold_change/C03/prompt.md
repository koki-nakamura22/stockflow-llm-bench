# C03: 注文状態遷移

状態 `PENDING`, `CONFIRMED`, `SHIPPED`, `CANCELED` を実装してください。

- `POST /orders/{id}/confirm`: PENDING -> CONFIRMED
- `POST /orders/{id}/ship`: CONFIRMED -> SHIPPED
- cancel: PENDING / CONFIRMED -> CANCELED
- その他は409 `INVALID_ORDER_STATE`
- cancelの在庫復元は一度だけ。confirm / shipでは在庫不変。
- 競合操作でも許可された遷移だけが一度成立する。
- tenant境界と既存contractを壊さない。

