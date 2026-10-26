"""One-shot synthetic worker entrypoint, intentionally no server or connector."""
import argparse
import json
from .core import Principal, Registry, process_one


def main():
    parser = argparse.ArgumentParser(description="Synthetic-only foundation Worker (not ETL)")
    parser.add_argument("--registry", required=True, help="Disposable local SQLite test registry")
    args = parser.parse_args()
    registry = Registry(args.registry)
    job_id = process_one(registry)
    if job_id:
        status = registry.get_job(Principal("synthetic-worker", "Viewer"), job_id)
        print(json.dumps({"state": status["state"], "is_simulation": True,
                          "database_connected": False, "etl_published": False}))
    else:
        print("No queued synthetic probe.")


if __name__ == "__main__":
    main()
