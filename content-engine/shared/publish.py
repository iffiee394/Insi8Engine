"""
Publishing / scheduling.

Both reference builds converge on Blotato for this, independently (one was
sponsored, one explicitly was not), so it is the sensible paid default. But the
engine must not REQUIRE it, because the whole build is otherwise free and a
$29/mo dependency for the last mile is a bad trade when you have one client.

Two adapters:

  export   FREE, always available. Writes a publish-ready folder: assets in
           order, one caption file per platform, and a manifest. You upload it
           by hand, or hand the folder to whatever scheduler you already pay for.

  blotato  OPTIONAL. Set BLOTATO_API_KEY. Nine platforms from one endpoint.

SAFETY: every adapter defaults to DRAFT/SCHEDULE, never immediate publish, and
publishing is refused unless the asset carries a clinical approval and passes
the compliance gate a second time at publish time. Reference build 1 states the
same rule as a prompt instruction ("nothing gets posted until you say go");
here it is enforced in code, because a prompt instruction is not a control.
See DECISIONS.md D-19 and D-20.
"""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import ClientProfile


class PublishError(RuntimeError):
    pass


@dataclass
class PublishResult:
    adapter: str
    platform: str
    status: str            # 'exported' | 'scheduled' | 'drafted' | 'failed'
    detail: str = ""
    remote_id: str = ""
    path: str = ""


# ---------------------------------------------------------------- free export


def export_bundle(
    *,
    client: ClientProfile,
    slug: str,
    lane: str,
    asset_paths: list[str],
    captions: dict[str, dict[str, Any]],
    out_root: Path,
    scheduled_for: str = "",
) -> list[PublishResult]:
    """Write a folder a human can upload from. Always works, costs nothing."""
    bundle = out_root / "publish" / slug
    media_dir = bundle / "media"
    media_dir.mkdir(parents=True, exist_ok=True)

    copied: list[str] = []
    for i, p in enumerate(asset_paths, start=1):
        src = Path(p)
        if not src.exists():
            continue
        dst = media_dir / f"{i:02d}{src.suffix}"
        shutil.copy2(src, dst)
        copied.append(dst.name)

    results: list[PublishResult] = []
    for platform, data in captions.items():
        text = data.get("caption", "")
        tags = " ".join(data.get("hashtags", []) or [])
        body = f"{text}\n\n{tags}".strip()
        cap_file = bundle / f"caption-{platform}.txt"
        cap_file.write_text(body, encoding="utf-8")
        results.append(PublishResult("export", platform, "exported", path=str(cap_file)))

    manifest = {
        "slug": slug,
        "lane": lane,
        "client": client.slug,
        "practice": client.name,
        "identification_block": client.identification_block,
        "media_in_order": copied,
        "captions": {k: v.get("caption", "") for k, v in captions.items()},
        "hashtags": {k: v.get("hashtags", []) for k, v in captions.items()},
        "scheduled_for": scheduled_for,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "upload_order_note": "Media files are numbered in posting order. "
                             "Carousel slide 01 is the cover.",
    }
    (bundle / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return results


# ---------------------------------------------------------------- blotato


BLOTATO_BASE = "https://backend.blotato.com/v2"


def blotato_available() -> bool:
    return bool(os.getenv("BLOTATO_API_KEY", ""))


def _blotato_headers() -> dict[str, str]:
    key = os.getenv("BLOTATO_API_KEY", "")
    if not key:
        raise PublishError("BLOTATO_API_KEY is not set")
    return {"blotato-api-key": key, "Content-Type": "application/json"}


def blotato_accounts() -> list[dict[str, Any]]:
    import requests

    r = requests.get(f"{BLOTATO_BASE}/accounts", headers=_blotato_headers(), timeout=60)
    r.raise_for_status()
    data = r.json()
    return data.get("items", data) if isinstance(data, dict) else data


def blotato_upload_media(path: str) -> str:
    """Blotato takes a public URL or base64; this uploads a local file."""
    import base64

    import requests

    p = Path(path)
    payload = {
        "file": base64.b64encode(p.read_bytes()).decode("ascii"),
        "filename": p.name,
    }
    r = requests.post(f"{BLOTATO_BASE}/media", headers=_blotato_headers(),
                      json=payload, timeout=300)
    r.raise_for_status()
    return r.json().get("url", "")


def blotato_schedule(
    *,
    account_id: str,
    platform: str,
    text: str,
    media_urls: list[str],
    scheduled_time: str,
) -> PublishResult:
    """Schedule (never immediate-post) a single item."""
    import requests

    if not scheduled_time:
        raise PublishError(
            "refusing to publish without a scheduled_time; this engine schedules, "
            "it does not fire immediate posts"
        )
    payload = {
        "post": {
            "accountId": account_id,
            "target": {"targetType": platform},
            "content": {"text": text, "platform": platform, "mediaUrls": media_urls},
        },
        "scheduledTime": scheduled_time,
    }
    r = requests.post(f"{BLOTATO_BASE}/posts", headers=_blotato_headers(),
                      json=payload, timeout=120)
    if r.status_code >= 400:
        return PublishResult("blotato", platform, "failed", detail=r.text[:400])
    return PublishResult("blotato", platform, "scheduled",
                         remote_id=str(r.json().get("id", "")))


# ---------------------------------------------------------------- gate


def preflight(
    *,
    conn: Any,
    client: ClientProfile,
    asset_row: Any,
    payload: dict[str, Any],
    lane: str,
) -> tuple[bool, str]:
    """The publish gate. Enforced in code, not in a prompt."""
    from . import compliance, store

    if asset_row is None:
        return False, "asset not found"

    if not store.has_approval(conn, asset_row["id"], "clinical"):
        return False, (
            f"no clinical approval on file. {client.compliance.get('clinical_approver','The approver')} "
            f"must sign off before this can be scheduled."
        )

    if lane == "carousel":
        result = compliance.check_carousel(payload, client, conn=conn)
    else:
        result = compliance.check_reel_script(payload, client, conn=conn)

    if not result.passed:
        return False, "compliance re-check failed at publish time:\n" + result.report()

    return True, "ok"
