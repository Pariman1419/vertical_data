import unittest
from backend.foundation.read_budget import BudgetError, ReadBudget, ReadGate, fixture_batches


class ReadBudgetTests(unittest.TestCase):
    def budget(self, **options):
        return ReadBudget(frozenset({("MES", "PROCESS_EVENT")}), **options)

    def test_explicit_allowlist_and_limits(self):
        for kwargs in ({"sample_rows": 0}, {"sample_rows": 1001},
                       {"sample_rows": True}, {"batch_size": 101},
                       {"timeout_seconds": 61}):
            with self.assertRaises(BudgetError):
                self.budget(**kwargs)
        with self.assertRaises(BudgetError):
            ReadBudget(frozenset())

    def test_reject_table_before_consuming(self):
        def forbidden():
            self.fail("Unauthorized fixture consumed")
            yield {}
        with self.assertRaises(BudgetError):
            list(fixture_batches(self.budget(), "OTHER", "TABLE", forbidden(),
                                 clock=lambda: 0, started_at=0))

    def test_cap_no_lookahead_and_batches(self):
        consumed = []
        def rows():
            for i in range(100):
                consumed.append(i)
                yield {"event": i}
        result = list(fixture_batches(self.budget(sample_rows=7, batch_size=3),
                                     "MES", "PROCESS_EVENT", rows(),
                                     clock=lambda: 0, started_at=0))
        self.assertEqual([len(b) for b in result], [3, 3, 1])
        self.assertEqual(consumed, list(range(7)))

    def test_timeout_before_and_after_read(self):
        for values in ([15], [0, 15]):
            times = iter(values)
            with self.assertRaises(BudgetError):
                list(fixture_batches(self.budget(), "MES", "PROCESS_EVENT", [{}],
                                     clock=lambda: next(times), started_at=0))

    def test_empty_and_short_samples(self):
        for rows in ([], [{"event": 1}]):
            result = list(fixture_batches(self.budget(), "MES", "PROCESS_EVENT", rows,
                                         clock=lambda: 0, started_at=0))
            self.assertEqual(sum(map(len, result)), len(rows))

    def test_lock_release_after_failure(self):
        gate = ReadGate()
        with self.assertRaises(RuntimeError):
            with gate.operation():
                with self.assertRaises(BudgetError):
                    with gate.operation():
                        pass
                raise RuntimeError("fixture failure")
        with gate.operation():
            pass

    def test_read_failure_propagates(self):
        def broken():
            raise RuntimeError("fixture read failed")
            yield {}
        with self.assertRaises(RuntimeError):
            list(fixture_batches(self.budget(), "MES", "PROCESS_EVENT", broken(),
                                 clock=lambda: 0, started_at=0))


if __name__ == "__main__":
    unittest.main()
