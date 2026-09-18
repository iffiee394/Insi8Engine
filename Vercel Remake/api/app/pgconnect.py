from __future__ import annotations

import ipaddress
import socket
import subprocess
from functools import lru_cache
from typing import Any
from urllib.parse import urlparse

import psycopg2
import requests
from psycopg2.extras import RealDictCursor


def _is_ip_address(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def _resolve_with_nslookup(host: str) -> str:
    try:
        result = subprocess.run(
            ["nslookup", host],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception:
        return ""

    for line in result.stdout.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("Server:") or stripped.startswith("Address:"):
            continue
        if stripped.startswith("Addresses:"):
            candidates = stripped.split(":", 1)[1].strip().split()
        else:
            candidates = stripped.split()
        for candidate in candidates:
            try:
                parsed = ipaddress.ip_address(candidate)
            except ValueError:
                continue
            if parsed.version == 4:
                return str(parsed)
    return ""


@lru_cache(maxsize=32)
def _resolve_hostaddr(host: str) -> str:
    if not host or _is_ip_address(host):
        return ""

    try:
        records = socket.getaddrinfo(host, None, family=socket.AF_INET, type=socket.SOCK_STREAM)
        for record in records:
            address = record[4][0]
            if address:
                return address
    except socket.gaierror:
        pass

    nslookup_address = _resolve_with_nslookup(host)
    if nslookup_address:
        return nslookup_address

    response = requests.get(
        "https://dns.google/resolve",
        params={"name": host, "type": "A"},
        timeout=5,
    )
    response.raise_for_status()
    data = response.json()
    for answer in data.get("Answer", []):
        if answer.get("type") == 1:
            address = str(answer.get("data", "")).strip()
            if address:
                return address
    return ""


def connect_postgres(url: str) -> Any:
    parsed = urlparse(url)
    kwargs: dict[str, Any] = {"connect_timeout": 15, "cursor_factory": RealDictCursor}
    host = parsed.hostname or ""
    hostaddr = _resolve_hostaddr(host)
    if hostaddr:
        kwargs["hostaddr"] = hostaddr
    return psycopg2.connect(url, **kwargs)
