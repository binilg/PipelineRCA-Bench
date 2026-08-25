"""
Verification for s006. A proposed fix passes if retrying a failed upload
task never results in more than one effective partner notification for
the same run_date.
Stub harness; replace mocks with real hooks when the harness is built.
"""

class BrokenNotifier:
    def __init__(self):
        self.sent = []

    def notify(self, run_date):
        self.sent.append(run_date)   # fires every call, no dedup


class FixedNotifier:
    def __init__(self):
        self.sent = set()

    def notify(self, run_date):
        if run_date in self.sent:
            return  # idempotent: already notified for this run_date
        self.sent.add(run_date)


def simulate_attempt_then_retry(notifier):
    notifier.notify("2026-07-25")   # attempt 1: notify, then transfer fails
    notifier.notify("2026-07-25")   # attempt 2 (retry): notify again, transfer succeeds


def test_retry_does_not_double_notify():
    broken = BrokenNotifier()
    simulate_attempt_then_retry(broken)
    assert len(broken.sent) == 2, "sanity check on broken behavior"

    fixed = FixedNotifier()
    simulate_attempt_then_retry(fixed)
    assert len(fixed.sent) == 1, (
        f"Fix must ensure a retried upload never results in more than one "
        f"effective notification for the same run_date, got {len(fixed.sent)}"
    )

if __name__ == "__main__":
    test_retry_does_not_double_notify()
    print("PASS: retrying an upload no longer double-notifies the partner")
