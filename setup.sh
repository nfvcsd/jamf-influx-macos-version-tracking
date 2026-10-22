#!/bin/bash
sudo apt update
sudo apt install -y python3 python3-venv

sudo useradd \
  --system \
  --no-create-home \
  --shell /usr/sbin/nologin \
  jamfinflux

sudo mkdir -p /opt/jamf-influx
sudo mkdir -p /var/lib/jamf-influx

sudo chown jamfinflux:jamfinflux /var/lib/jamf-influx

sudo python3 -m venv /opt/jamf-influx/venv

sudo /opt/jamf-influx/venv/bin/pip install \
  requests \
  influxdb-client