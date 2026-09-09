from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

from country_crm_api import DEFAULT_DEPARTMENTS
from global_lead_search_api import (
    _persist_candidate,
    _research_with_openai,
    department_config,
    now,
)
from insforge_backend import get_backend

RUNNABLE = {
    "RESEARCH_QUEUED",
    "RESEARCH_PARTIAL",
    "RESEARCH_FAILED",
    "RESEARCH_NO_RESULTS",
    "CANDIDATES_FOUND",
}


def enabled() -> bool:
    return os.getenv("LEAD_SEARCH_AUTONOMY_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}


def target_count() -> int:
    try:
        return max(3, min(int(os.getenv("LEAD_SEARCH_AUTONOMY_TARGET", "10")), 25))
    except ValueError:
        return 10


def country_for_hour() -> str:
    priority = ["CU", "US", "MX", "DO", "PA", "CO", "BR", "ES", "AE", "CN", "IN", "VN"]
    ordered = []
    for code in priority + list(DEFAULT_DEPARTMENTS):
        if code not in ordered:
            ordered.append(code)
    hour_bucket = int(datetime.now(timezone.utc).timestamp() // 3600)
    return ordered[hour_bucket % len(ordered)]


async def create_rotation_job() -> dict:
    backend = get_backend()
    code = country_for_hour()
    config = department_config(code)
    job_id = f"auto_{code.lower()}_{int(datetime.now(timezone.utc).timestamp())}"
    row = {
        "job_id": job_id,
        "country_code": config["country_code"],
        "country_name": config["country_name"],
        "primary_language": config["primary_language"],
        "sectors": config["sector_priorities"],
        "lead_types": config["target_lead_types"],
        "target_count": target_count(),
        "search_notes": (
            "24/7 autonomous research rotation. Find real, current, evidence-grounded commercial organizations. "
            "A discovered company is a research lead only, never qualified demand. Prefer primary sources. "
            "Do not send outreach, invent demand, or create binding commitments."
        ),
        "source_classes": config["source_classes"],
        "status": "RESEARCH_QUEUED",
        "candidate_count": 0,
        "accepted_count": 0,
        "routing_department": config["routing"],
        "authority": "RESEARCH_AND_QUALIFICATION_ONLY",
        "created_at": now(),
        "updated_at": now(),
    }
    await backend.insert("global_lead_search_jobs", row)
    return row


async def pick_job() -> dict:
    backend = get_backend()
    rows = await backend.select(
        "global_lead_search_jobs",
        params={"order": "updated_at.asc", "limit": "200"},
    ) or []
    for row in rows:
        if str(row.get("status") or "").upper() in RUNNABLE:
            target = int(row.get("target_count") or 0)
            accepted = int(row.get("accepted_count") or 0)
            if accepted < target:
                return row
    return await create_rotation_job()


async def run_job(job: dict) -> dict:
    backend = get_backend()
    job_id = str(job["job_id"])
    target = int(job.get("target_count") or 0)
    accepted_before = int(job.get("accepted_count") or 0)
    remaining = max(0, target - accepted_before)
    if remaining <= 0:
        await backend.patch(
            "global_lead_search_jobs",
            {"status": "RESEARCH_COMPLETED", "updated_at": now()},
            params={"job_id": f"eq.{job_id}"},
        )
        return {"job_id": job_id, "status": "RESEARCH_COMPLETED", "inserted": 0, "duplicates": 0}

    await backend.patch(
        "global_lead_search_jobs",
        {"status": "RESEARCH_RUNNING", "updated_at": now()},
        params={"job_id": f"eq.{job_id}"},
    )

    candidates = await _research_with_openai(job, min(remaining, target_count()))
    inserted = 0
    duplicates = 0
    for candidate in candidates:
        result = await _persist_candidate(candidate)
        if result["duplicate_candidate"]:
            duplicates += 1
        else:
            inserted += 1

    refreshed_rows = await backend.select(
        "global_lead_search_jobs",
        params={"job_id": f"eq.{job_id}", "limit": "1"},
    ) or []
    refreshed = refreshed_rows[0] if refreshed_rows else job
    accepted = int(refreshed.get("accepted_count") or 0)
    final_status = "RESEARCH_COMPLETED" if accepted >= target else ("RESEARCH_PARTIAL" if candidates else "RESEARCH_NO_RESULTS")
    await backend.patch(
        "global_lead_search_jobs",
        {"status": final_status, "updated_at": now()},
        params={"job_id": f"eq.{job_id}"},
    )
    return {
        "job_id": job_id,
        "country": job.get("country_code"),
        "status": final_status,
        "accepted": accepted,
        "target": target,
        "inserted": inserted,
        "duplicates": duplicates,
    }


async def main() -> None:
    if not enabled():
        print("lead-search autopilot disabled")
        return
    if not os.getenv("OPENAI_API_KEY", "").strip():
        raise RuntimeError("OPENAI_API_KEY is required")
    job = await pick_job()
    result = await run_job(job)
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
