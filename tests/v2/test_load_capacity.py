from backend.v2 import db


def test_request_pool_leaves_control_capacity_for_ten_preview_users():
    pool, held = db._get_pool(), []
    try:
        for _ in range(10):
            held.append(pool.getconn())
        db.ping()  # login/readiness must still be able to borrow a short-lived connection
    finally:
        for conn in held:
            pool.putconn(conn)
