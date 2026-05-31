from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from refsift.config import get_settings
from refsift.models import CheckCost, CheckResult, CheckStatus

_BOT_PROTECTION_HOSTS = {
    "linkedin.com", "www.linkedin.com",
    "twitter.com", "x.com", "www.twitter.com",
    "facebook.com", "www.facebook.com",
    "instagram.com", "www.instagram.com",
}

_BOT_PROTECTION_INDICATORS = [
    "cloudflare", "just a moment", "enable javascript", "checking your browser",
    "ddos protection", "attention required",
]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; refsift/0.1; citation verification bot; "
        "+https://github.com/refsift/refsift)"
    )
}


def _is_bot_protected(url: str, status: int, body: str) -> bool:
    from urllib.parse import urlparse
    host = urlparse(url).hostname or ""
    if host in _BOT_PROTECTION_HOSTS:
        return True
    if status == 403 and any(ind in body.lower() for ind in _BOT_PROTECTION_INDICATORS):
        return True
    return False


async def _check_single_url(
    client: httpx.AsyncClient, url: str
) -> tuple[str, CheckStatus, dict[str, Any]]:
    evidence: dict[str, Any] = {"url": url}
    try:
        r = await client.head(url, headers=_HEADERS, follow_redirects=True)
        if r.status_code == 405:
            r = await client.get(url, headers=_HEADERS, follow_redirects=True)
        final_url = str(r.url)
        evidence["status_code"] = r.status_code
        evidence["final_url"] = final_url
        evidence["redirected"] = final_url != url

        body = ""
        if r.status_code == 403:
            try:
                body = r.text[:2000]
            except Exception:
                pass

        if _is_bot_protected(final_url, r.status_code, body):
            evidence["bot_protection"] = True
            return url, CheckStatus.SKIPPED, evidence

        if 200 <= r.status_code < 300:
            return url, CheckStatus.PASS, evidence
        else:
            evidence["error"] = f"HTTP {r.status_code}"
            return url, CheckStatus.FAIL, evidence

    except httpx.TimeoutException:
        evidence["error"] = "timeout"
        return url, CheckStatus.WARN, evidence
    except httpx.HTTPError as e:
        evidence["error"] = str(e)
        return url, CheckStatus.FAIL, evidence


async def check_url_liveness(
    urls: list[str],
    use_cache: bool = True,
) -> CheckResult:
    start = time.monotonic()

    if not urls:
        return CheckResult(
            name="url_liveness",
            status=CheckStatus.SKIPPED,
            confidence=1.0,
            evidence={"reason": "no urls"},
            cost=CheckCost(elapsed_ms=0.0),
        )

    results: list[dict[str, Any]] = []
    settings = get_settings()

    async with httpx.AsyncClient(
        timeout=settings.request_timeout, follow_redirects=True
    ) as client:
        for url in urls:
            if use_cache:
                from refsift.cache import get_cache
                cache = get_cache()
                cached = cache.get("url_liveness", url)
                if cached is not None:
                    results.append({**cached, "from_cache": True})
                    continue

            _, status, evidence = await _check_single_url(client, url)
            results.append({"status": status.value, "evidence": evidence})

            if use_cache:
                from refsift.cache import get_cache
                cache = get_cache()
                cache.set("url_liveness", url, {"status": status.value, "evidence": evidence})

            await asyncio.sleep(settings.politeness_delay)

    elapsed = (time.monotonic() - start) * 1000

    statuses = [CheckStatus(r["status"]) for r in results]

    if any(s == CheckStatus.FAIL for s in statuses):
        overall = CheckStatus.FAIL
        confidence = 0.9
    elif any(s == CheckStatus.WARN for s in statuses):
        overall = CheckStatus.WARN
        confidence = 0.7
    elif all(s == CheckStatus.SKIPPED for s in statuses):
        overall = CheckStatus.SKIPPED
        confidence = 0.5
    else:
        overall = CheckStatus.PASS
        confidence = 0.95

    return CheckResult(
        name="url_liveness",
        status=overall,
        confidence=confidence,
        evidence={"url_results": results, "total_urls": len(urls)},
        cost=CheckCost(api_calls=len(urls), elapsed_ms=elapsed),
    )
