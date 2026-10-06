import os
import time
import unittest
import uuid
import xml.etree.ElementTree as ET

from unittest_parallel.main import ParallelTextTestResult


class JUnitResult(ParallelTextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._cases: list[ET.Element] = []
        self._started = 0.0

    def startTest(self, test):
        self._started = time.perf_counter()
        super().startTest(test)

    def _record(self, test, outcome=None, text=""):
        case = ET.Element("testcase", classname=f"{type(test).__module__}.{type(test).__qualname__}",
                          name=test._testMethodName if hasattr(test, "_testMethodName") else str(test),
                          time=f"{time.perf_counter() - self._started:.3f}")
        if outcome:
            ET.SubElement(case, outcome, message=text.splitlines()[0][:200] if text else "").text = text
        self._cases.append(case)

    def addSuccess(self, test):
        super().addSuccess(test)
        self._record(test)

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._record(test, "failure", self.failures[-1][1])

    def addError(self, test, err):
        super().addError(test, err)
        self._record(test, "error", self.errors[-1][1])

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self._record(test, "skipped", reason)

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self._record(test)

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self._record(test, "failure", "unexpected success")

    def printErrors(self):
        unittest.TextTestResult.printErrors(self)

    def stopTestRun(self):
        super().stopTestRun()
        directory = os.environ.get("JUNIT_DIR")
        if not directory or not self._cases:
            return
        os.makedirs(directory, exist_ok=True)
        suite = ET.Element("testsuite", name="waypoint", tests=str(len(self._cases)),
                           failures=str(sum(1 for c in self._cases if c.find("failure") is not None)),
                           errors=str(sum(1 for c in self._cases if c.find("error") is not None)),
                           skipped=str(sum(1 for c in self._cases if c.find("skipped") is not None)))
        suite.extend(self._cases)
        ET.ElementTree(suite).write(os.path.join(directory, f"{uuid.uuid4().hex}.xml"), encoding="utf-8", xml_declaration=True)
