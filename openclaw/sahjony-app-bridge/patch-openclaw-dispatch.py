from __future__ import annotations

import pathlib
import re
import shutil
import sys
import time


def main() -> int:
    if len(sys.argv) != 2:
        print("USAGE_ERROR")
        return 2

    dist = pathlib.Path(sys.argv[1])
    files = sorted(path for path in dist.rglob("*.js") if path.is_file())
    if not files:
        print("NO_JS_BUNDLES")
        return 2

    marker = "/* SAHJONY_OPENCLAW_DISPATCH_COMPAT */"
    signature_text = "runChannelInboundEvent prepared turns must declare runDispatchLifecycle when creating runDispatch"
    needle = re.compile(
        r'''if\s*\(\s*!lifecycle\s*\)\s*throw\s+new\s+Error\(\s*["']runChannelInboundEvent prepared turns must declare runDispatchLifecycle when creating runDispatch["']\s*\)\s*;?'''
    )

    patched: list[str] = []
    already: list[str] = []
    candidates: list[str] = []

    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue

        if marker in text:
            already.append(str(path.relative_to(dist)))
            continue

        if signature_text not in text:
            continue

        candidates.append(str(path.relative_to(dist)))
        new_text, count = needle.subn(
            "if (!lifecycle) { /* SAHJONY_OPENCLAW_DISPATCH_COMPAT */ return; }",
            text,
            count=1,
        )
        if not count:
            continue

        backup = path.with_name(path.name + f".backup.{int(time.time())}")
        shutil.copy2(path, backup)
        path.write_text(new_text, encoding="utf-8")
        patched.append(str(path.relative_to(dist)))

    if patched:
        print("PATCHED:" + ",".join(patched))
        return 0
    if already:
        print("ALREADY_PATCHED:" + ",".join(already))
        return 0
    if candidates:
        print("CANDIDATE_SIGNATURE_FOUND_BUT_PATTERN_DIFFERENT:" + ",".join(candidates))
        return 5

    print("SIGNATURE_NOT_FOUND")
    return 4


if __name__ == "__main__":
    raise SystemExit(main())
