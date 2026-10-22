# Jamf → InfluxDB macOS version tracking

Collect aggregate macOS version counts from the Jamf Platform API and write hourly snapshots to InfluxDB 2.x. Grafana displays the fleet distribution and its history using Flux.

The collector requests `OPERATING_SYSTEM` inventory, counts versions locally, and retains only version totals. It does not store device names, serial numbers, or inventory records.

## Project files

| File | Purpose |
| --- | --- |
| `jamf_influx.py` | OAuth authentication, pagination, normalization, snapshot writes and state |
| `jamf-influx.env.example` | Credential-free configuration template |
| `requirements.txt` | Python runtime dependencies |
| `setup.sh` | Debian/Ubuntu installation; leaves activation to the operator |
| `systemd/` | Oneshot service and hourly timer |
| `docs/deployment.md` | Prerequisites, values, paths, installation and operations |
| `docs/data-model.md` | Normalization, measurements, state and failure behavior |
| `grafana/` | Copyable Flux queries and panel guidance |
| `tests/` | Offline regression tests with mocked services |

## Start here

Read [the deployment guide](docs/deployment.md), create a Jamf Platform integration and an InfluxDB bucket/token, then run `sudo bash setup.sh` on your Linux server. Configure `/etc/jamf-influx.env`, run the documented dry run, and enable the timer after the first successful write.

For local development (Python 3.10+):

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python jamf_influx.py --help
```

The script reads process environment variables; it does not automatically load an env file. `--dry-run` still authenticates to Jamf and reads inventory, but does not write InfluxDB or state. Tests use no real credentials or network services.

## Handoff provenance and scope

This repository already contained the normalized collector from the “Track Jamf OS Versions” conversation. The handoff preserves its Platform API endpoints, environment header, measurement names, and state format. Deployment and documentation were reconstructed from that implementation and the available chat context; the earlier downloadable Word/Markdown attachments were not available to copy.

One installation represents one Jamf environment per bucket. There is no tenant/environment tag: do not send multiple independent fleets into the same bucket with this schema. The Grafana examples require a Flux-capable InfluxDB backend; they are not InfluxDB 3 SQL examples. OptiSigns/JWT embedding setup is separate from collection and is not enabled by this installer.

Real env files and runtime state are ignored. Never commit credentials. If a real credential was committed in earlier history, ignoring or deleting its file does not remove it from history: rotate it and coordinate history cleanup separately.

## Mobile devices

A separate `jamf_mobile_influx.py` collector is available with `setup-mobile.sh`, `jamf-mobile-influx.env.example`, and its own systemd service/timer. It follows the same run pattern while keeping mobile measurements and state separate. See [mobile setup and operations](docs/mobile-devices.md). The Mac and mobile collectors for one environment can share a bucket; independent environments still need separate buckets.
