# Independent mobile-device collector

`jamf_mobile_influx.py` runs independently of `jamf_influx.py`. It uses the same Python dependencies and environment variable names, authentication, normalization, pagination checks, dry-run option, and zero-count state behavior. It does not import or run the Mac collector. The separate installer can be used on its own.

## Scope and API

The collector requests `GET /pro/v2/mobile-devices/detail?section=GENERAL`, reads `general.osVersion`, and counts all returned mobile-device inventory records. Missing/blank versions become `Unknown`; `18.4.0` becomes `18.4`, while `27.0` remains `27.0`. It does not filter out unmanaged records or distinguish iOS, iPadOS, and tvOS families: these are aggregate mobile OS version counts. It requests stable ordering by `mobileDeviceId` while paging.

Use a platform environment-scoped integration with mobile inventory read access. Jamf documents the required permission as `devices:read` on the [mobile inventory endpoint](https://developer.jamf.com/platform-api/reference/get_v2-mobile-devices-detail-1). Existing Mac credentials can be reused if they also have that permission. The script sends `X-Environment-Id`; it does not use the Classic API.

The GENERAL response can include device identifiers; only aggregate version counts are retained or printed. As with the Mac collector, a zero-device fleet or failed/incomplete collection does not write a snapshot. Inventory reflects Jamf's last collected information.

## Install

On the Debian/Ubuntu target, from the repository directory:

```sh
sudo bash setup-mobile.sh
sudoedit /etc/jamf-mobile-influx.env
sudo chmod 600 /etc/jamf-mobile-influx.env
```

Fill in the variables described in [deployment.md](deployment.md#required-configuration). The installer copies `jamf-mobile-influx.env.example` only if the destination does not already exist. It does not enable either timer. Use the separate mobile env file even if both integrations share credentials. Leave `STATE_FILE=/var/lib/jamf-mobile-influx/known_versions.json`; never point it at the Mac state file.

| Resource | Mobile collector |
| --- | --- |
| Script | `/opt/jamf-mobile-influx/jamf_mobile_influx.py` |
| Python environment | `/opt/jamf-mobile-influx/venv/` |
| Secret configuration | `/etc/jamf-mobile-influx.env` (root-owned, `0600`) |
| State | `/var/lib/jamf-mobile-influx/known_versions.json` |
| Service | `jamf-mobile-influx.service` |
| Timer | `jamf-mobile-influx.timer` |
| Service user | `jamfinflux` (shared unprivileged account) |

Code, virtual environment, configuration, state, and scheduling are separate. The mobile state directory is writable by the service; the service sandbox protects the rest of the filesystem. Stop the mobile timer and let an active run finish before upgrading its files.

## Dry run, first write, and hourly schedule

```sh
sudo systemd-run --unit=jamf-mobile-influx-dry-run --wait --pipe --collect \
  --property=User=jamfinflux --property=Group=jamfinflux \
  --property=EnvironmentFile=/etc/jamf-mobile-influx.env \
  /opt/jamf-mobile-influx/venv/bin/python /opt/jamf-mobile-influx/jamf_mobile_influx.py --dry-run
```

Compare counts with Jamf. Dry run reads Jamf without reading/writing state or writing InfluxDB. Then:

```sh
sudo systemctl start jamf-mobile-influx.service
sudo journalctl -u jamf-mobile-influx.service -n 50 --no-pager
sudo systemctl enable --now jamf-mobile-influx.timer
systemctl list-timers jamf-mobile-influx.timer
```

For manual collection, start the service again. To pause, run `sudo systemctl stop jamf-mobile-influx.timer`. This does not pause the Mac collector. The hourly schedule includes up to 60 seconds of jitter and a catch-up run after downtime. Use the service rather than concurrent standalone writing processes.

For local development, install `requirements.txt` into a virtual environment, export the mobile configuration into the process environment, and run `python jamf_mobile_influx.py --dry-run`. The script does not load env files automatically. Run all offline tests with `python -m unittest discover -s tests -v`.

## Separate InfluxDB schema and Grafana

| Measurement | Tags | Integer fields |
| --- | --- | --- |
| `jamf_mobile_os_distribution` | `platform=mobile`, `version`, `major_version` | `count` |
| `jamf_mobile_inventory_summary` | `platform=mobile` | `total_devices`, `active_versions`, `known_versions`, `unknown_os` |

The default bucket remains `jamf_inventory`. Mac and mobile collectors for one environment may share that bucket because measurement names differ. Use separate buckets for separate Jamf environments. Mobile state uses the same `{"versions": [...]}` structure as Mac state, in its own directory; vanished mobile versions receive zero counts on subsequent successful runs.

Copy the Flux examples in [grafana/mobile](../grafana/mobile/) into separate mobile dashboard panels. They include current versions, current major versions, total devices, history, and snapshot age. The [Grafana guidance](../grafana/README.md) applies equally to those examples. Existing Mac queries are unchanged.

The same failure and recovery behavior described in [deployment.md](deployment.md#operations-and-troubleshooting) applies. For a mobile-only HTTP 403, check mobile inventory permissions in particular. Live API, InfluxDB, and Linux service validation must be performed on your target; offline tests use synthetic API responses.
