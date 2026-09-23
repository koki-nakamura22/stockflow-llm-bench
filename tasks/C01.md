# C01: cursor pagination

既存のStockFlow Miniへ `GET /orders` を追加してください。

- `limit`: 必須、1〜100
- 任意: `status`, `created_from`, `created_to`, `cursor`
- order: `created_at DESC, id DESC`
- response: `{"items": [...], "next_cursor": "string or null"}`
- cursorはopaqueで改ざん検知でき、`CURSOR_SECRET` を使う。
- filterを変えてcursorを再利用したら400 `INVALID_CURSOR`。
- 同じcreated_atでも重複・欠落を起こさない。
- tenant境界と既存contractを壊さない。

