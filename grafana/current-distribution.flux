data = from(bucket: "jamf_inventory")
  |> range(start: -3h)
  |> filter(fn: (r) => r._measurement == "jamf_os_distribution" and r._field == "count" and r.platform == "macOS")

latest = data
  |> group()
  |> max(column: "_time")
  |> findRecord(fn: (key) => true, idx: 0)

data
  |> filter(fn: (r) => r._time == latest._time)
  |> group()
  |> keep(columns: ["version", "_value"])
  |> sort(columns: ["_value"], desc: true)
