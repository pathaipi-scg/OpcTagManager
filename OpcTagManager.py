from pathlib import Path
import subprocess
import sys

import pyodbc
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from config.config import (
    APP_HOST,
    APP_PORT,
    BROWSER_SCRIPT,
    KEPWARE_CONFIG_API_HOST,
    KEPWARE_CONFIG_API_PASSWORD,
    KEPWARE_CONFIG_API_PORT,
    KEPWARE_CONFIG_API_SCHEME,
    KEPWARE_CONFIG_API_TIMEOUT,
    KEPWARE_CONFIG_API_USER,
    KEPWARE_CONFIG_API_VERIFY_SSL,
    LOG_LEVEL,
    PRODUCTION_LINE,
    SQL_DB,
    SQL_DRIVER,
    SQL_PASS,
    SQL_SERVER,
    SQL_TRUST_SERVER_CERTIFICATE,
    SQL_USER,
)
from services.kepware_config_api import (
    KepwareConfigApi,
    KepwareConfigError,
    KepwareConfigSettings,
)


BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="OpcTagManager")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")
kepware_config_api = KepwareConfigApi(
    KepwareConfigSettings(
        scheme=KEPWARE_CONFIG_API_SCHEME,
        host=KEPWARE_CONFIG_API_HOST,
        port=KEPWARE_CONFIG_API_PORT,
        username=KEPWARE_CONFIG_API_USER,
        password=KEPWARE_CONFIG_API_PASSWORD,
        verify_ssl=KEPWARE_CONFIG_API_VERIFY_SSL,
        timeout=KEPWARE_CONFIG_API_TIMEOUT,
    )
)


def get_conn():
    return pyodbc.connect(
        f"DRIVER={{{SQL_DRIVER}}};"
        f"SERVER={SQL_SERVER};"
        f"DATABASE={SQL_DB};"
        f"UID={SQL_USER};"
        f"PWD={SQL_PASS};"
        f"TrustServerCertificate={'yes' if SQL_TRUST_SERVER_CERTIFICATE else 'no'};"
    )


def build_tree(rows):
    tree = {}

    for tagid, path, dtype in rows:
        parts = path.split("/")
        node = tree

        for part in parts[:-1]:
            node = node.setdefault(part, {})

        node[parts[-1]] = {
            "tagid": tagid,
            "datatype": dtype,
            "fullpath": path,
            "_leaf": True,
        }

    return tree


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    conn = get_conn()

    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT TagId, Path, DataType
            FROM TagMaster
            WHERE IsActive = 1
            AND (Path LIKE ? OR Path LIKE '%SERVER/SYSTEM%')
            ORDER BY Path
            """,
            (f"%{PRODUCTION_LINE}%",),
        )
        tags = cur.fetchall()
    finally:
        conn.close()

    return templates.TemplateResponse(
        request,
        "opc_tag_manager.html",
        {"request": request, "tree": build_tree(tags)},
    )


@app.post("/refresh")
def refresh_browser():
    subprocess.run([sys.executable, BROWSER_SCRIPT])
    return RedirectResponse("/", status_code=303)


@app.get("/api/kepware/status")
def kepware_status():
    try:
        return kepware_config_api.test_connection()
    except KepwareConfigError as exc:
        return JSONResponse(
            {"connected": False, "error": str(exc), "base_url": kepware_config_api.base_url}
        )


@app.get("/api/kepware/tree")
def kepware_tree():
    try:
        return kepware_config_api.get_configuration_tree()
    except KepwareConfigError as exc:
        return JSONResponse(
            {
                "connected": False,
                "error": str(exc),
                "base_url": kepware_config_api.base_url,
                "tree": [],
            }
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "OpcTagManager:app",
        host=APP_HOST,
        port=APP_PORT,
        log_level=LOG_LEVEL.lower(),
    )
