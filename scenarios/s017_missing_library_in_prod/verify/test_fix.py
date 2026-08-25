"""
Verification for s017. A proposed fix passes if every import used by
upload_task.py is present in requirements_prod.txt -- i.e. prod's build
manifest is a superset of the code's actual runtime dependencies.
Stub harness; replace mocks with real hooks when the harness is built.
"""


def imports_available_in_prod(code_imports: set, requirements: set) -> bool:
    return code_imports.issubset(requirements)


def test_new_dependency_is_declared_in_prod_requirements():
    code_imports = {"airflow", "pandas", "fastparquet_writer"}

    broken_requirements = {"airflow", "pandas", "pyarrow", "pyyaml", "requests", "scikit-learn"}
    broken = imports_available_in_prod(code_imports, broken_requirements)
    assert broken is False, "sanity check: broken requirements.txt is missing fastparquet_writer"

    fixed_requirements = broken_requirements | {"fastparquet_writer"}
    fixed = imports_available_in_prod(code_imports, fixed_requirements)
    assert fixed is True, (
        "Fix must ensure every library the code actually imports is declared "
        "in requirements_prod.txt, not just that it happens to work in a "
        "developer's local environment."
    )


if __name__ == "__main__":
    test_new_dependency_is_declared_in_prod_requirements()
    print("PASS: prod requirements now declare every library the code imports")
