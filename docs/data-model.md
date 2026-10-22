# Collector behavior and data model

## Collection

The script exchanges client credentials for a bearer token, requests the `OPERATING_SYSTEM` section of computer inventory, and pages from zero. An inventory HTTP 401 refreshes the token and retries once; the refreshed token is reused for subsequent pages.

When `totalCount` is returned, collection checks that it stays constant and all reported records were received. Without `totalCount`, a short or empty page ends collection. Invalid response envelopes, page failures, or zero total devices prevent writes. Pagination is not a server-side atomic snapshot: inventory movement that leaves the total unchanged may still affect a run. Counts describe Jamf's recorded inventory, not a live OS probe of each Mac.

## Version normalization

| Input | Stored version |
| --- | --- |
| `15.4.0` | `15.4` |
| `26.5.0.0` | `26.5` |
| `15.7.9` | `15.7.9` |
| `27.0` or `27.0.0` | `27.0` |
| Missing, empty, or case-insensitive `unknown` | `Unknown` |

Whitespace is trimmed. Trailing `.0` components are removed only while at least major.minor remains. Other strings are retained rather than guessed. `major_version` is the text before the first dot (or `Unknown`). Numeric version sorting is used for console output and saved state.

## InfluxDB schema

All points in a run share a UTC timestamp with second precision. Counts are integer fields; versions are tags, not floating-point numbers.

| Measurement | Tags | Integer fields |
| --- | --- | --- |
| `jamf_os_distribution` | `platform=macOS`, `version`, `major_version` | `count` |
| `jamf_inventory_summary` | `platform=macOS` | `total_devices`, `active_versions`, `known_versions`, `unknown_os` |

`active_versions` counts currently populated version categories, including `Unknown` when present. `known_versions` counts the union of current and previously seen normalized versions. Each previously seen version absent now receives `count=0`, so graphs can show it disappearing.

The state file contains only this structure:

```json
{"versions": ["27.0", "26.5.1", "15.4", "Unknown"]}
```

This is a format example, not seed data. Old state entries are normalized on load. State writes use a temporary sibling file and atomic rename after the InfluxDB write. Malformed state fails closed. The dry run never changes state.

Normalization does not rewrite historical InfluxDB tag values. Older `15.4.0` series remain in retained history. The latest-snapshot Grafana examples select a single latest timestamp to exclude stale historical aliases; history queries can still show older labels. No historical data is deleted or migrated by setup.
