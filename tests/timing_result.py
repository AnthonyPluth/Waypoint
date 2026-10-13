import json
import os
import time
import uuid

from unittest_parallel.main import ParallelTextTestResult

from tests import shared


class TimingResult(ParallelTextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._timed: list[dict] = []
        self._started = 0.0
        self._phases: dict[str, float] = {}
        self._run_phases = dict(shared.PHASES)
        self._run_ended = shared.ENDED[0]

    def startTest(self, test):
        self._phases = dict(shared.PHASES)
        self._started = time.perf_counter()
        super().startTest(test)

    def stopTest(self, test):
        elapsed = time.perf_counter() - self._started
        super().stopTest(test)
        phases = {k: round(v - self._phases.get(k, 0.0), 4) for k, v in shared.PHASES.items()}
        self._timed.append({"module": type(test).__module__, "class": type(test).__qualname__,
                            "test": getattr(test, "_testMethodName", str(test)), "seconds": round(elapsed, 4),
                            "phases": {k: v for k, v in phases.items() if v}})

    def printErrors(self):
        super().printErrors()

    def stopTestRun(self):
        super().stopTestRun()
        directory = os.environ.get("TIMINGS_DIR")
        if not directory or not self._timed:
            return
        os.makedirs(directory, exist_ok=True)
        with open(os.path.join(directory, f"{uuid.uuid4().hex}.json"), "w") as f:
            phases = {k: round(v - self._run_phases.get(k, 0.0), 4) for k, v in shared.PHASES.items()}
            json.dump({"tests": self._timed, "phases": phases, "ended": shared.ENDED[0] - self._run_ended}, f)
