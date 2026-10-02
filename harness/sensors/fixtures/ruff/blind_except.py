# expect: BLE001
def f(conn):
    try:
        conn.execute("SELECT 1")
    except Exception:
        return None
