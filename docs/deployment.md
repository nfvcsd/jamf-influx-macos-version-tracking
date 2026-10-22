# Deployment and operations

## Prerequisites

Use a Debian/Ubuntu Linux server with systemd, Python 3.10+, outbound HTTPS to Jamf, and network access to InfluxDB. Installation uses root; collection runs as the dedicated `jamfinflux` account. The supplied installer is for the Linux target, not macOS.

In Jamf Account, create a **platform environment-scoped integration** for the environment containing your Jamf Pro tenant. Grant the capability that permits reading computer inventory, including operating-system inventory. Copy its client ID, secret, environment ID, and regional API base URL. Permission names can depend on the available tenant capabilities; verify access with the dry run. This collector uses `POST /auth/token` and `GET /pro/v4/computers-inventory` with `X-Environment-Id`. A tenant-scoped integration using `X-Tenant-Id` requires adapting the collector.

Create the InfluxDB 2.x organization and bucket (default `jamf_inventory`) with retention suited to your history requirements. Give the collector a token with write access to that bucket. Use a separate read-only token for Grafana. Creating the bucket, Grafana data source, and Jamf integration is not performed by the installer.

Jamf's [integration guide](https://developer.jamf.com/platform-api/reference/getting-started-with-platform-api) describes scopes, regional hosts, credential issuance, and rotation. Use the same regional host for token and inventory requests.

## Required configuration

Copy the template with the installer, then edit `/etc/jamf-influx.env` with `sudoedit`. Keep it owned by root with mode `0600`; systemd reads it before switching users. Use `KEY=value` lines without `export`. Quote values containing spaces according to systemd EnvironmentFile syntax; do not put shell commands or variable substitutions in the file.

| Variable | Value / purpose |
| --- | --- |
| `JAMF_BASE_URL` | Regional Platform URL; defaults to `https://us.api.jamfcloud.com`, not the Jamf Pro web console URL |
| `JAMF_CLIENT_ID` | Integration client ID; required |
| `JAMF_CLIENT_SECRET` | Integration secret; required |
| `JAMF_ENVIRONMENT_ID` | Environment ID associated with the integration; required |
| `JAMF_PAGE_SIZE` | Positive page size; defaults to `500` |
| `INFLUX_URL` | InfluxDB base URL, including port when needed; required for writes |
| `INFLUX_ORG` | Organization name or ID; required for writes |
| `INFLUX_BUCKET` | Destination bucket; defaults to `jamf_inventory` |
| `INFLUX_TOKEN` | Bucket write token; required for writes |
| `STATE_FILE` | Defaults to `/var/lib/jamf-influx/known_versions.json` |

Replace every `REPLACE_ME` and the example InfluxDB hostname. TLS verification remains enabled. For a private certificate authority, install a trusted CA on the target instead of disabling verification. Keep state inside `/var/lib/jamf-influx`; the service sandbox only permits persistent writes there.

## Install and validate

From the repository directory on the target Linux server:

```sh
sudo bash setup.sh
sudoedit /etc/jamf-influx.env
sudo chmod 600 /etc/jamf-influx.env
```

The installer preserves an existing env file and state. It installs code and dependencies, copies units, and reloads systemd. On an upgrade, stop the timer and wait for any active service to finish before replacing code or dependencies.

Run a dry run with systemd loading the protected environment and switching to the service account:

```sh
sudo systemd-run --unit=jamf-influx-dry-run --wait --pipe --collect   --property=User=jamfinflux --property=Group=jamfinflux   --property=EnvironmentFile=/etc/jamf-influx.env   /opt/jamf-influx/venv/bin/python /opt/jamf-influx/jamf_influx.py --dry-run
```

Compare the total and distribution to Jamf. A dry run does not require valid InfluxDB settings and does not read or write the state file. Then perform the first write and inspect the result:

```sh
sudo systemctl start jamf-influx.service
sudo journalctl -u jamf-influx.service -n 50 --no-pager
sudo cat /var/lib/jamf-influx/known_versions.json
sudo systemctl enable --now jamf-influx.timer
systemctl list-timers jamf-influx.timer
```

A successful oneshot service returns to inactive; that is normal. The timer runs hourly with up to 60 seconds of randomized delay. `Persistent=true` triggers a catch-up run after downtime, not a replay of every missed hour. Collection has a 30-minute service timeout. A failure leaves the timer enabled for the next scheduled attempt.

## Installed paths

| Path | Ownership / contents |
| --- | --- |
| `/opt/jamf-influx/jamf_influx.py` | root-owned collector, readable by service |
| `/opt/jamf-influx/requirements.txt` | dependency ranges |
| `/opt/jamf-influx/venv/` | root-managed Python environment |
| `/etc/jamf-influx.env` | root:root, `0600`; credentials |
| `/var/lib/jamf-influx/` | jamfinflux:jamfinflux, `0700`; state |
| `/etc/systemd/system/jamf-influx.service` | service definition |
| `/etc/systemd/system/jamf-influx.timer` | schedule |

The application creates `known_versions.json` on the first successful write. Do not prepopulate it with example versions. Back it up with the configuration, protecting the configuration backup as a secret.

## Operations and troubleshooting

```sh
sudo systemctl start jamf-influx.service     # manual collection through the same unit
sudo systemctl status jamf-influx.service --no-pager
sudo journalctl -u jamf-influx.service --since today --no-pager
sudo systemctl stop jamf-influx.timer        # pause scheduling
sudo systemctl disable --now jamf-influx.timer
```

Use the unit for manual writes: systemd prevents concurrent starts of the same service. Do not run standalone writing processes concurrently; the state file is atomically replaced but has no inter-process lock. Stopping the timer does not stop an already running collection.

| Symptom | Checks |
| --- | --- |
| Missing variable | Check variable names in `/etc/jamf-influx.env`; the Python script does not load files itself |
| Jamf HTTP 401 | Check region, client credentials and integration validity; inventory refreshes an expired token once |
| Jamf HTTP 403 | Check integration scope, environment membership, and inventory-read capability |
| Jamf HTTP 429 / 5xx | Check provider status/rate limits; run fails and the next timer invocation retries |
| Empty or incomplete inventory | No snapshot is written; check Jamf visibility, permissions, or inventory changes during paging |
| InfluxDB failure | Check URL/TLS/network, organization, bucket and write-token scope |
| State cannot be read | Restore or repair JSON and permissions; collector refuses a write to avoid losing zero-count tracking |
| Old nonzero versions in Grafana | Verify state was preserved and use the latest-snapshot query rather than independent last values over old series |
| No recent Grafana data | Check the timer, journal and freshness query; widening a range can conceal a stalled collector |

Errors omit API response bodies and unexpected exception messages to avoid exposing credentials or device data. Diagnose with HTTP status, exception class and configuration checks; do not paste tokens or full authenticated request dumps into tickets.

State is saved only after InfluxDB acknowledges the synchronous write. A failed or interrupted HTTP write may still have reached the server; the next run writes a fresh snapshot. There is no transaction spanning InfluxDB and the local state file. If a write succeeds but state saving fails, repair the directory and rerun promptly. Missing state starts a new known-version set; restoring the previous state preserves zero entries for disappeared versions.

To update credentials, edit the protected env file; the next service start reads the new values. To change the schedule, use `sudo systemctl edit jamf-influx.timer`, clear `OnCalendar=` before setting a replacement, then reload systemd and restart the timer. Retain the previous source revision for rollback; dependency ranges are not an exact lockfile, so validate upgrades on your target.
