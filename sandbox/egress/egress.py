"""Amaan egress proxy: the only way out of the sandbox networks.

Sandboxed programs (the expansion worker, URL.vet's headless Chrome) sit on an
internal Docker network with no route to the internet. Their only way out is this
HTTP proxy, which enforces the sandbox's network rules (docs/DECISIONS.md, D19):

- only ports 80 and 443;
- only public internet addresses: private ranges, loopback, link-local
  (cloud metadata 169.254.169.254), carrier-grade NAT, multicast and IPv6
  local ranges are refused, so a scam page cannot reach the user's router,
  home network or the Amaan server;
- the name is resolved here and the connection goes to the checked address,
  so a page cannot switch to a private address after the check (DNS rebinding);
- no inbound connections, no logs of addresses or links (counts only).

Plain Python standard library, so the image stays small and easy to audit.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import socket
from collections.abc import Callable
from dataclasses import dataclass, field

log = logging.getLogger("amaan.egress")

HEAD_LIMIT = 16 * 1024  # request line + headers
IDLE_TIMEOUT_S = 30.0  # no bytes in either direction
LIFETIME_S = 120.0  # one connection, at most
BYTES_LIMIT = 100 * 1024 * 1024  # one connection, both directions
CONNECT_TIMEOUT_S = 5.0
MAX_CONNECTIONS = 256

BLOCKED = (
    b"HTTP/1.1 403 Forbidden\r\nX-Amaan-Egress: blocked\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
)
BAD_REQUEST = b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
BAD_GATEWAY = b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
HOP_BY_HOP = {b"proxy-connection", b"proxy-authorization", b"connection", b"keep-alive"}


class Blocked(Exception):
    """The destination is not allowed."""


def public_address(ip: str) -> bool:
    """True only for a global unicast address (the public internet)."""
    try:
        addr = ipaddress.ip_address(ip.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address):
        if addr.ipv4_mapped:
            addr = addr.ipv4_mapped
        elif addr.sixtofour or addr.teredo:
            return False  # tunnels that can wrap a private IPv4 address
    return addr.is_global and not addr.is_multicast


@dataclass
class Policy:
    ports: frozenset[int] = frozenset({80, 443})
    address_ok: Callable[[str], bool] = public_address
    stats: dict[str, int] = field(default_factory=lambda: {"allowed": 0, "blocked": 0, "failed": 0})


async def resolve(host: str, port: int, policy: Policy) -> str:
    """The address to connect to. Refuses if ANY address of the name is not allowed."""
    if port not in policy.ports:
        raise Blocked
    host = host.strip("[]")
    try:
        ipaddress.ip_address(host)
        addrs = [host]
    except ValueError:
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except OSError as e:
            raise ConnectionError("name not found") from e
        addrs = list(dict.fromkeys(info[4][0] for info in infos))
    if not addrs or not all(policy.address_ok(a) for a in addrs):
        raise Blocked
    return addrs[0]


def split_host_port(value: str, default_port: int) -> tuple[str, int]:
    if value.startswith("["):  # [IPv6]:port
        host, _, rest = value[1:].partition("]")
        port = rest[1:] if rest.startswith(":") else ""
    else:
        host, _, port = value.rpartition(":") if value.count(":") == 1 else (value, "", "")
    if port and not port.isdigit():
        raise ValueError("bad port")
    return host, int(port) if port else default_port


async def _pipe(src: asyncio.StreamReader, dst: asyncio.StreamWriter, budget: list[int]) -> None:
    try:
        while True:
            chunk = await asyncio.wait_for(src.read(65536), IDLE_TIMEOUT_S)
            if not chunk:
                break
            budget[0] -= len(chunk)
            if budget[0] < 0:
                break
            dst.write(chunk)
            await dst.drain()
    except (TimeoutError, ConnectionError, OSError):
        pass
    finally:
        try:
            dst.close()
        except Exception:  # noqa: BLE001, S110 - the connection is already closed
            pass


async def _relay(client_r, client_w, server_r, server_w) -> None:
    budget = [BYTES_LIMIT]
    tasks = [asyncio.create_task(_pipe(client_r, server_w, budget)),
             asyncio.create_task(_pipe(server_r, client_w, budget))]
    try:
        await asyncio.wait_for(asyncio.gather(*tasks), LIFETIME_S)
    except TimeoutError:
        for t in tasks:
            t.cancel()


async def _open(host: str, port: int, policy: Policy):
    ip = await resolve(host, port, policy)
    return await asyncio.wait_for(asyncio.open_connection(ip, port), CONNECT_TIMEOUT_S)


async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, policy: Policy) -> None:
    try:
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), IDLE_TIMEOUT_S)
    except (TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError, ConnectionError):
        writer.close()
        return
    try:
        first, *header_lines = head[:-4].split(b"\r\n")
        method, target, version = first.decode("latin-1").split(" ")
        if method == "CONNECT":
            host, port = split_host_port(target, 443)
            server_r, server_w = await _open(host, port, policy)
            writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
            await writer.drain()
        elif target.lower().startswith("http://"):
            rest = target[len("http://"):]
            cut = min((i for i in (rest.find(c) for c in "/?#") if i >= 0), default=len(rest))
            hostport, path = rest[:cut], rest[cut:].split("#", 1)[0]
            if "@" in hostport:
                raise ValueError("credentials in proxy target")
            host, port = split_host_port(hostport, 80)
            server_r, server_w = await _open(host, port, policy)
            headers = [h for h in header_lines if h.split(b":", 1)[0].strip().lower() not in HOP_BY_HOP]
            if not path.startswith("/"):
                path = "/" + path
            out = f"{method} {path} {version}".encode("latin-1")
            server_w.write(b"\r\n".join([out, *headers, b"Connection: close", b"", b""]))
            await server_w.drain()
        else:
            writer.write(BAD_REQUEST)
            await writer.drain()
            writer.close()
            return
    except Blocked:
        policy.stats["blocked"] += 1
        writer.write(BLOCKED)
        await writer.drain()
        writer.close()
        return
    except (TimeoutError, ValueError, ConnectionError, OSError):
        policy.stats["failed"] += 1
        writer.write(BAD_GATEWAY)
        try:
            await writer.drain()
        except ConnectionError:
            pass
        writer.close()
        return
    policy.stats["allowed"] += 1
    await _relay(reader, writer, server_r, server_w)


async def serve(host: str = "0.0.0.0", port: int = 3128, policy: Policy | None = None) -> asyncio.base_events.Server:
    policy = policy or Policy()
    limit = asyncio.Semaphore(MAX_CONNECTIONS)

    async def on_client(r, w):
        async with limit:
            await handle(r, w, policy)

    return await asyncio.start_server(on_client, host, port, limit=HEAD_LIMIT)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    policy = Policy()
    server = await serve(port=int(os.environ.get("AMAAN_EGRESS_PORT", "3128")), policy=policy)
    log.info("egress proxy ready: ports 80/443 to public addresses only")
    async with server:
        while True:
            await asyncio.sleep(600)
            log.info("connections: %(allowed)d allowed, %(blocked)d blocked, %(failed)d failed", policy.stats)


if __name__ == "__main__":
    asyncio.run(main())
