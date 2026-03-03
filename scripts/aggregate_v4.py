#!/usr/bin/env python3
"""
Standalone IPv4 CIDR aggregator with Russian (RU) subnet filtering.

Reads a list of IPv4 CIDR prefixes from ip-ranges-v4.txt (or a file given as
the first argument), removes any prefixes that overlap with Russian IP
allocations (fetched from RIPE NCC delegated statistics), and collapses the
remainder into the smallest possible set of CIDR blocks.

This guarantees that NO foreign IPs are added — only addresses already covered
by at least one input prefix will be present in the output.

Usage:
    python scripts/aggregate_v4.py                      # default file
    python scripts/aggregate_v4.py path/to/input.txt    # custom input
    python scripts/aggregate_v4.py input.txt output.txt # custom input+output
    python scripts/aggregate_v4.py --skip-ru-filter      # skip RU filtering
"""

import ipaddress
import os
import sys
import time
import urllib.error
import urllib.request

RIPE_DELEGATED_URL = (
    "https://ftp.ripe.net/pub/stats/ripencc/delegated-ripencc-extended-latest"
)
REQUEST_TIMEOUT = 60


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
    return None


def fetch_ru_networks():
    """Fetch Russian IPv4 allocations from RIPE NCC delegated statistics."""
    print("Fetching Russian IP allocations from RIPE NCC...")
    data = fetch_url(RIPE_DELEGATED_URL)
    if not data:
        print("  WARNING: Could not fetch RIPE data, skipping RU filter")
        return []

    ru_networks = []
    for line in data.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("|")
        if len(parts) < 5:
            continue
        cc, addr_type = parts[1], parts[2]
        if cc != "RU" or addr_type != "ipv4":
            continue
        try:
            start = ipaddress.IPv4Address(parts[3])
            count = int(parts[4])
            end = ipaddress.IPv4Address(int(start) + count - 1)
            ru_networks.extend(
                ipaddress.summarize_address_range(start, end)
            )
        except (ValueError, TypeError, OverflowError):
            continue

    ru_networks = list(
        ipaddress.collapse_addresses(sorted(set(ru_networks)))
    )
    print(f"  Loaded {len(ru_networks)} Russian IPv4 prefixes")
    return ru_networks


def subtract_ru(networks, ru_networks):
    """Remove all IPs covered by ru_networks from the input networks."""
    if not ru_networks:
        return networks

    result = list(networks)
    removed_count = 0

    for excl in ru_networks:
        new_result = []
        for net in result:
            if not net.overlaps(excl):
                new_result.append(net)
            elif net.subnet_of(excl):
                removed_count += 1
            elif excl.subnet_of(net):
                new_result.extend(net.address_exclude(excl))
                removed_count += 1
        result = new_result

    if removed_count:
        print(f"  Removed/carved {removed_count} overlaps with RU allocations")
    return result


def read_prefixes(filepath):
    """Read IPv4 CIDR prefixes from a text file (one per line)."""
    networks = []
    errors = 0
    with open(filepath, "r") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                net = ipaddress.ip_network(line, strict=False)
                if net.version != 4:
                    print(
                        f"  Skipping non-IPv4 entry on line {lineno}: {line}"
                    )
                    continue
                networks.append(net)
            except ValueError:
                errors += 1
                print(f"  Invalid CIDR on line {lineno}: {line}")
    if errors:
        print(f"  Total invalid entries skipped: {errors}")
    return networks


def aggregate(networks):
    """Collapse networks into the smallest set without adding foreign IPs."""
    return list(ipaddress.collapse_addresses(sorted(set(networks))))


def write_prefixes(filepath, networks):
    """Write aggregated prefixes to a file, one per line."""
    with open(filepath, "w") as fh:
        for net in networks:
            fh.write(f"{net}\n")


def main():
    skip_ru = "--skip-ru-filter" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]

    script_dir = os.path.dirname(os.path.abspath(__file__))
    default_input = os.path.join(script_dir, "..", "ip-ranges-v4.txt")

    input_path = args[0] if len(args) > 0 else default_input
    output_path = args[1] if len(args) > 1 else input_path

    input_path = os.path.normpath(input_path)
    output_path = os.path.normpath(output_path)

    print(f"Reading prefixes from: {input_path}")
    networks = read_prefixes(input_path)
    original_count = len(networks)
    print(f"  Loaded {original_count} IPv4 prefixes")

    if not skip_ru:
        ru_nets = fetch_ru_networks()
        networks = subtract_ru(networks, ru_nets)
    else:
        print("  Skipping RU filter (--skip-ru-filter)")

    aggregated = aggregate(networks)
    print(f"\n  After aggregation: {len(aggregated)} prefixes")
    if original_count:
        pct = 100 * (1 - len(aggregated) / original_count)
        print(
            f"  Reduction: {original_count} -> {len(aggregated)} "
            f"({pct:.1f}% fewer entries)"
        )

    write_prefixes(output_path, aggregated)
    print(f"  Written to: {output_path}")


if __name__ == "__main__":
    main()
