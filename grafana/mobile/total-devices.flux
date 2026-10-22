from(bucket: "jamf_inventory")
  |> range(start: -3h)
  |> filter(fn: (r) => r._measurement == "jamf_mobile_inventory_summary" and r._field == "total_devices" and r.platform == "mobile")
  |> last()
