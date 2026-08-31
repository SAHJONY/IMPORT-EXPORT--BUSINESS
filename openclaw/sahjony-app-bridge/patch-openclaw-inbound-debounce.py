from __future__ import annotations

import pathlib
import shutil
import sys
import time

MARKER = "/* SAHJONY_OPENCLAW_INBOUND_DEBOUNCE_COMPAT */"
ADMISSION_OLD = "flush.admission.catch(reportOnce)"
COMPLETION_OLD = "flush.completion.catch(reportOnce)"
ADMISSION_NEW = "Promise.resolve(flush?.admission ?? flush?.completion ?? flush).catch(reportOnce) /* SAHJONY_OPENCLAW_INBOUND_DEBOUNCE_COMPAT */"
COMPLETION_NEW = "Promise.resolve(flush?.completion ?? flush).catch(reportOnce)"


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
    partial: list[str] = []

    for path in sorted(dist.rglob("*.js")):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue

        if MARKER in text:
            already.append(str(path.relative_to(dist)))
            continue

        has_admission = ADMISSION_OLD in text
        has_completion = COMPLETION_OLD in text
        if not has_admission and not has_completion:
            continue
        if not (has_admission and has_completion):
            partial.append(str(path.relative_to(dist)))
            continue

        backup = path.with_suffix(path.suffix + f".backup.{int(time.time())}")
        shutil.copy2(path, backup)
        new_text = text.replace(ADMISSION_OLD, ADMISSION_NEW, 1)
        new_text = new_text.replace(COMPLETION_OLD, COMPLETION_NEW, 1)
        path.write_text(new_text, encoding="utf-8")
        patched.append(str(path.relative_to(dist)))

    if patched:
        print("PATCHED:" + ",".join(patched))
        return 0
    if already:
        print("ALREADY_PATCHED:" + ",".join(already))
        return 0
    if partial:
        print("PARTIAL_SIGNATURE:" + ",".join(partial))
        return 4

    print("SIGNATURE_NOT_FOUND")
    return 4


if __name__ == "__main__":
    raise SystemExit(main())
