"""Bounded branch execution; deadlines include queueing and query embedding.

Python cannot kill a running model call. Timed-out jobs may finish in the
background, but a process-wide admission bound prevents unbounded accumulation.
No request-local executor context manager waits for them on return.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, TimeoutError, wait
from dataclasses import dataclass, field
from typing import Any, Callable

POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="recipe-recall")
SLOTS = threading.BoundedSemaphore(8)


@dataclass
class BranchResult:
    status: str
    elapsed_ms: float
    hits: list[dict[str, Any]] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)
    query_trace: list[dict[str, Any]] = field(default_factory=list)
    total: dict[str, Any] | None = None
    error_type: str | None = None


def execute_branches(
    branches: dict[str, Callable[[], dict[str, Any]]],
    *,
    execution: str,
    timeout_seconds: float,
    on_progress: Callable[[str, str, float | None], None],
) -> dict[str, BranchResult]:
    def submit(name: str, function: Callable[[], dict[str, Any]]) -> tuple[Future, float]:
        started = time.perf_counter()
        on_progress(name, "running", None)
        if not SLOTS.acquire(blocking=False):
            rejected: Future = Future()
            rejected.set_result(BranchResult("failed", 0.0, error_type="CapacityExceeded"))
            return rejected, started

        def run() -> BranchResult:
            if time.perf_counter() - started >= timeout_seconds:
                return BranchResult("timeout", timeout_seconds * 1000, error_type="BranchTimeout")
            try:
                data = function()
                elapsed = (time.perf_counter() - started) * 1000
                if elapsed >= timeout_seconds * 1000:
                    return BranchResult(
                        "timeout", timeout_seconds * 1000, error_type="BranchTimeout"
                    )
                return BranchResult("complete", elapsed, **data)
            except Exception as exc:
                return BranchResult(
                    "failed",
                    (time.perf_counter() - started) * 1000,
                    error_type=type(exc).__name__,
                    query_trace=getattr(exc, "query_trace", []),
                )

        try:
            future = POOL.submit(run)
        except Exception:
            SLOTS.release()
            raise
        future.add_done_callback(lambda _: SLOTS.release())
        return future, started

    def collect(name: str, job: tuple[Future, float]) -> BranchResult:
        future, started = job
        remaining = max(0.0, timeout_seconds - (time.perf_counter() - started))
        try:
            outcome = future.result(timeout=remaining)
        except TimeoutError:
            future.cancel()  # Removes queued work when it has not started.
            outcome = BranchResult("timeout", timeout_seconds * 1000, error_type="BranchTimeout")
        on_progress(name, outcome.status, round(outcome.elapsed_ms, 2))
        return outcome

    if execution == "serial":
        return {name: collect(name, submit(name, function)) for name, function in branches.items()}
    if execution != "parallel":
        raise ValueError("Unknown execution mode")
    jobs = {name: submit(name, function) for name, function in branches.items()}
    pending = dict(jobs)
    results = {}
    while pending:
        remaining = max(
            0.0,
            min(started + timeout_seconds for _, started in pending.values()) - time.perf_counter(),
        )
        wait(
            [future for future, _ in pending.values()],
            timeout=remaining,
            return_when=FIRST_COMPLETED,
        )
        for name, job in list(pending.items()):
            future, started = job
            if future.done() or time.perf_counter() - started >= timeout_seconds:
                results[name] = collect(name, job)
                del pending[name]
    # Completion order affects progress only, never ranking or response order.
    return {name: results[name] for name in branches}
