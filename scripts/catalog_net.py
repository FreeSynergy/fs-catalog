"""Downloads for the generator: public https files only, size-limited; failures are `Transient` (never stop bump or sign)."""
import ipaddress
import socket
import subprocess
import sys
import urllib.parse

import catalog_schema as schema


class Skip(Exception):
    """This package cannot be listed right now (draft, missing release or file). The run goes on without it."""


class Transient(Skip):
    """A download failed (network, server): nothing is wrong with the data. Never stops bump or sign (see `gen_catalog.main`)."""


def _public_host(url):
    """False when the FIRST host of `url` resolves to a loopback, private, link-local or otherwise internal address.
    Only a first line of defence: a redirect (https only, at most 3) or DNS rebinding between this check and curl is not covered;
    the generator runs on a GitHub runner that holds no internal services, and only reads public pictures."""
    host = urllib.parse.urlsplit(url).hostname or ""
    try:
        found = {a[4][0] for a in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)}
    except OSError:
        return True  # cannot resolve now: curl fails the same way and that is reported as a transient failure
    return all(ipaddress.ip_address(a.split("%")[0]).is_global for a in found)


def fetch(url, limit=schema.SCREENSHOT_LIMIT):
    """Bytes of a public file (icon, picture): https only (also after redirects), at most `limit` bytes, no internal first host.
    A failed download is `Transient` (try again next run), never a half entry; a file over the limit is an error."""
    if not _public_host(url):
        sys.exit(f"{url}: the host is a loopback or private address; only public https addresses are fetched")
    done = subprocess.run(
        ["curl", "-fsSL", "--proto", "=https", "--proto-redir", "=https", "--max-redirs", "3", "--max-time", "60", "--max-filesize", str(limit), url],
        capture_output=True)
    if done.returncode == 63:  # CURLE_FILESIZE_EXCEEDED
        sys.exit(f"{url}: larger than {limit} bytes")
    if done.returncode != 0:
        raise Transient(f"{url}: could not be downloaded (curl exit {done.returncode})")
    if len(done.stdout) > limit:
        sys.exit(f"{url}: larger than {limit} bytes")
    return done.stdout
