# Benchmark summary

| Model | Track | Task | Status | Capability | Code Health | Agent | Turns | Duration |
|---|---|---|---|---:|---:|---|---:|---:|
| gpt-oss:20b | zero_to_one | A00 | error | 0 | 100.0 | max_turns | 40 | 18.2m |
| gpt-oss:20b | controlled_cold_change | C01 | completed | 100 | 100.0 | context_exceeded | 22 | 23.4m |
| gpt-oss:20b | controlled_cold_change | C02 | completed | 0 | 90.0 | context_exceeded | 27 | 10.3m |
| gpt-oss:20b | controlled_cold_change | C03 | completed | 100 | 100.0 | context_exceeded | 18 | 9.3m |
| gpt-oss:20b | controlled_cold_change | C04 | error | 0 | 70.0 | model_error | 29 | 17.1m |
| gpt-oss:20b | controlled_cold_change | C05 | error | 0 | 100.0 | model_error | 13 | 10.9m |

Primary Capability Index: **24.00**
Controlled mean: **40.00**
