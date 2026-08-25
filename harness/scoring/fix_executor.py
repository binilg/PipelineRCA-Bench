"""Sandboxed execution of a scenario's verify/test_fix.py.

Current state (honest limitation, matches the "Stub harness; replace mocks
with real hooks when the harness is built" comment in every scenario's
verify/test_fix.py): each verify file is self-contained -- it embeds both
a "broken" and a "fixed" reference implementation and asserts the fixed
one behaves correctly. None of them yet accept an agent's actual
diagnosis.fix_code as input.

So today, FixExecutor.run_verification() runs the scenario's verify file
as-is, in an isolated subprocess with a timeout, and reports whether the
verification script itself is sound (exits 0). That's a real, useful
check on its own -- it's the regression test that catches an author
breaking a scenario's verify file (like the s008 bug this project already
found and fixed). The integration point for scoring an agent's actual fix
is run_verification(); when scenarios are updated to parameterize their
verify files on external fix code (e.g. via an environment variable or a
CLI arg the test file reads), that plumbing goes here, sandboxing is
already in place.

Sandboxing today: separate subprocess, wall-clock timeout, captured
stdout/stderr, cwd set to a throwaway copy so nothing can write back into
the scenario directory. This is process-level isolation, not container-
level (no seccomp/gVisor/network denial) -- adequate for scenario
authoring and regression testing, not yet for running untrusted agent-
submitted code. Note that limitation before pointing this at arbitrary
externally-submitted fix code.

For is_false_positive scenarios (category 8, e.g. s021), verify/test_fix.py
is not a broken-vs-fixed fix check -- there's no fix, since nothing is
broken. It's a consistency check confirming the scenario's own claimed
ground truth is actually correct (e.g. s021 asserts each of its four
claimed exclusion reasons really does exclude the combination it claims
to). run_verification() runs it exactly the same way either way; the
distinction only matters when interpreting what a pass/fail means.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ..loader import Scenario
from ..agent import Diagnosis


@dataclass
class FixResult:
    passed: bool
    stdout: str
    stderr: str
    timed_out: bool
    error: str | None = None


class FixExecutor:
    def __init__(self, timeout_s: int = 15):
        self.timeout_s = timeout_s

    def run_verification(self, scenario: Scenario, diagnosis: Diagnosis) -> FixResult:
        verify_path = scenario.verify_path()
        if not verify_path.exists():
            return FixResult(passed=False, stdout="", stderr="", timed_out=False,
                              error=f"verification file not found: {verify_path}")

        with tempfile.TemporaryDirectory(prefix="pipelinerca_verify_") as tmp:
            tmp_path = Path(tmp)
            sandboxed_verify = tmp_path / verify_path.name
            shutil.copy2(verify_path, sandboxed_verify)

            # Integration point for scoring diagnosis.fix_code once verify
            # files accept external fix input -- e.g. write it alongside
            # the sandboxed copy and have the test import/apply it.
            del diagnosis  # unused until that plumbing exists; kept in the
                            # signature so callers don't need to change later

            try:
                proc = subprocess.run(
                    [sys.executable, str(sandboxed_verify)],
                    cwd=tmp_path,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_s,
                )
            except subprocess.TimeoutExpired as e:
                return FixResult(
                    passed=False,
                    stdout=e.stdout or "",
                    stderr=e.stderr or "",
                    timed_out=True,
                    error=f"verification timed out after {self.timeout_s}s",
                )

            return FixResult(
                passed=(proc.returncode == 0),
                stdout=proc.stdout,
                stderr=proc.stderr,
                timed_out=False,
                error=None if proc.returncode == 0 else f"exited with code {proc.returncode}",
            )
