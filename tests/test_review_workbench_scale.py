from __future__ import annotations

from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
import sqlite3
import time

from openpyxl import Workbook

from material_matcher.services.review_workbench_service import ReviewWorkbenchService


SCHEMA = """
CREATE TABLE tasks(task_id TEXT PRIMARY KEY);
CREATE TABLE match_items(
 task_id TEXT NOT NULL, source_row_id TEXT NOT NULL, source_row_number INTEGER,
 source_id TEXT NOT NULL, source_payload TEXT NOT NULL,
 original_status TEXT NOT NULL, current_status TEXT NOT NULL,
 top1_group_code TEXT, top1_score REAL NOT NULL, second_score REAL NOT NULL,
 score_gap REAL NOT NULL, critical_conflict INTEGER NOT NULL, final_group_code TEXT,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 PRIMARY KEY(task_id,source_row_id)
);
CREATE INDEX idx_match_items_task_status_score ON match_items(task_id,current_status,top1_score);
CREATE TABLE match_candidates(
 task_id TEXT NOT NULL, source_row_id TEXT NOT NULL, rank INTEGER NOT NULL,
 target_row_number INTEGER, target_group_code TEXT NOT NULL, target_payload TEXT NOT NULL,
 score REAL NOT NULL, field_scores TEXT NOT NULL, critical_conflict INTEGER NOT NULL,
 PRIMARY KEY(task_id,source_row_id,rank)
);
CREATE TABLE reviews(
 review_id TEXT PRIMARY KEY,task_id TEXT NOT NULL,source_row_id TEXT NOT NULL,
 original_status TEXT NOT NULL,selected_group_code TEXT,action TEXT NOT NULL,
 operator TEXT NOT NULL,comment TEXT NOT NULL,created_at TEXT NOT NULL
);
CREATE TABLE match_operation_logs(
 operation_id TEXT PRIMARY KEY,task_id TEXT NOT NULL,source_row_id TEXT NOT NULL,
 source_row_number INTEGER,operator TEXT NOT NULL,operated_at TEXT NOT NULL,
 operation_type TEXT NOT NULL,before_status TEXT NOT NULL,after_status TEXT NOT NULL,
 previous_group_code TEXT,selected_group_code TEXT,previous_target_row_number INTEGER,
 target_row_number INTEGER,source TEXT NOT NULL,comment TEXT NOT NULL DEFAULT ''
);
CREATE TABLE audit_events(
 event_id TEXT PRIMARY KEY,entity_type TEXT NOT NULL,entity_id TEXT NOT NULL,
 action TEXT NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL
);
"""


class Repo:
    def __init__(self, path: Path):
        self.path = path
        self.connect_count = 0
        self.trace_sql = False
        self.statements: list[str] = []
        with sqlite3.connect(path) as c:
            c.executescript(SCHEMA)
            c.execute("INSERT INTO tasks VALUES('t1')")

    @contextmanager
    def connect(self):
        self.connect_count += 1
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        if self.trace_sql:
            c.set_trace_callback(self.statements.append)
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback(); raise
        finally:
            c.close()


def seed(repo: Repo, n: int, statuses=("REVIEW",), candidates=2):
    now = "2026-09-17T14:00:00+08:00"
    with sqlite3.connect(repo.path) as c:
        c.executemany(
            "INSERT INTO match_items VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    "t1", str(i), i + 2, f"SRC-{i:06d}", '{"name":"material-%d"}' % i,
                    statuses[i % len(statuses)], statuses[i % len(statuses)], f"G{i:06d}-1",
                    float(i % 101), float(max((i % 101)-5, 0)), 5.0, 0,
                    f"G{i:06d}-1" if statuses[i % len(statuses)] == "MATCHED" else None,
                    now, f"{now}-{i:06d}"
                )
                for i in range(n)
            ],
        )
        rows=[]
        for i in range(n):
            for rank in range(1, candidates+1):
                rows.append(("t1", str(i), rank, i*10+rank, f"G{i:06d}-{rank}", '{"desc":"target"}', 90-rank, '{}', 0))
        c.executemany("INSERT INTO match_candidates VALUES(?,?,?,?,?,?,?,?,?)", rows)


def service(tmp_path, n=0, statuses=("REVIEW",), candidates=2):
    repo=Repo(tmp_path / "db.sqlite")
    if n: seed(repo,n,statuses,candidates)
    return repo, ReviewWorkbenchService(repo)


def test_status_filters_paging_and_candidates(tmp_path):
    statuses=("MATCHED","REVIEW","CONFIRMED","UNMATCHED")
    repo, svc=service(tmp_path, 40, statuses, 5)
    for status in ("ALL",*statuses):
        result=svc.list_items("t1",status=status,page=1,page_size=7,include_candidates=5)
        assert result["total"] == (40 if status=="ALL" else 10)
        assert len(result["items"]) == 7
        assert all("version" in row for row in result["items"])
        assert all(len(row["candidates"]) == 5 for row in result["items"])
    search=svc.list_items("t1",status="ALL",q="SRC-000013",page_size=50)
    assert search["total"] == 1
    assert search["items"][0]["source_row_id"] == "13"


def test_optimistic_conflict_prevents_silent_overwrite(tmp_path):
    repo, svc=service(tmp_path,1,("REVIEW",),2)
    row=svc.list_items("t1",status="REVIEW",include_candidates=2)["items"][0]
    version=row["version"]
    first=svc.submit_decisions("t1", [{"source_row_id":"0","target_rank":1,"expected_version":version}], operator="B")
    assert first["success"] == 1
    second=svc.submit_decisions("t1", [{"source_row_id":"0","target_rank":2,"expected_version":version}], operator="A")
    assert second["conflicts"] == 1
    assert second["details"][0]["code"] == "VERSION_CONFLICT"
    with sqlite3.connect(repo.path) as c:
        status,group=c.execute("SELECT current_status,final_group_code FROM match_items WHERE source_row_id='0'").fetchone()
    assert (status,group) == ("CONFIRMED","G000000-1")


def test_explicit_rematch_requires_current_version_and_is_audited(tmp_path):
    repo, svc=service(tmp_path,1,("REVIEW",),2)
    v=svc.list_items("t1",status="REVIEW")["items"][0]["version"]
    svc.submit_decisions("t1", [{"source_row_id":"0","target_rank":1,"expected_version":v}], operator="A")
    current=svc.list_items("t1",status="CONFIRMED")["items"][0]
    result=svc.submit_decisions("t1", [{"source_row_id":"0","target_rank":2,"expected_version":current["version"],"operation":"REMATCH"}], operator="A")
    assert result["success"] == 1
    with sqlite3.connect(repo.path) as c:
        row=c.execute("SELECT operation_type,operator,source,selected_group_code,target_row_number FROM match_operation_logs ORDER BY rowid DESC LIMIT 1").fetchone()
    assert row == ("REMATCH","A","WEB","G000000-2",2)


def test_filtered_10000_bulk_confirm_uses_one_transaction_connection(tmp_path):
    repo, svc=service(tmp_path,10_000,("REVIEW",),1)
    before=repo.connect_count
    result=svc.bulk_action(
        "t1",
        action="CONFIRM_TOP1",
        selection={"mode":"filter","filter":{"status":"REVIEW"}},
        operator="bulk-user",
    )
    assert result["success"] == 10_000
    assert result["conflicts"] == 0
    assert repo.connect_count - before == 1
    with sqlite3.connect(repo.path) as c:
        assert c.execute("SELECT COUNT(*) FROM match_items WHERE current_status='CONFIRMED'").fetchone()[0] == 10_000
        assert c.execute("SELECT COUNT(*) FROM match_operation_logs WHERE operator='bulk-user' AND source='WEB'").fetchone()[0] == 10_000
        assert c.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == 10_000


def test_100000_server_side_status_paging_search_and_select_all_contract(tmp_path):
    statuses=(
        ("MATCHED",) * 70
        + ("REVIEW",) * 12
        + ("CONFIRMED",) * 10
        + ("UNMATCHED",) * 8
    )
    expected={"MATCHED":70_000,"REVIEW":12_000,"CONFIRMED":10_000,"UNMATCHED":8_000}
    repo, svc=service(tmp_path,100_000,statuses,0)
    repo.trace_sql=True

    all_page_1=svc.list_items("t1",status="ALL",page=1,page_size=50)
    all_page_100=svc.list_items("t1",status="ALL",page=100,page_size=50)
    assert all_page_1["total"] == 100_000
    assert all_page_100["total"] == 100_000
    assert len(all_page_1["items"]) == 50
    assert len(all_page_100["items"]) == 50
    assert all_page_1["include_candidates"] == 0
    assert all("candidates" not in row for row in all_page_1["items"])

    for status,total in expected.items():
        page_1=svc.list_items("t1",status=status,page=1,page_size=50)
        page_100=svc.list_items("t1",status=status,page=100,page_size=50)
        assert page_1["total"] == total
        assert page_100["total"] == total
        assert len(page_1["items"]) == 50
        assert len(page_100["items"]) == 50
        assert all(row["current_status"] == status for row in page_1["items"])
        assert svc.selection_count("t1", {"mode":"filter","filter":{"status":status}})["count"] == total

    source_id=svc.list_items("t1",status="ALL",q="SRC-099970",page=1,page_size=50)
    source_payload=svc.list_items("t1",status="ALL",q="material-99970",page=1,page_size=50)
    group_code=svc.list_items("t1",status="ALL",q="G099970-1",page=1,page_size=50)
    review_search=svc.list_items("t1",status="REVIEW",q="SRC-099970",page=1,page_size=50)
    matched_search=svc.list_items("t1",status="MATCHED",q="SRC-099970",page=1,page_size=50)
    for result in (source_id,source_payload,group_code,review_search):
        assert result["total"] == 1
        assert result["items"][0]["source_row_id"] == "99970"
    assert matched_search["total"] == 0
    assert matched_search["items"] == []

    start=time.monotonic()
    page=svc.list_items("t1",status="REVIEW",first_score_min=60,first_score_max=80,page=3,page_size=100)
    preview=svc.selection_count("t1", {"mode":"filter","filter":{"status":"REVIEW","first_score_min":60,"first_score_max":80}})
    elapsed=time.monotonic()-start
    assert page["total"] == preview["count"]
    assert 0 < preview["count"] < 100_000
    assert len(page["items"]) == 100
    assert elapsed < 10.0

    normalized_sql=[" ".join(statement.split()) for statement in repo.statements]
    assert any(
        "FROM match_items m WHERE" in statement
        and "LIMIT 50 OFFSET 4950" in statement
        for statement in normalized_sql
    )


def workbook_for(task_id: str, rows: list[tuple[str,str]]) -> BytesIO:
    wb=Workbook(); ws=wb.active; ws.title="人工匹配"
    ws.append(["人工选择","__task_id","__source_row_id"])
    for source_row_id,choice in rows: ws.append([choice,task_id,source_row_id])
    out=BytesIO(); wb.save(out); out.seek(0); return out


def test_excel_merge_blank_idempotent_conflict_and_no_overwrite(tmp_path):
    repo, svc=service(tmp_path,2,("REVIEW",),2)
    first=svc.import_workbook("t1", workbook_for("t1", [("0","候选1"),("1","")]), operator="excel-a", filename="a.xlsx")
    assert first["success_count"] == 1 and first["skipped_count"] == 1
    same=svc.import_workbook("t1", workbook_for("t1", [("0","候选1")]), operator="excel-b", filename="b.xlsx")
    assert same["success_count"] == 0 and same["skipped_count"] == 1
    conflict=svc.import_workbook("t1", workbook_for("t1", [("0","候选2")]), operator="excel-c", filename="c.xlsx")
    assert conflict["conflict_count"] == 1 and conflict["success_count"] == 0
    with sqlite3.connect(repo.path) as c:
        assert c.execute("SELECT final_group_code FROM match_items WHERE source_row_id='0'").fetchone()[0] == "G000000-1"
        log=c.execute("SELECT operator,source,operation_type FROM match_operation_logs WHERE source_row_id='0' ORDER BY rowid LIMIT 1").fetchone()
    assert log == ("excel-a","EXCEL","IMPORT_MATCH")


def test_excel_conflicting_duplicate_does_not_apply_either_choice(tmp_path):
    repo, svc=service(tmp_path,1,("REVIEW",),2)
    result=svc.import_workbook("t1", workbook_for("t1", [("0","候选1"),("0","候选2")]), operator="excel")
    assert result["conflict_count"] == 1
    assert result["success_count"] == 0
    with sqlite3.connect(repo.path) as c:
        assert c.execute("SELECT current_status FROM match_items WHERE source_row_id='0'").fetchone()[0] == "REVIEW"


def test_cancel_unmatched_and_restore_algorithm_are_traceable(tmp_path):
    repo, svc=service(tmp_path,1,("REVIEW",),1)
    v=svc.list_items("t1",status="REVIEW")["items"][0]["version"]
    svc.submit_decisions("t1", [{"source_row_id":"0","unmatched":True,"expected_version":v}], operator="u")
    cancel=svc.bulk_action("t1",action="CANCEL_UNMATCHED",selection={"mode":"filter","filter":{"status":"UNMATCHED"}},operator="u")
    assert cancel["success"] == 1
    with sqlite3.connect(repo.path) as c:
        assert c.execute("SELECT current_status FROM match_items WHERE source_row_id='0'").fetchone()[0] == "REVIEW"
        actions=[r[0] for r in c.execute("SELECT operation_type FROM match_operation_logs ORDER BY rowid").fetchall()]
    assert actions == ["MARK_UNMATCHED","CANCEL_UNMATCHED"]
