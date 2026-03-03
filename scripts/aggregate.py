#!/usr/bin/env python3
"""
Aggressive CIDR aggregator with Russian (RU) subnet filtering.

Reads IPv4 and IPv6 CIDR lists, removes any prefixes overlapping with
Russian IP allocations (fetched from RIPE NCC delegated statistics), applies
aggressive supernetting beyond ``ipaddress.collapse_addresses()``, and writes
the result back.

This guarantees that NO Russian IPs remain in the output.

Usage:
    python scripts/aggregate.py                 # default files
    python scripts/aggregate.py --skip-ru-filter # skip RU filtering
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

# Supernetting parameters
SUPERNET_COVERAGE = 0.5  # merge children into parent when they cover >= 50%
MAX_SUPERNET_ROUNDS = 3  # limit iterative supernetting rounds
MIN_PREFIXLEN_V4 = 8     # don't supernet below /8 for IPv4
MIN_PREFIXLEN_V6 = 20    # don't supernet below /20 for IPv6


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
    """Fetch Russian IPv4 and IPv6 allocations from RIPE NCC."""
    print("Fetching Russian IP allocations from RIPE NCC...")
    data = fetch_url(RIPE_DELEGATED_URL)
    if not data:
        print("  WARNING: Could not fetch RIPE data, skipping RU filter")
        return [], []

    ru_v4 = []
    ru_v6 = []
    for line in data.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("|")
        if len(parts) < 5:
            continue
        cc, addr_type = parts[1], parts[2]
        if cc != "RU":
            continue
        try:
            if addr_type == "ipv4":
                # IPv4: parts[4] is host count
                start = ipaddress.IPv4Address(parts[3])
                count = int(parts[4])
                end = ipaddress.IPv4Address(int(start) + count - 1)
                ru_v4.extend(
                    ipaddress.summarize_address_range(start, end)
                )
            elif addr_type == "ipv6":
                # IPv6: parts[4] is prefix length
                prefix = f"{parts[3]}/{parts[4]}"
                ru_v6.append(ipaddress.ip_network(prefix, strict=False))
        except (ValueError, TypeError, OverflowError):
            continue

    ru_v4 = list(ipaddress.collapse_addresses(sorted(set(ru_v4))))
    ru_v6 = list(ipaddress.collapse_addresses(sorted(set(ru_v6))))
    print(f"  Loaded {len(ru_v4)} Russian IPv4 prefixes")
    print(f"  Loaded {len(ru_v6)} Russian IPv6 prefixes")
    return ru_v4, ru_v6


def subtract_networks(networks, exclusions):
    """Remove all IPs covered by *exclusions* from *networks*."""
    if not exclusions:
        return networks

    result = list(networks)
    removed = 0

    for excl in exclusions:
        new_result = []
        for net in result:
            if not net.overlaps(excl):
                new_result.append(net)
            elif net.subnet_of(excl):
                removed += 1
            elif excl.subnet_of(net):
                new_result.extend(net.address_exclude(excl))
                removed += 1
        result = new_result

    if removed:
        print(f"  Removed/carved {removed} overlaps with RU allocations")
    return result


def _supernet_pass(networks, min_prefixlen):
    """One round: merge children into parent when coverage >= threshold."""
    networks = list(ipaddress.collapse_addresses(sorted(set(networks))))

    by_parent = {}
    for net in networks:
        if net.prefixlen <= min_prefixlen:
            continue
        parent = net.supernet()
        by_parent.setdefault(parent, []).append(net)

    result = []
    merged = set()

    for parent, children in by_parent.items():
        covered = sum(c.num_addresses for c in children)
        if covered / parent.num_addresses >= SUPERNET_COVERAGE:
            result.append(parent)
            merged.update(children)

    for net in networks:
        if net not in merged:
            result.append(net)

    return list(ipaddress.collapse_addresses(sorted(set(result))))


def supernet_aggressive(networks, min_prefixlen=0):
    """Iterative supernetting with bounded rounds."""
    for _ in range(MAX_SUPERNET_ROUNDS):
        new_networks = _supernet_pass(networks, min_prefixlen)
        if new_networks == networks:
            break
        networks = new_networks
    return networks


def read_prefixes(filepath):
    """Read CIDR prefixes from a text file (one per line)."""
    networks = []
    errors = 0
    with open(filepath, "r") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                networks.append(ipaddress.ip_network(line, strict=False))
            except ValueError:
                errors += 1
                print(f"  Invalid CIDR on line {lineno}: {line}")
    if errors:
        print(f"  Skipped {errors} invalid entries")
    return networks


def write_prefixes(filepath, networks):
    """Write prefixes to file, one per line."""
    with open(filepath, "w") as fh:
        for net in networks:
            fh.write(f"{net}\n")


def main():
    skip_ru = "--skip-ru-filter" in sys.argv

    script_dir = os.path.dirname(os.path.abspath(__file__))
    base_dir = os.path.join(script_dir, "..")

    v4_path = os.path.normpath(os.path.join(base_dir, "ip-ranges-v4.txt"))
    v6_path = os.path.normpath(os.path.join(base_dir, "ip-ranges-v6.txt"))
    all_path = os.path.normpath(os.path.join(base_dir, "ip-ranges-all.txt"))

    # ── Read ──────────────────────────────────────────────────────────
    print(f"Reading IPv4 prefixes from: {v4_path}")
    v4_nets = [n for n in read_prefixes(v4_path) if n.version == 4]
    print(f"  Loaded {len(v4_nets)} IPv4 prefixes")

    print(f"Reading IPv6 prefixes from: {v6_path}")
    v6_nets = [n for n in read_prefixes(v6_path) if n.version == 6]
    print(f"  Loaded {len(v6_nets)} IPv6 prefixes")

    orig_v4, orig_v6 = len(v4_nets), len(v6_nets)

    # ── Supernet (before filtering so the filter catches any added IPs) ──
    print("\nSupernetting IPv4...")
    v4_nets = supernet_aggressive(v4_nets, min_prefixlen=MIN_PREFIXLEN_V4)
    print(f"  {orig_v4} -> {len(v4_nets)} prefixes")

    print("Supernetting IPv6...")
    v6_nets = supernet_aggressive(v6_nets, min_prefixlen=MIN_PREFIXLEN_V6)
    print(f"  {orig_v6} -> {len(v6_nets)} prefixes")

    # ── RU filter ─────────────────────────────────────────────────────
    if not skip_ru:
        ru_v4, ru_v6 = fetch_ru_networks()
        print("\nFiltering IPv4...")
        v4_nets = subtract_networks(v4_nets, ru_v4)
        print("Filtering IPv6...")
        v6_nets = subtract_networks(v6_nets, ru_v6)
    else:
        print("\nSkipping RU filter (--skip-ru-filter)")

    # ── Final collapse ────────────────────────────────────────────────
    v4_agg = list(ipaddress.collapse_addresses(sorted(set(v4_nets))))
    v6_agg = list(ipaddress.collapse_addresses(sorted(set(v6_nets))))

    print(f"\nFinal results:")
    print(f"  IPv4: {orig_v4} -> {len(v4_agg)} prefixes")
    print(f"  IPv6: {orig_v6} -> {len(v6_agg)} prefixes")

    # ── Write ─────────────────────────────────────────────────────────
    write_prefixes(v4_path, v4_agg)
    print(f"  Written IPv4 to: {v4_path}")

    write_prefixes(v6_path, v6_agg)
    print(f"  Written IPv6 to: {v6_path}")

    write_prefixes(all_path, v4_agg + v6_agg)
    print(f"  Written combined to: {all_path}")

    print("\nDone.")


if __name__ == "__main__":
    main()
