#!/usr/bin/env python3

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import requests
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

# =========================================================
# Configuration
# =========================================================

JAMF_BASE_URL = os.environ.get("JAMF_BASE_URL", "https://us.api.jamfcloud.com").rstrip(
    "/"
)

JAMF_CLIENT_ID = os.environ.get("JAMF_CLIENT_ID")
JAMF_CLIENT_SECRET = os.environ.get("JAMF_CLIENT_SECRET")
JAMF_ENVIRONMENT_ID = os.environ.get("JAMF_ENVIRONMENT_ID")

JAMF_PAGE_SIZE = os.environ.get("JAMF_PAGE_SIZE", "500")

INFLUX_URL = os.environ.get("INFLUX_URL")
INFLUX_ORG = os.environ.get("INFLUX_ORG")
INFLUX_BUCKET = os.environ.get("INFLUX_BUCKET", "jamf_inventory")
INFLUX_TOKEN = os.environ.get("INFLUX_TOKEN")

STATE_FILE = Path(
    os.environ.get("STATE_FILE", "/var/lib/jamf-mobile-influx/known_versions.json")
)


# =========================================================
# Environment validation
# =========================================================


def validate_environment(dry_run=False):
    global JAMF_PAGE_SIZE
    try:
        JAMF_PAGE_SIZE = int(JAMF_PAGE_SIZE)
        if JAMF_PAGE_SIZE <= 0:
            raise ValueError
    except (TypeError, ValueError):
        raise RuntimeError("JAMF_PAGE_SIZE must be a positive integer.") from None

    required = {
        "JAMF_CLIENT_ID": JAMF_CLIENT_ID,
        "JAMF_CLIENT_SECRET": JAMF_CLIENT_SECRET,
        "JAMF_ENVIRONMENT_ID": JAMF_ENVIRONMENT_ID,
    }

    if not dry_run:
        required.update(
            {
                "INFLUX_URL": INFLUX_URL,
                "INFLUX_ORG": INFLUX_ORG,
                "INFLUX_TOKEN": INFLUX_TOKEN,
            }
        )

    missing = [key for key, value in required.items() if not value]

    if missing:
        raise RuntimeError(
            "Missing required environment variables: " + ", ".join(missing)
        )


# =========================================================
# mobile version handling
# =========================================================


def normalize_version(version):
    """
    Normalize Jamf mobile version strings.

    Examples:

        15.4.0     -> 15.4
        26.5.0     -> 26.5
        26.5.0.0   -> 26.5

        26.5.1     -> 26.5.1
        15.7.9     -> 15.7.9

        27.0       -> 27.0
        15.7       -> 15.7

        None       -> Unknown
        ""         -> Unknown

    The function removes trailing ".0" components only
    when at least major.minor will remain.

    Therefore:

        27.0 stays 27.0
        15.4.0 becomes 15.4
    """

    if version is None:
        return "Unknown"

    version = str(version).strip()

    if not version:
        return "Unknown"

    if version.lower() == "unknown":
        return "Unknown"

    parts = version.split(".")

    while len(parts) > 2 and parts[-1] == "0":
        parts.pop()

    return ".".join(parts)


def major_version(version):
    """
    Return the major mobile version.

    Examples:

        26.6.2 -> 26
        15.7   -> 15
    """

    if version == "Unknown":
        return "Unknown"

    return version.split(".", 1)[0]


def version_sort_key(version):
    """
    Produce a numeric sort key for mobile versions.

    This ensures:

        26.10
        26.9
        26.8

    are sorted numerically rather than alphabetically.
    """

    if version == "Unknown":
        return (-1,)

    numbers = re.findall(r"\d+", version)

    if not numbers:
        return (-1,)

    return tuple(int(x) for x in numbers)


# =========================================================
# Jamf authentication
# =========================================================


def get_jamf_token():
    url = f"{JAMF_BASE_URL}/auth/token"

    response = requests.post(
        url,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "client_credentials",
            "client_id": JAMF_CLIENT_ID,
            "client_secret": JAMF_CLIENT_SECRET,
        },
        timeout=30,
    )

    if not response.ok:
        raise RuntimeError(
            f"Jamf authentication failed: "
            f"HTTP {response.status_code}"
        )

    payload = response.json()

    token = payload.get("access_token")

    if not token:
        raise RuntimeError(
            "Jamf authentication succeeded, " "but no access_token was returned."
        )

    return token


# =========================================================
# Jamf inventory retrieval
# =========================================================


def get_inventory_page(token, page):
    """
    Retrieve one page of Jamf Pro device inventory.

    Only the GENERAL section is requested.
    """

    url = f"{JAMF_BASE_URL}" "/pro/v2/mobile-devices/detail"

    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        "X-Environment-Id": JAMF_ENVIRONMENT_ID,
    }

    params = {
        "section": "GENERAL",
        "sort": "mobileDeviceId:asc",
        "page": page,
        "page-size": JAMF_PAGE_SIZE,
    }

    response = requests.get(
        url,
        headers=headers,
        params=params,
        timeout=60,
    )

    # If the token expired, get another token
    # and retry the request once.
    if response.status_code == 401:
        token = get_jamf_token()

        headers["Authorization"] = f"Bearer {token}"

        response = requests.get(
            url,
            headers=headers,
            params=params,
            timeout=60,
        )

    if not response.ok:
        raise RuntimeError(
            f"Jamf inventory request failed "
            f"on page {page}: "
            f"HTTP {response.status_code}"
        )

    payload = response.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise RuntimeError("Jamf returned an invalid inventory response.")
    return payload, token


def collect_os_versions():
    """
    Retrieve all Jamf mobile devices and build a Counter
    containing only normalized mobile version counts.

    No device-specific information is retained.
    """

    token = get_jamf_token()

    counts = Counter()

    page = 0
    total_devices = 0
    expected_total = None

    while True:
        data, token = get_inventory_page(token, page)

        results = data["results"]
        page_total = data.get("totalCount")
        if page_total is not None:
            if type(page_total) is not int or page_total < 0:
                raise RuntimeError("Jamf returned an invalid totalCount.")
            if expected_total is not None and page_total != expected_total:
                raise RuntimeError("Jamf inventory changed during collection; retry next run.")
            expected_total = page_total

        if not results:
            if expected_total is not None and total_devices != expected_total:
                raise RuntimeError("Jamf returned an incomplete inventory; refusing to write.")
            break

        for device in results:
            os_info = device.get("general") or {}

            version = normalize_version(os_info.get("osVersion"))

            counts[version] += 1
            total_devices += 1

        print(f"Retrieved Jamf page {page}: " f"{len(results)} mobile devices")

        if expected_total is not None:
            if total_devices > expected_total:
                raise RuntimeError("Jamf inventory exceeded totalCount; refusing to write.")
            if total_devices == expected_total:
                break
            page += 1
            continue

        # If Jamf returned fewer records than our page size,
        # this was the final page.
        if len(results) < JAMF_PAGE_SIZE:
            break

        page += 1

    return counts, total_devices


# =========================================================
# Known-version state
# =========================================================


def load_known_versions():
    """
    Load previously observed OS version names.

    This file contains only OS versions, never device
    information.

    Previously stored versions are normalized when loaded
    so an older 15.4.0 entry becomes 15.4.
    """

    if not STATE_FILE.exists():
        return set()

    try:
        with STATE_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)

        if not isinstance(data, dict) or not isinstance(data.get("versions"), list):
            raise ValueError
        versions = data["versions"]
        if not all(isinstance(version, str) for version in versions):
            raise ValueError
        return {normalize_version(version) for version in versions}

    except (OSError, ValueError, TypeError):
        raise RuntimeError(
            "Cannot read known_versions state. Restore or repair it before writing."
        ) from None



def save_known_versions(versions):
    """
    Save the list of OS versions we've seen.

    This allows versions that disappear completely from
    Jamf to be written to InfluxDB with count=0.
    """

    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

    normalized_versions = {normalize_version(version) for version in versions}

    temp_file = STATE_FILE.with_suffix(".tmp")

    with temp_file.open("w", encoding="utf-8") as file:
        json.dump(
            {
                "versions": sorted(
                    normalized_versions,
                    key=version_sort_key,
                    reverse=True,
                )
            },
            file,
            indent=2,
        )

    temp_file.replace(STATE_FILE)


# =========================================================
# Console output
# =========================================================


def print_distribution(counts, total):
    print()
    print("Current Jamf mobile Distribution")
    print("=" * 50)

    for version in sorted(
        counts.keys(),
        key=version_sort_key,
        reverse=True,
    ):
        count = counts[version]

        percentage = (count / total) * 100 if total else 0

        print(f"mobile {version:<15} " f"{count:>6} " f"{percentage:>7.2f}%")

    print("-" * 50)

    print(f"Total mobile devices: {total}")

    print()


# =========================================================
# InfluxDB
# =========================================================


def write_to_influx(current_counts, total_devices, known_versions):
    """
    Write one complete fleet snapshot to InfluxDB.

    Every OS version in the snapshot receives the exact
    same timestamp.

    Previously observed versions that no longer exist in
    Jamf receive count=0.
    """

    snapshot_time = datetime.now(timezone.utc)

    all_versions = set(current_counts.keys()) | set(known_versions)

    points = []

    for version in sorted(
        all_versions,
        key=version_sort_key,
        reverse=True,
    ):
        count = current_counts.get(version, 0)

        point = (
            Point("jamf_mobile_os_distribution")
            .tag("platform", "mobile")
            .tag("version", version)
            .tag("major_version", major_version(version))
            .field("count", int(count))
            .time(snapshot_time, WritePrecision.S)
        )

        points.append(point)

    summary = (
        Point("jamf_mobile_inventory_summary")
        .tag("platform", "mobile")
        .field("total_devices", int(total_devices))
        .field(
            "active_versions",
            int(sum(1 for count in current_counts.values() if count > 0)),
        )
        .field("known_versions", int(len(all_versions)))
        .field("unknown_os", int(current_counts.get("Unknown", 0)))
        .time(snapshot_time, WritePrecision.S)
    )

    points.append(summary)

    with InfluxDBClient(
        url=INFLUX_URL,
        token=INFLUX_TOKEN,
        org=INFLUX_ORG,
    ) as client:

        write_api = client.write_api(write_options=SYNCHRONOUS)

        write_api.write(
            bucket=INFLUX_BUCKET,
            org=INFLUX_ORG,
            record=points,
        )

    return snapshot_time, all_versions


# =========================================================
# Main
# =========================================================


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Collect the current mobile version "
            "distribution from Jamf and optionally "
            "write the aggregate snapshot to InfluxDB."
        )
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Query Jamf and display the current "
            "distribution without writing anything "
            "to InfluxDB."
        ),
    )

    args = parser.parse_args()

    validate_environment(dry_run=args.dry_run)

    print("Authenticating to Jamf Platform API...")

    counts, total = collect_os_versions()

    if total == 0:
        raise RuntimeError(
            "Jamf returned zero mobile devices. " "Refusing to write an empty snapshot."
        )

    print_distribution(counts, total)

    if args.dry_run:
        print("Dry run complete. " "Nothing was written to InfluxDB.")

        return

    known_versions = load_known_versions()

    snapshot_time, all_versions = write_to_influx(
        counts,
        total,
        known_versions,
    )

    # Update the version-state file only after
    # the InfluxDB write succeeds.
    save_known_versions(all_versions)

    print("Successfully wrote Jamf snapshot " "to InfluxDB.")

    print(f"Snapshot timestamp: " f"{snapshot_time.isoformat()}")

    print(f"OS versions written: " f"{len(all_versions)}")


if __name__ == "__main__":
    try:
        main()

    except KeyboardInterrupt:
        print(
            "\nInterrupted.",
            file=sys.stderr,
        )

        sys.exit(130)

    except Exception as exc:
        print(
            f"ERROR: {exc if isinstance(exc, RuntimeError) else type(exc).__name__}",
            file=sys.stderr,
        )

        sys.exit(1)
