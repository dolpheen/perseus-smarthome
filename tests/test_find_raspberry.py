import importlib.util
import ipaddress
import sys
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "find_raspberry.py"
SPEC = importlib.util.spec_from_file_location("find_raspberry", MODULE_PATH)
find_raspberry = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = find_raspberry
SPEC.loader.exec_module(find_raspberry)


def test_parse_arp_output_normalizes_mac_addresses():
    output = """
? (172.16.0.42) at b8:27:eb:01:02:03 on en0 ifscope [ethernet]
? (172.16.0.43) at 0:a0:de:92:fb:99 on en0 ifscope [ethernet]
"""
    assert find_raspberry.parse_arp_output(output) == {
        "172.16.0.42": "b8:27:eb:01:02:03",
        "172.16.0.43": "00:a0:de:92:fb:99",
    }


def test_pi_mac_detection_uses_known_ouis():
    assert find_raspberry.looks_like_pi_mac("b8:27:eb:01:02:03")
    assert find_raspberry.looks_like_pi_mac("DC-A6-32-01-02-03")
    assert not find_raspberry.looks_like_pi_mac("00:a0:de:92:fb:99")


def test_ifconfig_network_parsing_supports_macos_hex_netmask():
    output = """
en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500
    inet 172.16.0.102 netmask 0xffffff00 broadcast 172.16.0.255
"""
    assert find_raspberry.parse_ifconfig_networks(output) == {
        ipaddress.IPv4Network("172.16.0.0/24")
    }


def test_env_upsert_preserves_existing_values_and_adds_missing(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("RPI_SSH_USER=pi\nRPI_SSH_HOST=old.local\n", encoding="utf-8")

    find_raspberry.upsert_env(
        env_path,
        {
            "RPI_SSH_HOST": "172.16.0.50",
            "RPI_MCP_URL": "http://172.16.0.50:8000/mcp",
        },
    )

    assert (
        env_path.read_text(encoding="utf-8")
        == "RPI_SSH_USER=pi\n"
        "RPI_SSH_HOST=172.16.0.50\n"
        "\n"
        "RPI_MCP_URL=http://172.16.0.50:8000/mcp\n"
    )


def test_iter_scan_ips_respects_host_cap():
    networks = [ipaddress.IPv4Network("192.168.1.0/24")]
    assert find_raspberry.iter_scan_ips(networks, max_hosts=3) == [
        "192.168.1.1",
        "192.168.1.2",
        "192.168.1.3",
    ]


def test_split_subnet_values_accepts_commas_and_whitespace():
    assert find_raspberry.split_subnet_values(
        "172.16.0.0/24, 192.168.1.0/24\n10.0.0.5"
    ) == ["172.16.0.0/24", "192.168.1.0/24", "10.0.0.5"]
