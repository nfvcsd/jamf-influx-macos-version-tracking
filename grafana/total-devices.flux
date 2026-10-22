from(bucket: "jamf_inventory")
  |> range(start: -3h)
  |> filter(fn: (r) => r._measurement == "jamf_inventory_summary" and r._field == "total_devices" and r.platform == "macOS")
  |> last()
