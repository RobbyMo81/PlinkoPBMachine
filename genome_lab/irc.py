"""Independent Resource Controller (Document 02, build step 6).

The deterministic IRC owns the run, AI-interaction, and container deadlines
and the combined output cap. The scheduler requests work and obeys IRC
decisions; neither the scheduler nor the AI can override the fixed run
limits (G-022). The run clock starts when the owner-authorized run opens
after passing preflight. Each AI interaction is bounded by the earlier of
its 90-second deadline and the run deadline; late responses are discarded
and the timed-out phase is journaled. On a container breach the IRC stops
the attempt through the runtime and confirms exit before permitting further
work.
"""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from genome_lab.config import (
    AI_INTERACTION_SECONDS,
    MAX_AI_INTERACTIONS,
    RUN_SECONDS,
)
from genome_lab.identity import Identity
from genome_lab.journal import Journal
from genome_lab.sandbox import AttemptRequest, AttemptResult, LocalExecutor


class IRCError(RuntimeError):
    """Raised when the IRC refuses dispatch or a limit is violated."""


@dataclass
class IRCState:
    run_id: str
    opened: bool = False
    closed: bool = False
    start_monotonic: float | None = None
    interactions: int = 0
    attempts: int = 0
    stop_reason: str | None = None
    remaining_budget_note: dict = field(default_factory=dict)


class IRC:
    def __init__(
        self,
        journal: Journal,
        identity: Identity,
        run_id: str,
        run_seconds: int = RUN_SECONDS,
        ai_interaction_seconds: float = AI_INTERACTION_SECONDS,
    ) -> None:
        self._journal = journal
        self._identity = identity
        self._state = IRCState(run_id=run_id)
        self._run_seconds = run_seconds
        self._ai_interaction_seconds = ai_interaction_seconds

    def set_remaining_seconds(self, remaining: float) -> None:
        """Restart resume: re-anchor the clock to the saved remaining time."""
        if not self._state.opened or self._state.start_monotonic is None:
            raise IRCError("run is not open")
        self._state.start_monotonic = time.monotonic() - (self._run_seconds - remaining)

    @property
    def state(self) -> IRCState:
        return self._state

    def _log(self, kind: str, payload: dict) -> None:
        self._journal.submit_as(self._identity, kind, self._state.run_id, payload)

    def open_run(self, preflight_reference: str) -> None:
        """Start the run clock. Called once, after authorization and preflight PASS."""
        if self._state.opened:
            raise IRCError("run already opened")
        self._state.opened = True
        self._state.start_monotonic = time.monotonic()
        self._log(
            "run_opened",
            {
                "preflight_reference": preflight_reference,
                "run_seconds": self._run_seconds,
                "ai_interaction_seconds": AI_INTERACTION_SECONDS,
                "max_ai_interactions": MAX_AI_INTERACTIONS,
            },
        )

    def remaining_seconds(self) -> float:
        if not self._state.opened or self._state.start_monotonic is None:
            raise IRCError("run is not open")
        elapsed = time.monotonic() - self._state.start_monotonic
        return self._run_seconds - elapsed

    def guard_dispatch(self, phase: str) -> None:
        """Run dispatch cutoff: refuse work after the deadline or close."""
        if not self._state.opened:
            raise IRCError(f"dispatch refused in {phase}: run not open")
        if self._state.closed:
            raise IRCError(f"dispatch refused in {phase}: run closed")
        if self.remaining_seconds() <= 0:
            raise IRCError(f"dispatch refused in {phase}: run deadline passed")

    def ai_interaction(self, call: Callable[[], object], phase: str) -> tuple[bool, object]:
        """Bound an in-run AI interaction by min(90s, remaining run time).

        The response is discarded when it arrives late; the timed-out phase is
        journaled. Affected work stops; independent authorized work continues.
        """
        self.guard_dispatch(f"ai:{phase}")
        if self._state.interactions >= MAX_AI_INTERACTIONS:
            raise IRCError(f"AI interaction budget exhausted ({MAX_AI_INTERACTIONS})")
        budget = min(self._ai_interaction_seconds, self.remaining_seconds())
        holder: dict[str, object] = {}

        def runner() -> None:
            holder["value"] = call()

        thread = threading.Thread(target=runner, daemon=True)
        thread.start()
        thread.join(budget)
        self._state.interactions += 1
        timed_out = thread.is_alive()
        if timed_out or self.remaining_seconds() <= 0:
            self._log(
                "ai_timeout", {"phase": phase, "budget_seconds": budget, "timed_out": timed_out}
            )
            return False, None
        value = holder.get("value")
        self._log("ai_interaction", {"phase": phase, "budget_seconds": budget, "used": True})
        return True, value

    def execute_attempt(self, executor: LocalExecutor, request: AttemptRequest) -> AttemptResult:
        self.guard_dispatch(f"attempt:{request.slot}")
        self._state.attempts += 1
        result = executor.run(request)
        payload = {
            "slot": request.slot,
            "attempt": request.attempt,
            "ok": result.ok,
            "breach": result.breach,
            "stopped_confirmed": result.stopped_confirmed,
            "returncode": result.returncode,
            "duration_seconds": round(result.duration_seconds, 3),
            "artifact_fingerprint": result.artifact_fingerprint,
        }
        if result.breach:
            # stop through the runtime, confirm exit, discard partial output
            self._log("container_breach", payload)
        self._log("attempt_result", payload)
        return result

    def confirm_stop(self, reason: str) -> None:
        """Stop experimental work (integrity failure, containment breach, deadline)."""
        self._state.stop_reason = reason
        self._log("irc_stop", {"reason": reason})

    def close_run(self, executor: LocalExecutor | None = None, reason: str = "close") -> list[str]:
        """Terminate remaining containers, clean disposable resources, seal."""
        removed: list[str] = []
        if executor is not None:
            removed = executor.cleanup_run(self._state.run_id)
        self._state.closed = True
        self._log("run_closed", {"reason": reason, "cleanup": removed})
        return removed
