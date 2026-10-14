"""SQLite state storage, relational collection queries, and mapping compatibility."""
import copy
import json
import math
import threading
from collections.abc import MutableMapping
from pathlib import Path

from sqlalchemy import Column, JSON, delete
from sqlmodel import Field, Session, SQLModel, create_engine, select

DEFAULT_STATE = {"scouted_projects": [], "analyses": [], "launches": [], "moltbook_posts": [], "last_scout": None, "last_analysis": None, "demo_mode": False}

class Record(SQLModel):
    id: int | None = Field(default=None, primary_key=True)
    position: int = Field(index=True)
    project_id: str | None = Field(default=None, index=True)
    project_name: str | None = Field(default=None, index=True)
    overall_score: float | None = Field(default=None, index=True)
    payload: dict = Field(sa_type=JSON, nullable=False)

class ProjectRecord(Record, table=True):
    __tablename__ = "projects"

class AnalysisRecord(Record, table=True):
    __tablename__ = "analyses"

class LaunchRecord(Record, table=True):
    __tablename__ = "launches"

class PostRecord(Record, table=True):
    __tablename__ = "moltbook_posts"

class Metadata(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value: object = Field(sa_column=Column(JSON, nullable=True))

TABLES = {"scouted_projects": ProjectRecord, "analyses": AnalysisRecord, "launches": LaunchRecord, "moltbook_posts": PostRecord}

class StateStore:
    def __init__(self, database_path, legacy_path=None):
        path = Path(database_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine("sqlite:///" + str(path), connect_args={"check_same_thread": False, "timeout": 30})
        self.lock = threading.RLock()
        SQLModel.metadata.create_all(self.engine)
        with Session(self.engine) as session:
            initialized = session.get(Metadata, "_initialized") is not None
        if not initialized:
            state = copy.deepcopy(DEFAULT_STATE)
            if legacy_path and Path(legacy_path).exists():
                with open(legacy_path, encoding="utf-8") as source:
                    legacy = json.load(source)
                if not isinstance(legacy, dict):
                    raise ValueError("Legacy state must be an object")
                # Older versions could persist fictional fixtures. Preserve the
                # source file, but never migrate a demo snapshot into live data.
                if not legacy.get("demo_mode", False):
                    state.update(legacy)
            self.save_state(state)

    def load_state(self, defaults=None):
        with self.lock, Session(self.engine) as session:
            state = copy.deepcopy(DEFAULT_STATE if defaults is None else defaults)
            for key, table in TABLES.items():
                state[key] = [copy.deepcopy(row.payload) for row in session.exec(select(table).order_by(table.position)).all()]
            for item in session.exec(select(Metadata)).all():
                if item.key != "_initialized":
                    state[item.key] = copy.deepcopy(item.value)
            return state

    def save_state(self, state):
        # Validate and serialize before deleting any rows; commit all tables together.
        serialized = json.loads(json.dumps(dict(state), allow_nan=False))
        for key in TABLES:
            values = serialized.get(key, [])
            if not isinstance(values, list) or any(not isinstance(v, dict) for v in values):
                raise ValueError(f"{key} must be a list of objects")
        with self.lock, Session(self.engine) as session:
            for key, table in TABLES.items():
                session.exec(delete(table))
                for position, payload in enumerate(serialized.get(key, [])):
                    project_id = payload.get("project_id", payload.get("id"))
                    score = payload.get("overall_score")
                    if score is not None and not math.isfinite(float(score)):
                        raise ValueError("overall_score must be finite")
                    session.add(table(position=position, project_id=str(project_id) if project_id is not None else None, project_name=payload.get("project_name", payload.get("title")), overall_score=float(score) if score is not None else None, payload=payload))
            session.exec(delete(Metadata))
            for key, value in serialized.items():
                if key not in TABLES and key != "_initialized":
                    session.add(Metadata(key=key, value=value))
            session.add(Metadata(key="_initialized", value=True))
            session.commit()

    def query(self, collection, *, project_name=None, min_score=None, limit=None):
        table = TABLES[collection]
        statement = select(table)
        if project_name is not None:
            statement = statement.where(table.project_name == project_name)
        if min_score is not None:
            statement = statement.where(table.overall_score >= min_score)
        statement = statement.order_by(table.position)
        if limit is not None:
            if limit < 0:
                raise ValueError("limit must be nonnegative")
            statement = statement.limit(limit)
        with self.lock, Session(self.engine) as session:
            return [copy.deepcopy(row.payload) for row in session.exec(statement).all()]

    def close(self):
        self.engine.dispose()

class PersistentList(list):
    """Route-compatible collection; every list mutation persists immediately."""
    def __init__(self, values, state, key):
        super().__init__(values)
        self._state, self._key = state, key
    def _change(self, method, *args, **kwargs):
        with self._state.store.lock:
            values = self._state.store.load_state()[self._key]
            result = getattr(values, method)(*args, **kwargs)
            self._state[self._key] = values
            list.clear(self)
            list.extend(self, values)
            return result
    def append(self, item): return self._change("append", item)
    def extend(self, items): return self._change("extend", items)
    def insert(self, index, item): return self._change("insert", index, item)
    def pop(self, index=-1): return self._change("pop", index)
    def remove(self, item): return self._change("remove", item)
    def clear(self): return self._change("clear")
    def reverse(self): return self._change("reverse")
    def sort(self, *args, **kwargs): return self._change("sort", *args, **kwargs)
    def __setitem__(self, key, value): return self._change("__setitem__", key, value)
    def __delitem__(self, key): return self._change("__delitem__", key)
    def __iadd__(self, values):
        self.extend(values)
        return self
    def __imul__(self, count):
        self._change("__imul__", count)
        return self
    def __deepcopy__(self, memo): return copy.deepcopy(list(self), memo)

class DatabaseState(MutableMapping):
    """Read-through state: SQLite is the authoritative store, not a cached dict."""
    def __init__(self, store): self.store = store
    def __getitem__(self, key):
        value = self.store.load_state()[key]
        return PersistentList(value, self, key) if key in TABLES else value
    def __setitem__(self, key, value):
        with self.store.lock:
            state = self.store.load_state()
            state[key] = value
            self.store.save_state(state)
    def __delitem__(self, key):
        if key in DEFAULT_STATE:
            self[key] = copy.deepcopy(DEFAULT_STATE[key])
        else:
            with self.store.lock:
                state = self.store.load_state()
                del state[key]
                self.store.save_state(state)
    def __iter__(self): return iter(self.store.load_state())
    def __len__(self): return len(self.store.load_state())
    def snapshot(self): return self.store.load_state()
    def update(self, *args, **kwargs):
        with self.store.lock:
            state = self.store.load_state()
            state.update(*args, **kwargs)
            self.store.save_state(state)
    def __deepcopy__(self, memo): return copy.deepcopy(self.snapshot(), memo)
