"""Checks GitHub for a newer release of the program.

Uses Python's HTTPS client with the certifi certificate bundle shipped inside the program, so the check
does not depend on the Windows certificate store (Qt's network stack failed there with
"issuer certificate ... could not be found").
"""
import json
import re
import ssl
import threading
import urllib.error
import urllib.request

from PySide6.QtCore import QObject, Signal

from .version import BUILD, RELEASES_REPO, REPO

API = "https://api.github.com/repos/{}/releases/latest"
RELEASES_PAGE = f"https://github.com/{RELEASES_REPO}/releases/latest"


def parse_release(data):
    """Return (build number, notes, download url) from the GitHub release JSON, or None."""
    m = re.search(r"(\d+)$", data.get("tag_name") or "")
    if not m:
        return None
    assets = data.get("assets") or []
    url = next((a.get("browser_download_url") for ext in (".exe", ".zip") for a in assets
                if (a.get("name") or "").lower().endswith(ext)), None)
    return int(m.group(1)), (data.get("body") or "").strip(), url or data.get("html_url") or RELEASES_PAGE


def is_newer(latest_build, current=BUILD):
    return current > 0 and latest_build > current


def ssl_contexts():
    """The bundled certifi roots first, then the system store (needed behind company proxies that
    inspect HTTPS with their own root certificate installed in Windows)."""
    out = []
    try:
        import certifi
        out.append(ssl.create_default_context(cafile=certifi.where()))
    except ImportError:
        pass
    out.append(ssl.create_default_context())
    return out


def fetch_release(repo, timeout=10):
    req = urllib.request.Request(API.format(repo), headers={"Accept": "application/vnd.github+json",
                                                         "User-Agent": "Collections"})
    last = None
    for ctx in ssl_contexts():
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as e:
            if not isinstance(getattr(e, "reason", None), ssl.SSLError):
                raise
            last = e
    raise last


def fetch_latest(timeout=10):
    """The newest release of the downloads repository and the code repository (the code repository may be
    private or gone; while moving to the downloads repository both may have releases)."""
    found, errors = [], []
    for repo in (RELEASES_REPO, REPO):
        try:
            data = fetch_release(repo, timeout)
        except urllib.error.HTTPError as e:
            errors.append(e)
            continue
        if parse_release(data):
            found.append(data)
    if not found:
        if errors:
            raise errors[0]
        return {}
    return max(found, key=lambda d: parse_release(d)[0])


class UpdateChecker(QObject):
    """result(newer: bool, build: int, notes: str, url: str) — or failed(message). Runs in a background thread."""
    result = Signal(bool, int, str, str)
    failed = Signal(str)

    def check(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            info = parse_release(fetch_latest())
        except Exception as e:  # noqa: BLE001 - reported to the user on a manual check
            self.failed.emit(str(e))
            return
        if not info:
            self.failed.emit("لا توجد إصدارات منشورة بعد.")
            return
        build, notes, url = info
        self.result.emit(is_newer(build), build, notes, url)
