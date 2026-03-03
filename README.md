# amazonaws-ip-ranges

Aggregated IP ranges from major cloud and hosting providers, compressed into
minimal CIDR lists via `ipaddress.collapse_addresses()`.

A GitHub Actions workflow runs daily to fetch the latest ranges and commit the
result.

## Providers

| Provider | Source |
|---|---|
| AWS | https://ip-ranges.amazonaws.com/ip-ranges.json |
| Cloudflare | https://www.cloudflare.com/ips-v4 / ips-v6 |
| DigitalOcean | https://digitalocean.com/geo/google.csv |
| Oracle Cloud | https://docs.oracle.com/en-us/iaas/tools/public_ip_ranges.json |
| Hetzner | RIPE Stat – AS24940 |
| OVH | RIPE Stat – AS16276 |
| Vultr | RIPE Stat – AS20473 |
| Scaleway | RIPE Stat – AS12876 |
| Melbicom | RIPE Stat – AS51167 |
| FranTech / BuyVM | RIPE Stat – AS53667 |
| Contabo | RIPE Stat – AS40021 |

## Output files

| File | Description |
|---|---|
| `ip-ranges-v4.txt` | Aggregated IPv4 CIDR ranges |
| `ip-ranges-v6.txt` | Aggregated IPv6 CIDR ranges |
| `ip-ranges-all.txt` | Combined IPv4 + IPv6 list |

## Manual run

```bash
python scripts/fetch_and_aggregate.py
```

## Standalone IPv4 aggregation

Re-aggregate `ip-ranges-v4.txt` without fetching new data.  Uses
`ipaddress.collapse_addresses()` so **no foreign IPs are added**.

```bash
# Re-aggregate the default file in-place
python scripts/aggregate_v4.py

# Custom input/output
python scripts/aggregate_v4.py input.txt output.txt
```