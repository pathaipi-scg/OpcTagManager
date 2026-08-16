from pathlib import Path
import subprocess
import sys

import pyodbc
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from config.config import (
    BROWSER_SCRIPT,
    PRODUCTION_LINE,
    SQL_DB,
    SQL_DRIVER,
    SQL_PASS,
    SQL_SERVER,
    SQL_USER,
)


BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="OpcTagManager")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


def get_conn():
    return pyodbc.connect(
        f"DRIVER={{{SQL_DRIVER}}};"
        f"SERVER={SQL_SERVER};"
        f"DATABASE={SQL_DB};"
        f"UID={SQL_USER};"
        f"PWD={SQL_PASS};"
        f"TrustServerCertificate=yes;"
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
