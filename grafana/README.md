# Grafana Flux examples

Configure Grafana's InfluxDB data source for Flux using the InfluxDB URL, organization, bucket, and a separate bucket-read token. Replace `jamf_inventory` in these files if you chose another bucket. Paste one file into a panel's query editor.

| Query | Suggested panel |
| --- | --- |
| `current-distribution.flux` | Table or bar chart: version and count |
| `current-major-versions.flux` | Bar chart: major version and summed count |
| `total-devices.flux` | Stat: most recent fleet total |
| `version-history.flux` | Time series: legend `${__field.labels.version}`, stack if desired |
| `snapshot-age.flux` | Stat: seconds since last snapshot; warn after 7200 seconds |

Current queries deliberately use a three-hour lookback independent of the dashboard time picker. They select the latest distribution timestamp, keeping all versions from that same snapshot. This avoids resurrecting old unnormalized series via an independent `last()` for each version. An empty lookback returns no usable current data; configure Grafana's no-data handling rather than treating that as a zero fleet. The freshness panel looks back 30 days; configure no-data as a failure there too.

For a pie chart, use the current-distribution query and configure the panel to show all values, using `version` as labels and `_value` as counts. Zero values are retained in the query; filter `_value > 0` only after snapshot selection if you want to hide retired versions.

History uses `last` within each display window because these are snapshot counts. Summing repeated hourly snapshots would overcount devices. Grafana's time range should include multiple hourly runs; gaps can indicate failed collection. Flux's [aggregateWindow documentation](https://docs.influxdata.com/influxdb/v2/reference/flux/stdlib/built-in/transformations/aggregates/aggregatewindow/) explains window selection and grouping.

Queries assume a single writer/fleet per bucket and successful complete writes. InfluxDB can partially accept a failing write, so investigate write errors rather than assuming every timestamp is complete. These examples have not been executed against your live Grafana/InfluxDB installation.

Mobile equivalents of all five queries are in `mobile/`, using separate mobile measurements and `platform=mobile`. See [mobile setup](../docs/mobile-devices.md).
