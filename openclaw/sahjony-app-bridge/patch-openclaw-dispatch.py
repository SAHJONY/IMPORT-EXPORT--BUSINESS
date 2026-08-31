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
    files = sorted(dist.glob("kernel-*.js"))
    if not files:
        print("NO_KERNEL")
        return 2

    needle = re.compile(
        r'''if\s*\(\s*!lifecycle\s*\)\s*throw\s+new\s+Error\(\s*["']runChannelInboundEvent prepared turns must declare runDispatchLifecycle when creating runDispatch["']\s*\)\s*;?'''
    )
    marker = "/* SAHJONY_OPENCLAW_DISPATCH_COMPAT */"
    patched: list[str] = []
    already: list[str] = []

    for path in files:
        text = path.read_text(encoding="utf-8")
        if marker in text:
            already.append(path.name)
            continue

        new_text, count = needle.subn(
            "if (!lifecycle) { /* SAHJONY_OPENCLAW_DISPATCH_COMPAT */ return; }",
            text,
            count=1,
        )
        if not count:
            continue

        backup = path.with_suffix(path.suffix + f".backup.{int(time.time())}")
        shutil.copy2(path, backup)
        path.write_text(new_text, encoding="utf-8")
        patched.append(path.name)

    if patched:
        print("PATCHED:" + ",".join(patched))
        return 0
    if already:
        print("ALREADY_PATCHED:" + ",".join(already))
        return 0

    print("SIGNATURE_NOT_FOUND")
    return 4


if __name__ == "__main__":
    raise SystemExit(main())
