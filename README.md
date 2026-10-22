# Jamf OS Version Tracking for InfluxDB

Track macOS and mobile-device OS versions from the Jamf Platform API in InfluxDB, and visualize fleet trends in Grafana.

Two independent Python collectors aggregate inventory by OS version. Each has its own configuration, state file, installer, and hourly systemd timer. Run either collector on its own or both together.

## Features

- Paginated inventory collection with OAuth client credentials and token refresh.
- Version normalization: `15.4.0` becomes `15.4`, while `27.0` stays `27.0`.
- Aggregate snapshots with device counts, active versions, and unknown versions.
- Persistent version tracking that writes zero counts when a version disappears.
- A `--dry-run` option to check inventory without writing InfluxDB or state.
- Separate Mac and mobile measurements, plus ready-to-use Grafana Flux queries.

Only aggregate counts and version state are stored. Device names, serial numbers, and individual inventory records are not retained.

## Requirements

- Python 3.10 or newer.
- A Jamf Platform integration scoped to the target environment, with read access to the relevant computer or mobile-device inventory.
- InfluxDB 2.x with an organization, bucket, and bucket-write token.
- Debian or Ubuntu with systemd for the supplied installers and scheduled services.
- A Flux-capable Grafana data source for the included dashboard queries.

## Choose a collector

| | macOS | Mobile devices |
| --- | --- | --- |
| Script | `jamf_influx.py` | `jamf_mobile_influx.py` |
| Installer | `setup.sh` | `setup-mobile.sh` |
| Configuration template | `jamf-influx.env.example` | `jamf-mobile-influx.env.example` |
| Installed configuration | `/etc/jamf-influx.env` | `/etc/jamf-mobile-influx.env` |
| Service | `jamf-influx.service` | `jamf-mobile-influx.service` |
| Timer | `jamf-influx.timer` | `jamf-mobile-influx.timer` |
| Setup guide | [macOS deployment](docs/deployment.md) | [Mobile deployment](docs/mobile-devices.md) |

Mobile counts combine all returned mobile-device OS versions; they do not separate iOS, iPadOS, and other mobile OS families. Both collectors report Jamf's recorded inventory rather than probing devices live.

## Getting started

1. Create the Jamf integration and InfluxDB bucket and token.
2. Follow the relevant setup guide above and run its installer on your Linux server.
3. Edit the installed configuration file with your environment's values.
4. Run the documented dry run and compare the counts with Jamf.
5. Perform the first write, then enable the collector's timer.

Installers preserve existing configuration and state and do not enable collection automatically. The scripts read process environment variables; they do not load env files themselves. The systemd services load the installed configuration files.

The Mac and mobile collectors for one Jamf environment can share an InfluxDB bucket because their measurement names differ. Use separate buckets for independent Jamf environments: the schema has no environment tag. Keep each collector's state file separate.

## Grafana and data model

- [Grafana panel setup and Flux examples](grafana/README.md)
- [Mobile Flux queries](grafana/mobile/)
- [Normalization, measurements, and state behavior](docs/data-model.md)
- [Mobile schema and operations](docs/mobile-devices.md)

Current-distribution queries select one snapshot timestamp to avoid including stale version labels. History queries show changes over time, and freshness queries help identify missed collection runs. The examples require Flux; they are not InfluxDB 3 SQL queries.

## Development

Create a virtual environment and install runtime and development dependencies:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
```

Run the offline tests and formatting check:

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m black --check --diff .
```

Apply formatting before submitting changes:

```sh
.venv/bin/python -m black .
```

Black is pinned in `requirements-dev.txt` so local and CI formatting agree. GitHub Actions runs the test suite on Python 3.10–3.15 and checks Black formatting on every push and pull request. Tests mock Jamf and InfluxDB; no service credentials are required. The workflow also checks installer shell syntax. Live API access and systemd deployment should be verified separately on the target server.

## Credentials and operations

Keep real credentials in the protected installed configuration files, not in source control. Use a separate read-only InfluxDB token for Grafana. Local env files and runtime state are ignored by Git; only placeholder templates belong in the repository.

See the deployment guides for permissions, logs, manual runs, credential rotation, state recovery, and troubleshooting. If a credential is accidentally committed, rotate it; deleting the file does not remove it from Git history.
