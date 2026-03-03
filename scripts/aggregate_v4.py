#!/usr/bin/env python3
"""
Standalone IPv4 CIDR aggregator.

Reads a list of IPv4 CIDR prefixes from ip-ranges-v4.txt (or a file given as
the first argument) and collapses them into the smallest possible set of CIDR
blocks using ipaddress.collapse_addresses().

This guarantees that NO foreign IPs are added — only addresses already covered
by at least one input prefix will be present in the output.

Usage:
    python scripts/aggregate_v4.py                      # default file
    python scripts/aggregate_v4.py path/to/input.txt    # custom input
    python scripts/aggregate_v4.py input.txt output.txt # custom input+output
"""

import ipaddress
import os
import sys


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
                    print(f"  Skipping non-IPv4 entry on line {lineno}: {line}")
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
    script_dir = os.path.dirname(os.path.abspath(__file__))
    default_input = os.path.join(script_dir, "..", "ip-ranges-v4.txt")

    input_path = sys.argv[1] if len(sys.argv) > 1 else default_input
    output_path = sys.argv[2] if len(sys.argv) > 2 else input_path

    input_path = os.path.normpath(input_path)
    output_path = os.path.normpath(output_path)

    print(f"Reading prefixes from: {input_path}")
    networks = read_prefixes(input_path)
    print(f"  Loaded {len(networks)} IPv4 prefixes")

    aggregated = aggregate(networks)
    print(f"  After aggregation: {len(aggregated)} prefixes")
    print(
        f"  Reduction: {len(networks) - len(aggregated)} entries removed "
        f"({100 * (1 - len(aggregated) / max(len(networks), 1)):.1f}%)"
    )

    write_prefixes(output_path, aggregated)
    print(f"  Written to: {output_path}")


if __name__ == "__main__":
    main()
