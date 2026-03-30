"""HTTP client for comfy-runner server integration."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse, urlunparse

import requests as req


def runner_request(
    method: str,
    server_url: str,
    path: str,
    *,
    json_body: dict | None = None,
    timeout: int = 120,
) -> dict[str, Any]:
    """Send a request to the comfy-runner server and return the JSON response.

    Returns {"ok": false, "error": "..."} on connection or HTTP errors
    so callers never need to catch exceptions.
    """
    parsed = urlparse(server_url)
    if parsed.scheme == "https" and not parsed.port:
        # Default to port 9189 for runner server connections
        netloc = f"{parsed.hostname}:9189"
        server_url = urlunparse(parsed._replace(netloc=netloc))

    url = server_url.rstrip("/") + path
    try:
        resp = req.request(
            method,
            url,
            json=json_body,
            timeout=timeout,
            headers={"Accept": "application/json"},
        )
        data = resp.json()
        if isinstance(data, dict):
            return data
        return {"ok": False, "error": f"Unexpected response: {data!r}"}
    except req.ConnectionError:
        return {"ok": False, "error": f"Cannot connect to runner server at {server_url}"}
    except req.Timeout:
        return {"ok": False, "error": f"Request to {url} timed out after {timeout}s"}
    except req.RequestException as e:
        return {"ok": False, "error": str(e)}
    except ValueError:
        return {"ok": False, "error": f"Invalid JSON response from {url}"}
