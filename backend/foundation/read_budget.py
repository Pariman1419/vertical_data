"""Engine-neutral spike budget. No SQL, credentials, network or live adapter.

Caller and connector must enforce server/driver timeouts too. Limiting returned
rows does not prove bounded physical reads or an acceptable query plan.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from itertools import islice
import threading


class BudgetError(ValueError):
    pass


@dataclass(frozen=True)
class ReadBudget:
    allowed_tables: frozenset[tuple[str, str]]
    sample_rows: int = 100
    batch_size: int = 25
    timeout_seconds: int = 15
    catalog_only: bool = False

    def __post_init__(self):
        tables = self.allowed_tables
        if not isinstance(tables, frozenset) or len(tables) > 10 or (not tables and not self.catalog_only):
            raise BudgetError("Explicit bounded table scope or catalog-only mode required")
        for pair in tables:
            if not isinstance(pair, tuple) or len(pair) != 2 or any(
                not isinstance(v, str) or not v or len(v) > 128
                or any(ord(c) < 32 for c in v) for v in pair
            ):
                raise BudgetError("Invalid schema/table allowlist")
        for value, maximum in ((self.sample_rows, 1000),
                               (self.batch_size, 1000),
                               (self.timeout_seconds, 60)):
            if type(value) is not int or not 1 <= value <= maximum:
                raise BudgetError("Read budget outside permitted limits")
        if self.batch_size > self.sample_rows:
            raise BudgetError("Batch size must not exceed sample row limit")

    def check_table(self, schema, table):
        if (schema, table) not in self.allowed_tables:
            raise BudgetError("Table not authorized")


class ReadGate:
    """One concurrent spike operation per shared instance; fail instead of queue.

    NOT a distributed lock. A live supervisor must own/share this gate, or use
    a durable cross-process admission lock before enabling multiple workers.
    """
    def __init__(self):
        self._lock = threading.Lock()

    @contextmanager
    def operation(self):
        if not self._lock.acquire(blocking=False):
            raise BudgetError("Source read already active")
        try:
            yield
        finally:
            self._lock.release()


def fixture_batches(budget, schema, table, rows, *, clock, started_at):
    """Bounded fixture consumer only, never a live database timeout mechanism.

    No lookahead beyond the sample cap. Exceptions propagate to the worker;
    callers must not mark partial samples as complete on timeout/failure.
    """
    budget.check_table(schema, table)
    iterator = iter(rows)
    remaining = budget.sample_rows
    while remaining:
        if clock() - started_at >= budget.timeout_seconds:
            raise BudgetError("Sample deadline exceeded")
        batch = list(islice(iterator, min(budget.batch_size, remaining)))
        if clock() - started_at >= budget.timeout_seconds:
            raise BudgetError("Sample deadline exceeded")
        if not batch:
            return
        remaining -= len(batch)
        yield batch
