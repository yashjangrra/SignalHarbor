import copy
import json
import pytest
from sqlmodel import Session, select
from src.database import AnalysisRecord, DatabaseState, StateStore


def test_restart_queries_and_relational_rows(tmp_path):
    path = tmp_path / "state.db"
    store = StateStore(path)
    state = DatabaseState(store)
    state["analyses"].append({"project_name": "Strong", "overall_score": 85, "scores": {"market": 90}})
    state["analyses"].append({"project_name": "Weak", "overall_score": 30})
    state["last_scout"] = "2026-10-14"
    store.close()
    restarted = StateStore(path)
    assert restarted.load_state()["last_scout"] == "2026-10-14"
    assert restarted.query("analyses", min_score=70)[0]["project_name"] == "Strong"
    assert restarted.query("analyses", project_name="Weak", limit=1)[0]["overall_score"] == 30
    with Session(restarted.engine) as session:
        assert len(session.exec(select(AnalysisRecord)).all()) == 2


def test_legacy_migration_runs_once(tmp_path):
    legacy = tmp_path / "state.json"
    legacy.write_text(json.dumps({"scouted_projects": [{"id": "old"}]}))
    store = StateStore(tmp_path / "state.db", legacy)
    assert store.load_state()["scouted_projects"] == [{"id": "old"}]
    legacy.write_text(json.dumps({"scouted_projects": [{"id": "changed"}]}))
    store.close()
    assert StateStore(tmp_path / "state.db", legacy).load_state()["scouted_projects"] == [{"id": "old"}]


def test_bad_save_is_atomic_and_demo_snapshot_is_isolated(tmp_path):
    store = StateStore(tmp_path / "state.db")
    state = DatabaseState(store)
    state["scouted_projects"] = [{"id": "live"}]
    demo = copy.deepcopy(state)
    demo["scouted_projects"][0]["id"] = "demo"
    assert state["scouted_projects"][0]["id"] == "live"
    invalid = store.load_state()
    invalid["analyses"] = [{"overall_score": "invalid"}]
    with pytest.raises(ValueError):
        store.save_state(invalid)
    assert store.load_state()["scouted_projects"] == [{"id": "live"}]


def test_collection_updates_and_stale_append_do_not_lose_rows(tmp_path):
    state = DatabaseState(StateStore(tmp_path / "state.db"))
    first, second = state["launches"], state["launches"]
    first.append({"id": "one"})
    second.append({"id": "two"})
    assert [v["id"] for v in state["launches"]] == ["one", "two"]
    state["launches"][0] = {"id": "replacement"}
    assert state["launches"].pop()["id"] == "two"
    assert state["launches"] == [{"id": "replacement"}]
    state.update(last_scout="now", last_analysis="later")
    assert state.snapshot()["last_analysis"] == "later"


def test_legacy_demo_never_becomes_live_data(tmp_path):
    legacy = tmp_path / "state.json"
    content = json.dumps({"demo_mode": True, "scouted_projects": [{"id": "fictional"}]})
    legacy.write_text(content)
    store = StateStore(tmp_path / "state.db", legacy)
    assert store.load_state()["scouted_projects"] == []
    assert store.load_state()["demo_mode"] is False
    assert legacy.read_text() == content
    store.close()


@pytest.mark.parametrize("score", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_indexed_score_is_rejected_atomically(tmp_path, score):
    store = StateStore(tmp_path / "state.db")
    state = store.load_state()
    state["analyses"] = [{"overall_score": score}]
    with pytest.raises(ValueError, match="finite"):
        store.save_state(state)
    assert store.load_state()["analyses"] == []
    store.close()


def test_commit_failure_rolls_back_all_tables_and_metadata(tmp_path, monkeypatch):
    store = StateStore(tmp_path / 'rollback.db')
    state = store.load_state()
    state.update(scouted_projects=[{'id': 'old'}], analyses=[{'project_name': 'old', 'overall_score': 80}], last_scout='before')
    store.save_state(state)
    replacement = copy.deepcopy(state)
    replacement.update(scouted_projects=[{'id': 'new'}], analyses=[], last_scout='after')
    with monkeypatch.context() as patch:
        def fail_commit(self):
            self.flush()
            raise RuntimeError('simulated commit failure')
        patch.setattr(Session, 'commit', fail_commit)
        with pytest.raises(RuntimeError, match='simulated commit failure'):
            store.save_state(replacement)
    assert store.load_state() == state
    store.close()
    reopened = StateStore(tmp_path / 'rollback.db')
    try:
        assert reopened.load_state() == state
    finally:
        reopened.close()


@pytest.mark.parametrize('contents', ['{broken', '{"scouted_projects": "bad"}', '{"analyses": [{"overall_score": "bad"}]}'])
def test_malformed_legacy_is_preserved_and_can_be_repaired(tmp_path, contents):
    legacy = tmp_path / 'state.json'
    legacy.write_text(contents)
    with pytest.raises((ValueError, TypeError)):
        StateStore(tmp_path / 'legacy.db', legacy)
    assert legacy.read_text() == contents
    legacy.write_text(json.dumps({'scouted_projects': [{'id': 'repaired'}]}))
    store = StateStore(tmp_path / 'legacy.db', legacy)
    try:
        assert store.load_state()['scouted_projects'] == [{'id': 'repaired'}]
    finally:
        store.close()
