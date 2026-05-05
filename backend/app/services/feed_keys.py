from __future__ import annotations

import hashlib
import json


def query_feed_fingerprint(title: str, location: str) -> str:
    blob = json.dumps(
        {
            "location": (location or "").strip().lower(),
            "title": (title or "").strip().lower(),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(blob.encode()).hexdigest()
