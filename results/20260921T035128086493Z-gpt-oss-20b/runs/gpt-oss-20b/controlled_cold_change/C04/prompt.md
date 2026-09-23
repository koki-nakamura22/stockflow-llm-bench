# C04: transactional outbox

注文作成とcancelへtransactional outboxを追加してください。

- event type: `order.created`, `order.canceled`
- `event_id`, `event_type`, `aggregate_id`, `occurred_at`, `payload`
- domain更新とoutbox INSERTは同一transaction。rollback時eventなし。
- `python -m stockflow.outbox_worker --once` を追加。
- `EVENT_PUBLISH_URL` へJSON POST。header `Idempotency-Key` はevent_id。
- 2xx時sent_at。失敗時attempts / last_errorを更新して未送信のまま。
- 複数workerが同じeventを同時claimしない。
- at-least-onceでよい。外部の実在serviceへ接続しない。

