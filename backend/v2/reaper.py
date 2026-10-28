"""Retention entry point; worker/re-enqueue orchestration is deferred to Task 5."""


def prune_source_events(db):
    with db.cursor() as cur:
        cur.execute('select prune_source_events() as removed')
        row = cur.fetchone()
        return row['removed'] if isinstance(row, dict) else row[0]
