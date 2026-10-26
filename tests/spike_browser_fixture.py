"""Browser integration fixture server. NEVER connects to a database.

Hard-coded dummy application password is for this test fixture only. Production
launcher always prompts privately and never imports this module.
"""
from http.server import ThreadingHTTPServer
from pathlib import Path
import tempfile
from backend.spike.server import handler_for, tls_context
from backend.spike.service import Service


class Cursor:
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def execute(self, sql, binds=None):
        assert sql.startswith(("SELECT ", "SET TRANSACTION READ ONLY"))
        if "SYS_CONTEXT" in sql: rows=[("synthetic-browser-user", "synthetic-browser-db")]
        elif "FETCH NEXT" in sql: rows=[("BIDPITDBA","DP_WIP_DATA","TABLE",1), ("QA_SCHEMA","LOT_QC","VIEW",2)][:binds["cap"]]
        elif "ALL_OBJECTS" in sql: rows=[("BIDPITDBA","DP_WIP_DATA","TABLE")]
        elif "ALL_TAB_COLUMNS" in sql: rows=[("EVENT_ID",1,"NUMBER","N"),("LOT_NO",2,"VARCHAR2","N"),("BATCH_NO",3,"VARCHAR2","Y"),("INPUT_QTY",4,"NUMBER","Y"),("PAYLOAD",5,"CLOB","Y")]
        elif "LEFT JOIN" in sql: rows=[("FK_FIXTURE","LOT_NO",1,"BIDPITDBA","DP_ASSY_LOT_PACK","LOT_NO")]
        elif "ALL_CONSTRAINTS" in sql: rows=[("PK_FIXTURE","P","EVENT_ID",1,None,None)]
        elif "ROWNUM" in sql: rows=[("000123",), ("<script>bad()</script>",)][:binds["row_cap"]]
        else: rows=[]
        self.rows=iter(rows)
    def fetchmany(self, n):
        result=[]
        for _ in range(n):
            try: result.append(next(self.rows))
            except StopIteration: break
        return result


class Connection:
    version="synthetic-browser-fixture-NOT-ORACLE"
    def cursor(self): return Cursor()
    def close(self): pass


def main():
    # The managed Windows test sandbox does not permit tempfile's default
    # AppContainer path; keep disposable synthetic TLS artifacts under the
    # repository's ignored test-artifact directory instead.
    temp_root = Path(__file__).resolve().parents[1] / ".foundation-test" / "tls-temp"
    temp_root.mkdir(parents=True, exist_ok=True)
    tempfile.tempdir = str(temp_root)
    service=Service("synthetic-app-passphrase", factory=lambda config,timeout: lambda: Connection())
    server=ThreadingHTTPServer(("127.0.0.1",8444), handler_for(service,"https://localhost:8444"))
    context,_=tls_context("synthetic-app-passphrase")
    server.socket=context.wrap_socket(server.socket,server_side=True)
    print("Synthetic HTTPS browser fixture ready; NO DATABASE",flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close(); service.close()


if __name__ == "__main__": main()
