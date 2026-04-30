#!/usr/bin/env python3
"""Find a headless Raspberry Pi on the local network by probing SSH."""

from __future__ import annotations

import argparse
import concurrent.futures
import dataclasses
import ipaddress
import json
import os
import re
import socket
import subprocess
import sys
from pathlib import Path
from typing import Iterable


DEFAULT_HOSTNAMES = (
    "raspberrypi.local",
    "raspberrypi",
)

RASPBERRY_PI_OUIS = {
    "b8:27:eb",
    "dc:a6:32",
    "e4:5f:01",
    "d8:3a:dd",
    "2c:cf:67",
}


@dataclasses.dataclass(frozen=True)
class Candidate:
    ip: str
    port: int
    ssh_open: bool
    banner: str = ""
    hostname: str = ""
    mac: str = ""
    source: tuple[str, ...] = ()

    @property
    def likely_raspberry_pi(self) -> bool:
        return looks_like_pi_mac(self.mac)

    @property
    def confidence(self) -> str:
        if self.likely_raspberry_pi:
            return "high"
        if self.hostname.endswith(".local") or self.hostname == "raspberrypi":
            return "medium"
        return "unknown"

    def as_dict(self) -> dict[str, object]:
        return {
            "ip": self.ip,
            "port": self.port,
            "ssh_open": self.ssh_open,
            "banner": self.banner,
            "hostname": self.hostname,
            "mac": self.mac,
            "source": list(self.source),
            "likely_raspberry_pi": self.likely_raspberry_pi,
            "confidence": self.confidence,
        }


def normalize_mac(mac: str) -> str:
    parts = re.findall(r"[0-9a-fA-F]{1,2}", mac)
    if len(parts) < 6:
        return ""
    return ":".join(part.lower().zfill(2) for part in parts[:6])


def looks_like_pi_mac(mac: str) -> bool:
    normalized = normalize_mac(mac)
    return any(normalized.startswith(prefix) for prefix in RASPBERRY_PI_OUIS)


def parse_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def upsert_env(path: Path, updates: dict[str, str]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    seen: set[str] = set()
    output: list[str] = []

    for line in lines:
        stripped = line.strip()
        prefix = "export " if stripped.startswith("export ") else ""
        assignment = stripped.removeprefix("export ").strip()
        if "=" not in assignment or assignment.startswith("#"):
            output.append(line)
            continue
        key = assignment.split("=", 1)[0].strip()
        if key in updates:
            output.append(f"{prefix}{key}={updates[key]}")
            seen.add(key)
        else:
            output.append(line)

    missing = [key for key in updates if key not in seen]
    if missing and output and output[-1].strip():
        output.append("")
    for key in missing:
        output.append(f"{key}={updates[key]}")

    path.write_text("\n".join(output) + "\n", encoding="utf-8")


def run_command(args: list[str], timeout: float = 2.0) -> str:
    try:
        completed = subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return ""
    return completed.stdout + completed.stderr


def parse_arp_output(output: str) -> dict[str, str]:
    entries: dict[str, str] = {}
    for line in output.splitlines():
        ip_match = re.search(r"\((\d{1,3}(?:\.\d{1,3}){3})\)", line)
        mac_match = re.search(r"\bat\s+([0-9a-fA-F:.-]+)\b", line)
        if not ip_match or not mac_match:
            continue
        mac = normalize_mac(mac_match.group(1))
        if mac:
            entries[ip_match.group(1)] = mac
    return entries


def arp_cache() -> dict[str, str]:
    return parse_arp_output(run_command(["arp", "-a"]))


def netmask_to_prefix(netmask: str) -> int:
    if netmask.startswith("0x"):
        mask_int = int(netmask, 16)
        return bin(mask_int).count("1")
    return ipaddress.IPv4Network(f"0.0.0.0/{netmask}").prefixlen


def parse_ifconfig_networks(output: str) -> set[ipaddress.IPv4Network]:
    networks: set[ipaddress.IPv4Network] = set()
    for line in output.splitlines():
        match = re.search(
            r"\binet\s+(\d{1,3}(?:\.\d{1,3}){3})\s+.*?\bnetmask\s+([0-9a-fA-Fx.]+)",
            line,
        )
        if not match:
            continue
        ip = ipaddress.IPv4Address(match.group(1))
        if not is_scan_candidate_ip(ip):
            continue
        try:
            prefix = netmask_to_prefix(match.group(2))
        except ValueError:
            prefix = 24
        networks.add(ipaddress.IPv4Network(f"{ip}/{prefix}", strict=False))
    return networks


def parse_ip_addr_networks(output: str) -> set[ipaddress.IPv4Network]:
    networks: set[ipaddress.IPv4Network] = set()
    for match in re.finditer(r"\binet\s+(\d{1,3}(?:\.\d{1,3}){3}/\d{1,2})\b", output):
        network = ipaddress.IPv4Interface(match.group(1)).network
        if is_scan_candidate_ip(network.network_address + 1):
            networks.add(network)
    return networks


def is_scan_candidate_ip(ip: ipaddress.IPv4Address) -> bool:
    return not (
        ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
        or ip.is_reserved
    )


def local_networks_from_system() -> set[ipaddress.IPv4Network]:
    networks: set[ipaddress.IPv4Network] = set()
    networks.update(parse_ifconfig_networks(run_command(["ifconfig"])))
    networks.update(parse_ip_addr_networks(run_command(["ip", "-o", "-4", "addr", "show"])))

    for ip_text in arp_cache():
        try:
            ip = ipaddress.IPv4Address(ip_text)
        except ValueError:
            continue
        if is_scan_candidate_ip(ip):
            networks.add(ipaddress.IPv4Network(f"{ip}/24", strict=False))

    if not networks:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect(("8.8.8.8", 80))
                ip = ipaddress.IPv4Address(sock.getsockname()[0])
            if is_scan_candidate_ip(ip):
                networks.add(ipaddress.IPv4Network(f"{ip}/24", strict=False))
        except OSError:
            pass

    return networks


def resolve_hostnames(hostnames: Iterable[str]) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for hostname in hostnames:
        try:
            infos = socket.getaddrinfo(hostname, None, family=socket.AF_INET)
        except socket.gaierror:
            continue
        for info in infos:
            ip = info[4][0]
            resolved[ip] = hostname
    return resolved


def iter_scan_ips(networks: Iterable[ipaddress.IPv4Network], max_hosts: int) -> list[str]:
    ips: list[str] = []
    seen: set[str] = set()
    for network in sorted(networks, key=lambda item: (int(item.network_address), item.prefixlen)):
        hosts = [network.network_address] if network.prefixlen == 32 else network.hosts()
        for ip in hosts:
            if not is_scan_candidate_ip(ip):
                continue
            text = str(ip)
            if text in seen:
                continue
            seen.add(text)
            ips.append(text)
            if len(ips) >= max_hosts:
                return ips
    return ips


def probe_ssh(ip: str, port: int, timeout: float) -> Candidate | None:
    try:
        with socket.create_connection((ip, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            try:
                banner = sock.recv(160).decode("utf-8", errors="replace").strip()
            except OSError:
                banner = ""
    except OSError:
        return None
    return Candidate(ip=ip, port=port, ssh_open=True, banner=banner)


def merge_candidates(
    candidates: Iterable[Candidate],
    hostname_sources: dict[str, str],
    mac_sources: dict[str, str],
    scanned_ips: set[str],
) -> list[Candidate]:
    merged: list[Candidate] = []
    for candidate in candidates:
        sources = ["scan"] if candidate.ip in scanned_ips else []
        if candidate.ip in hostname_sources:
            sources.append("hostname")
        if candidate.ip in mac_sources:
            sources.append("arp")
        merged.append(
            dataclasses.replace(
                candidate,
                hostname=hostname_sources.get(candidate.ip, ""),
                mac=mac_sources.get(candidate.ip, ""),
                source=tuple(sources),
            )
        )
    return sorted(
        merged,
        key=lambda item: (
            0 if item.likely_raspberry_pi else 1,
            0 if item.hostname else 1,
            ipaddress.IPv4Address(item.ip),
        ),
    )


def parse_networks(values: list[str]) -> set[ipaddress.IPv4Network]:
    networks: set[ipaddress.IPv4Network] = set()
    for value in values:
        value = value.strip()
        if not value:
            continue
        if "/" not in value:
            value = f"{value}/32"
        networks.add(ipaddress.IPv4Network(value, strict=False))
    return networks


def split_subnet_values(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"[,\s]+", value) if part.strip()]


def print_table(candidates: list[Candidate]) -> None:
    if not candidates:
        print("No SSH hosts found.")
        print("Connect the Raspberry Pi, then rerun with an explicit subnet if needed:")
        print("  python3 tools/find_raspberry.py --subnet 172.16.0.0/24")
        return

    print("SSH hosts found:")
    print("IP              PORT  CONFIDENCE  PI-MAC  MAC                HOSTNAME          BANNER")
    print("-" * 94)
    for item in candidates:
        print(
            f"{item.ip:<15} {item.port:<5} {item.confidence:<11} "
            f"{str(item.likely_raspberry_pi):<7} {item.mac or '-':<18} "
            f"{item.hostname or '-':<17} {item.banner or '-'}"
        )

    likely = [item for item in candidates if item.confidence in {"high", "medium"}]
    if likely:
        chosen = likely[0]
        print()
        print("Most likely Raspberry Pi:")
        print(f"  {chosen.ip}")
        print()
        print("Suggested .env values:")
        print(f"  RPI_SSH_HOST={chosen.ip}")
        print(f"  RPI_MCP_HOST={chosen.ip}")
        print(f"  RPI_MCP_URL=http://{chosen.ip}:8000/mcp")


def update_env_from_candidate(path: Path, candidate: Candidate, mcp_port: int) -> None:
    upsert_env(
        path,
        {
            "RPI_SSH_HOST": candidate.ip,
            "RPI_MCP_HOST": candidate.ip,
            "RPI_MCP_PORT": str(mcp_port),
            "RPI_MCP_URL": f"http://{candidate.ip}:{mcp_port}/mcp",
        },
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Find a headless Raspberry Pi by scanning LAN hosts with SSH open.",
    )
    parser.add_argument("--subnet", action="append", default=[], help="CIDR or IP to scan. Repeatable.")
    parser.add_argument("--port", type=int, default=22, help="SSH port to probe. Default: 22.")
    parser.add_argument("--timeout", type=float, default=0.75, help="TCP timeout in seconds. Default: 0.75.")
    parser.add_argument("--concurrency", type=int, default=128, help="Parallel probes. Default: 128.")
    parser.add_argument("--max-hosts", type=int, default=1024, help="Safety cap for scanned hosts. Default: 1024.")
    parser.add_argument("--hostname", action="append", default=[], help="Hostname to resolve before scanning.")
    parser.add_argument("--no-default-hostnames", action="store_true", help="Do not try raspberrypi hostnames.")
    parser.add_argument("--env-file", default=".env", help="Local env file to read/update. Default: .env.")
    parser.add_argument("--update-env", action="store_true", help="Write discovered host fields to --env-file.")
    parser.add_argument("--select", help="IP to use with --update-env when multiple candidates are found.")
    parser.add_argument("--mcp-port", type=int, default=8000, help="MCP HTTP port for .env output. Default: 8000.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    env_path = Path(args.env_file)
    env = parse_env(env_path)

    hostname_values: list[str] = []
    if not args.no_default_hostnames:
        hostname_values.extend(DEFAULT_HOSTNAMES)
    hostname_values.extend(args.hostname)
    for key in ("RPI_SSH_HOST", "RPI_MCP_HOST"):
        value = env.get(key, "")
        if value and not value.startswith("<") and not re.match(r"^\d{1,3}(?:\.\d{1,3}){3}$", value):
            hostname_values.append(value)

    hostname_sources = resolve_hostnames(dict.fromkeys(hostname_values))

    env_subnets = split_subnet_values(env.get("RPI_DISCOVERY_SUBNET", ""))
    subnet_values = args.subnet or env_subnets
    networks = parse_networks(subnet_values) if subnet_values else local_networks_from_system()
    scan_ips = set(iter_scan_ips(networks, max_hosts=args.max_hosts))
    scan_ips.update(hostname_sources)

    if not scan_ips:
        if args.json:
            print(json.dumps({"candidates": [], "networks": []}, indent=2))
        else:
            print("No local network could be detected. Pass --subnet, for example:")
            print("  python3 tools/find_raspberry.py --subnet 172.16.0.0/24")
        return 2

    candidates: list[Candidate] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as executor:
        futures = [executor.submit(probe_ssh, ip, args.port, args.timeout) for ip in sorted(scan_ips, key=ipaddress.IPv4Address)]
        for future in concurrent.futures.as_completed(futures):
            candidate = future.result()
            if candidate:
                candidates.append(candidate)

    mac_sources = arp_cache()
    merged = merge_candidates(candidates, hostname_sources, mac_sources, scan_ips)

    if args.update_env:
        selected: Candidate | None = None
        if args.select:
            selected = next((item for item in merged if item.ip == args.select), None)
            if not selected:
                print(f"--select IP was not found among candidates: {args.select}", file=sys.stderr)
                return 3
        elif len(merged) == 1:
            selected = merged[0]
        else:
            likely = [item for item in merged if item.confidence in {"high", "medium"}]
            if len(likely) == 1:
                selected = likely[0]
        if not selected:
            print("Refusing to update .env because no single Raspberry Pi candidate was identified.", file=sys.stderr)
            print("Rerun with --select <ip> --update-env after reviewing candidates.", file=sys.stderr)
            return 4
        update_env_from_candidate(env_path, selected, args.mcp_port)

    if args.json:
        print(
            json.dumps(
                {
                    "networks": [str(network) for network in sorted(networks, key=str)],
                    "candidates": [candidate.as_dict() for candidate in merged],
                },
                indent=2,
            )
        )
    else:
        print_table(merged)
        if args.update_env and merged:
            print()
            print(f"Updated {env_path}")

    return 0 if merged else 1


if __name__ == "__main__":
    raise SystemExit(main())
