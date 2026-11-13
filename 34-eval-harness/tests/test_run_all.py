from pathlib import Path

from eval_harness.results import ResultRow, ResultsFile
from eval_harness.run_all import join_results


def _write(path: Path, *rows: ResultRow) -> None:
    path.write_text(ResultsFile(tasks=list(rows), summary="x").model_dump_json())


def _row(task_id: str, passed: bool) -> ResultRow:
    return ResultRow(id=task_id, title=task_id, passed=passed, score=1.0 if passed else 0.0, evidence="e")


def test_joins_rows_of_every_suite_in_order(tmp_path: Path) -> None:
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    _write(a, _row("keystone:seat35.t1", True))
    _write(b, _row("keystone:seat31.t1", True), _row("keystone:seat31.t2", False))

    writer = join_results(
        [(Path("suites/seat35"), a), (Path("suites/seat31"), b)], "keystone", tmp_path / "out.json"
    )

    out = ResultsFile.model_validate_json((tmp_path / "out.json").read_text())
    assert [r.id for r in out.tasks] == ["keystone:seat35.t1", "keystone:seat31.t1", "keystone:seat31.t2"]
    assert out.summary == "keystone: 2/3 tasks passed"
    assert len(writer.rows) == 3


def test_suite_without_results_becomes_one_infrastructure_row(tmp_path: Path) -> None:
    a = tmp_path / "a.json"
    _write(a, _row("suryodaya:seat35.t1", True))

    join_results(
        [(Path("suites/seat35"), a), (Path("suites/seat31"), tmp_path / "missing.json")],
        "suryodaya",
        tmp_path / "out.json",
    )

    out = ResultsFile.model_validate_json((tmp_path / "out.json").read_text())
    last = out.tasks[-1]
    assert last.id == "suryodaya:seat31"
    assert not last.passed
    assert last.evidence.startswith("infrastructure:")
    assert out.summary == "suryodaya: 1/2 tasks passed"
