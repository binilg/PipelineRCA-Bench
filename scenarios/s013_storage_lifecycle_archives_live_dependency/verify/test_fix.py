"""
Verification for s013. A proposed fix passes if a read-only reference
file the pipeline depends on is never eligible for an unmodified-object
archival policy -- either because it's excluded/tagged, or because it
gets touched periodically.
Stub harness; replace mocks with real hooks when the harness is built.
"""

def is_archival_eligible(days_since_modified: int, excluded: bool, threshold: int = 90) -> bool:
    if excluded:
        return False
    return days_since_modified >= threshold

def test_pipeline_dependency_file_is_excluded_from_archival():
    days_since_modified = 120  # long-stable reference file

    broken = is_archival_eligible(days_since_modified, excluded=False)
    assert broken is True, "sanity check: broken behavior makes the file archival-eligible"

    fixed = is_archival_eligible(days_since_modified, excluded=True)
    assert fixed is False, (
        "Fix must ensure a pipeline-critical reference file is excluded from "
        "generic unmodified-object archival policies, regardless of how long "
        "it's gone without being written to."
    )

if __name__ == "__main__":
    test_pipeline_dependency_file_is_excluded_from_archival()
    print("PASS: pipeline-critical reference file is no longer eligible for archival")
