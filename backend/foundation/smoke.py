"""Create temporary synthetic registry and run a separate Worker process."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from .core import Principal, Registry


def main():
    test_root = Path(__file__).resolve().parents[2] / ".foundation-test"
    test_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="smoke-", dir=test_root) as directory:
        path = Path(directory) / "registry.sqlite3"
        registry = Registry(path)
        admin = Principal("synthetic-admin", "Admin")
        registry.save_metadata(admin, "source-demo", 0, {
            "role": "Source", "engine": "synthetic", "host": "demo-source.invalid",
            "database": "DEMO_MES", "authentication": "none"})
        registry.save_bundle(admin, "bundle-demo", 0)
        job = registry.enqueue(admin, "request-demo", "source-demo/target-demo", "bundle-demo", 1)
        # API/UI-like caller exits its registry handle; Worker reopens durable state.
        subprocess.run([sys.executable, "-m", "backend.foundation.worker", "--registry", str(path)],
                       cwd=Path(__file__).resolve().parents[2], check=True)
        restarted = Registry(path)
        status = restarted.get_job(admin, job["id"])
        assert status["state"] == "synthetic_completed"
        assert status["database_connected"] is False and status["etl_published"] is False
        print(json.dumps({"environment": "synthetic-test", "state": status["state"],
                          "checkpoint": status["checkpoint"], "is_simulation": True,
                          "etl_published": False}))
        print("PASS: temporary registry bootstrap, metadata/revision, durable job and separate Worker. Not ETL.")


if __name__ == "__main__":
    main()
