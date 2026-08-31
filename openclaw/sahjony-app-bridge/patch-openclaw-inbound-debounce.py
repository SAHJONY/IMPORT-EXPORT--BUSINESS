from __future__ import annotations

import pathlib
import shutil
import sys
import time

MARKER = "/* SAHJONY_OPENCLAW_INBOUND_DEBOUNCE_COMPAT */"
OLD = "const admission = flush.admission.catch(reportOnce);\n    const completion = flush.completion.catch(reportOnce);"
NEW = "const completionSource = flush?.completion ?? (typeof flush?.then === \"function\" ? flush : Promise.resolve());\n    const admissionSource = flush?.admission ?? completionSource;\n    const admission = Promise.resolve(admissionSource).catch(reportOnce); /* SAHJONY_OPENCLAW_INBOUND_DEBOUNCE_COMPAT */\n    const completion = Promise.resolve(completionSource).catch(reportOnce);"


def main() -> int:
    if len(sys.argv) != 2:
        print("USAGE_ERROR")
        return 2

    dist = pathlib.Path(sys.argv[1])
    if not dist.is_dir():
        print("DIST_NOT_FOUND")
        return 2

    patched: list[str] = []
    already: list[str] = []
    candidates: list[str] = []

    for path in sorted(dist.rglob("*.js")):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue

        if MARKER in text:
            already.append(str(path.relative_to(dist)))
            continue

        if "flush.admission.catch(reportOnce)" in text:
            candidates.append(str(path.relative_to(dist)))

        if OLD not in text:
            continue

        backup = path.with_suffix(path.suffix + f".backup.{int(time.time())}")
        shutil.copy2(path, backup)
        path.write_text(text.replace(OLD, NEW, 1), encoding="utf-8")
        patched.append(str(path.relative_to(dist)))

    if patched:
        print("PATCHED:" + ",".join(patched))
        return 0
    if already:
        print("ALREADY_PATCHED:" + ",".join(already))
        return 0
    if candidates:
        print("CANDIDATE_PATTERN_DIFFERENT:" + ",".join(candidates))
        return 4

    print("SIGNATURE_NOT_FOUND")
    return 4


if __name__ == "__main__":
    raise SystemExit(main())
