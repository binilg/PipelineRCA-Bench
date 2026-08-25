"""The tool surface exposed to an Agent during diagnosis.

A ToolBelt is constructed from an already-resolved {path: content} dict
(loader.AgentTask.context) -- never from a filesystem handle into the
scenario directory. That's a deliberate design constraint: there is no
method on this class that can read manifest.yaml or anything outside
context/, because the object it wraps was never given access to either.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class LogMatch:
    file: str
    line_no: int
    line: str


class ToolBelt:
    def __init__(self, context: dict[str, str]):
        self._context = context

    def list_files(self) -> list[str]:
        """All files available as evidence for this scenario."""
        return sorted(self._context.keys())

    def read_file(self, relative_path: str) -> str:
        if relative_path not in self._context:
            raise FileNotFoundError(
                f"{relative_path!r} is not part of this scenario's context. "
                f"Available files: {self.list_files()}"
            )
        return self._context[relative_path]

    def search_logs(self, pattern: str, relative_path: str | None = None) -> list[LogMatch]:
        """grep-like search across one file or all files. `pattern` is a
        regular expression."""
        regex = re.compile(pattern)
        targets = [relative_path] if relative_path else self.list_files()
        matches: list[LogMatch] = []
        for path in targets:
            content = self._context.get(path)
            if content is None:
                continue
            for i, line in enumerate(content.splitlines(), start=1):
                if regex.search(line):
                    matches.append(LogMatch(file=path, line_no=i, line=line))
        return matches

    def profile_data(self, relative_path: str) -> dict:
        """Lightweight profile of a CSV file: columns, row count, and a
        numeric summary per column. Uses pandas if available; falls back
        to a naive stdlib csv parse otherwise so the tool works even in a
        minimal environment."""
        content = self.read_file(relative_path)
        try:
            import io
            import pandas as pd

            df = pd.read_csv(io.StringIO(content), comment="#")
            summary = {
                "columns": list(df.columns),
                "row_count": len(df),
            }
            numeric = df.select_dtypes("number")
            summary["numeric_summary"] = {
                col: {
                    "min": float(numeric[col].min()),
                    "max": float(numeric[col].max()),
                    "mean": float(numeric[col].mean()),
                }
                for col in numeric.columns
            }
            return summary
        except ImportError:
            return self._naive_csv_profile(content)

    @staticmethod
    def _naive_csv_profile(content: str) -> dict:
        import csv
        import io

        rows = [r for r in csv.reader(io.StringIO(content)) if r and not r[0].startswith("#")]
        if not rows:
            return {"columns": [], "row_count": 0, "numeric_summary": {}}
        header, data_rows = rows[0], rows[1:]
        numeric_summary: dict[str, dict] = {}
        for idx, col in enumerate(header):
            values = []
            for row in data_rows:
                if idx < len(row):
                    try:
                        values.append(float(row[idx]))
                    except ValueError:
                        pass
            if values:
                numeric_summary[col] = {
                    "min": min(values), "max": max(values), "mean": sum(values) / len(values),
                }
        return {"columns": header, "row_count": len(data_rows), "numeric_summary": numeric_summary}
