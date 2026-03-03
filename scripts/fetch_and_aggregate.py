#!/usr/bin/env python3
"""
Fetch IP ranges from multiple cloud/hosting providers and aggregate them
into a single compressed CIDR list using ipaddress.collapse_addresses().

Supported providers:
  - AWS
  - Cloudflare
  - DigitalOcean
  - Oracle Cloud
  - Hetzner (via ASN)
  - OVH (via ASN)
  - Vultr (via ASN)
  - Scaleway (via ASN)
  - Melbicom (via ASN)
  - FranTech/BuyVM (via ASN)
  - Contabo (via ASN)
"""

import ipaddress
import json
import csv
import io
import os
import sys
import time
import urllib.request
import urllib.error

OUTPUT_DIR = os.environ.get("OUTPUT_DIR", ".")

PROVIDERS_DIRECT = {
    "aws": {
        "urls": ["https://ip-ranges.amazonaws.com/ip-ranges.json"],
        "parser": "aws",
    },
    "cloudflare": {
        "urls": [
            "https://www.cloudflare.com/ips-v4",
            "https://www.cloudflare.com/ips-v6",
        ],
        "parser": "plain",
    },
    "digitalocean": {
        "urls": ["https://digitalocean.com/geo/google.csv"],
        "parser": "digitalocean_csv",
    },
    "oracle": {
        "urls": [
            "https://docs.oracle.com/en-us/iaas/tools/public_ip_ranges.json"
        ],
        "parser": "oracle",
    },
}

PROVIDERS_ASN = {
    "hetzner": ["AS24940"],
    "ovh": ["AS16276"],
    "vultr": ["AS20473"],
    "scaleway": ["AS12876"],
    "melbicom": ["AS51167"],
    "frantech_buyvm": ["AS53667"],
    "contabo": ["AS40021"],
}

REQUEST_TIMEOUT = 30
RIPE_DELAY = 1  # seconds between RIPE API calls to avoid rate limiting


def fetch_url(url):
    """Fetch URL content with retries."""
    for attempt in range(3):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "cloud-ip-aggregator/1.0"},
            )
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                return resp.read().decode("utf-8")
        except (urllib.error.URLError, OSError) as exc:
            print(f"  Attempt {attempt + 1}/3 failed for {url}: {exc}")
            if attempt < 2:
                time.sleep(2 ** attempt)
    print(f"  WARNING: Could not fetch {url}")
    return None


def parse_aws(data):
    """Parse AWS ip-ranges.json."""
    obj = json.loads(data)
    prefixes = [p["ip_prefix"] for p in obj.get("prefixes", [])]
    prefixes += [p["ipv6_prefix"] for p in obj.get("ipv6_prefixes", [])]
    return prefixes


def parse_plain(data):
    """Parse plain text list of CIDRs (one per line)."""
    return [line.strip() for line in data.splitlines() if line.strip()]


def parse_digitalocean_csv(data):
    """Parse DigitalOcean CSV geofeed."""
    prefixes = []
    reader = csv.reader(io.StringIO(data))
    for row in reader:
        if row and row[0].strip() and not row[0].startswith("#"):
            prefixes.append(row[0].strip())
    return prefixes


def parse_oracle(data):
    """Parse Oracle Cloud public_ip_ranges.json."""
    obj = json.loads(data)
    prefixes = []
    for region in obj.get("regions", []):
        for cidr_item in region.get("cidrs", []):
            cidr = cidr_item.get("cidr", "")
            if cidr:
                prefixes.append(cidr)
    return prefixes


PARSERS = {
    "aws": parse_aws,
    "plain": parse_plain,
    "digitalocean_csv": parse_digitalocean_csv,
    "oracle": parse_oracle,
}


def fetch_direct_providers():
    """Fetch IP ranges from providers with direct API endpoints."""
    all_prefixes = []
    for name, cfg in PROVIDERS_DIRECT.items():
        print(f"Fetching {name}...")
        parser_fn = PARSERS[cfg["parser"]]
        for url in cfg["urls"]:
            data = fetch_url(url)
            if data:
                prefixes = parser_fn(data)
                print(f"  {url}: {len(prefixes)} prefixes")
                all_prefixes.extend(prefixes)
    return all_prefixes


def fetch_asn_prefixes(asn):
    """Fetch announced prefixes for an ASN using RIPE Stat API."""
    url = (
        f"https://stat.ripe.net/data/announced-prefixes/data.json"
        f"?resource={asn}"
    )
    data = fetch_url(url)
    if not data:
        return []
    obj = json.loads(data)
    prefixes = []
    for item in obj.get("data", {}).get("prefixes", []):
        prefix = item.get("prefix", "")
        if prefix:
            prefixes.append(prefix)
    return prefixes


def fetch_asn_providers():
    """Fetch IP ranges from providers identified by ASN."""
    all_prefixes = []
    for name, asns in PROVIDERS_ASN.items():
        print(f"Fetching {name} (ASN: {', '.join(asns)})...")
        for asn in asns:
            prefixes = fetch_asn_prefixes(asn)
            print(f"  {asn}: {len(prefixes)} prefixes")
            all_prefixes.extend(prefixes)
            time.sleep(RIPE_DELAY)
    return all_prefixes


def parse_and_separate(raw_prefixes):
    """Parse CIDR strings into IPv4 and IPv6 network objects."""
    v4_nets = []
    v6_nets = []
    errors = 0
    for cidr in raw_prefixes:
        try:
            net = ipaddress.ip_network(cidr.strip(), strict=False)
            if net.version == 4:
                v4_nets.append(net)
            else:
                v6_nets.append(net)
        except ValueError:
            errors += 1
    if errors:
        print(f"  Skipped {errors} invalid CIDR entries")
    return v4_nets, v6_nets


def aggregate(networks):
    """Collapse a list of ip_network objects into the smallest set."""
    return list(ipaddress.collapse_addresses(sorted(set(networks))))


def write_list(filepath, networks):
    """Write networks to a text file, one CIDR per line."""
    with open(filepath, "w") as fh:
        for net in networks:
            fh.write(f"{net}\n")
    print(f"Wrote {len(networks)} entries to {filepath}")


def main():
    print("=" * 60)
    print("Cloud Provider IP Range Aggregator")
    print("=" * 60)

    raw = []
    raw.extend(fetch_direct_providers())
    raw.extend(fetch_asn_providers())

    print(f"\nTotal raw prefixes collected: {len(raw)}")

    v4, v6 = parse_and_separate(raw)
    print(f"  IPv4: {len(v4)} prefixes")
    print(f"  IPv6: {len(v6)} prefixes")

    v4_agg = aggregate(v4)
    v6_agg = aggregate(v6)
    print(f"\nAfter aggregation:")
    print(f"  IPv4: {len(v4)} -> {len(v4_agg)}")
    print(f"  IPv6: {len(v6)} -> {len(v6_agg)}")

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    write_list(os.path.join(OUTPUT_DIR, "ip-ranges-v4.txt"), v4_agg)
    write_list(os.path.join(OUTPUT_DIR, "ip-ranges-v6.txt"), v6_agg)
    write_list(
        os.path.join(OUTPUT_DIR, "ip-ranges-all.txt"), v4_agg + v6_agg
    )

    print("\nDone.")


if __name__ == "__main__":
    main()
