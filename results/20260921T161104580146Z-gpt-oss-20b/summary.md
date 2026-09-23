# Benchmark summary

| Model | Track | Task | Status | Capability | Code Health | Agent | Turns | Duration |
|---|---|---|---|---:|---:|---|---:|---:|
| gpt-oss:20b | zero_to_one | A00 | completed | 0 | 100.0 | max_turns | 40 | 10.5m |
| gpt-oss:20b | controlled_cold_change | C01 | completed | 100 | 90.0 | context_exceeded | 38 | 28.2m |
| gpt-oss:20b | controlled_cold_change | C02 | error | 0 | 90.0 | max_turns | 40 | 19.6m |
| gpt-oss:20b | controlled_cold_change | C03 | completed | 100 | 100.0 | max_turns | 40 | 10.0m |
| gpt-oss:20b | controlled_cold_change | C04 | completed | 25 | 100.0 | model_error | 8 | 2.6m |
| gpt-oss:20b | controlled_cold_change | C05 | error | 0 | 70.0 | max_turns | 40 | 15.5m |

Primary Capability Index: **27.00**
Controlled mean: **45.00**
