
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import pyodbc, os
import subprocess
import sys

from config.config import *

from pyModbusTCP.client import ModbusClient

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# MP3_FOLDER and BROWSER_SCRIPT come from config.config (env-backed, with defaults)

def get_conn():
    return pyodbc.connect(
        f"DRIVER={{{SQL_DRIVER}}};"
        f"DRIVER={{{SQL_DRIVER}}};"
        f"SERVER={SQL_SERVER};"
        f"DATABASE={SQL_DB};"
        f"UID={SQL_USER};"
        f"PWD={SQL_PASS};"
        f"TrustServerCertificate=yes;"
    )

def reload_alarm():

    try:

        c = ModbusClient(
            host=KEPWARE_MODBUS_HOST,
            port=KEPWARE_MODBUS_PORT,
            auto_open=True
        )

        regs = c.read_holding_registers(
             RELOAD_ALARM_ADDR,
            1
        )

        if not regs:

            print(
                "READ RELOAD_ALARM FAILED"
            )

            return

        current = regs[0]

        next_value = (current + 1) % 65536

        ok = c.write_single_register(
            RELOAD_ALARM_ADDR,
            next_value
        )

        if ok:
            print(f"RELOAD_ALARM => {next_value}")
        else:
            print("WRITE RELOAD_ALARM FAILED")

    except Exception as ex:

        print(
            "RELOAD_ALARM ERROR:",
            ex
        )

def build_tree(rows, used_tagids=None):
    used_tagids = used_tagids or set()
    tree = {}

    for tagid, path, dtype in rows:
        parts = path.split("/")
        node = tree

        for p in parts[:-1]:
            node = node.setdefault(p, {})

        node[parts[-1]] = {
            "tagid": tagid,
            "datatype": dtype,
            "fullpath": path,
            "used": tagid in used_tagids,
            "_leaf": True
        }

    return tree

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    conn = get_conn()
    cur = conn.cursor()

    # tags / mp3 files already mapped to an alarm (shown but greyed-out, not selectable)
    cur.execute("SELECT TagId, Mp3File FROM Alarm_Lists")
    used_rows = cur.fetchall()
    used_tagids = {r.TagId for r in used_rows}
    used_mp3 = {(r.Mp3File or "").lower() for r in used_rows}

    #from config.config import PRODUCTION_LINE

    cur.execute("""
    SELECT TagId, Path, DataType
    FROM TagMaster
    WHERE IsActive = 1
    AND (Path LIKE ? OR Path LIKE '%SERVER/SYSTEM%')
    ORDER BY Path
    """, (f"%{PRODUCTION_LINE}%",))

    tags = cur.fetchall()

    tree = build_tree(tags, used_tagids)

    mp3_files = []
    if os.path.exists(MP3_FOLDER):
        mp3_files = sorted([f for f in os.listdir(MP3_FOLDER) if f.lower().endswith(".mp3")])

    cur.execute("""
        SELECT AlarmId, TagId, TagPath, AlarmMode,
               ThresholdHigh, ThresholdLow, Mp3File,
               Priority, EnableAlarm, [Repeat]
        FROM Alarm_Lists
        ORDER BY TagPath
    """)
    alarms = cur.fetchall()

    conn.close()

    return templates.TemplateResponse(request, "alarm_list.html", {
        "request": request,
        "tree": tree,
        "mp3_files": mp3_files,
        "used_mp3": used_mp3,
        "alarms": alarms
    })

@app.post("/save")
def save_alarm(
    alarmid: str = Form(""),
    tagid: int = Form(...),
    tagpath: str = Form(...),
    alarmmode: str = Form(...),
    thresholdhigh: float = Form(None),
    thresholdlow: float = Form(None),
    mp3file: str = Form(...),
    priority: int = Form(1),
    repeatcount: str = Form("3")
):
    # default to 3 when blank or invalid
    try:
        repeat = int(repeatcount)
    except (ValueError, TypeError):
        repeat = 3
    if repeat < 1:
        repeat = 3

    conn = get_conn()
    cur = conn.cursor()

    # กัน Tag ซ้ำ
    if not alarmid:

        cur.execute("""
            SELECT COUNT(*)
            FROM Alarm_Lists
            WHERE TagId = ?
        """, (tagid,))

        if cur.fetchone()[0] > 0:

            conn.close()

            return RedirectResponse(
                "/",
                status_code=303
            )

    if alarmid:
        cur.execute("""
            UPDATE Alarm_Lists
            SET TagId = ?,
                TagPath = ?,
                AlarmMode = ?,
                ThresholdHigh = ?,
                ThresholdLow = ?,
                Mp3File = ?,
                Priority = ?,
                [Repeat] = ?,
                UpdatedTime = GETDATE()
            WHERE AlarmId = ?
        """, (
            tagid,
            tagpath,
            alarmmode,
            thresholdhigh,
            thresholdlow,
            mp3file,
            priority,
            repeat,
            int(alarmid)
        ))
    else:
        cur.execute("""
            INSERT INTO Alarm_Lists (
                TagId,
                TagPath,
                AlarmMode,
                ThresholdHigh,
                ThresholdLow,
                Mp3File,
                Priority,
                [Repeat],
                RepeatEnable,
                EnableAlarm,
                CreatedTime,
                UpdatedTime
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, 1, 1,
                GETDATE(),
                GETDATE()
            )
        """, (
            tagid,
            tagpath,
            alarmmode,
            thresholdhigh,
            thresholdlow,
            mp3file,
            priority,
            repeat
        ))

    conn.commit()
    conn.close()
    reload_alarm()

    return RedirectResponse("/", status_code=303)

@app.post("/delete/{alarm_id}")
def delete_alarm(alarm_id: int):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        DELETE FROM Alarm_Lists
        WHERE AlarmId = ?
    """, (alarm_id,))

    conn.commit()
    conn.close()
    reload_alarm()

    return RedirectResponse("/", status_code=303)

@app.post("/refresh")
def refresh_browser():

    # rebuild the OPC tag tree only (e.g. after adding a machine).
    # does NOT touch Alarm_Lists.
    subprocess.run([
        sys.executable,
        BROWSER_SCRIPT
    ])

    return RedirectResponse(
        "/",
        status_code=303
    )

@app.get("/mp3/{filename}")
def serve_mp3(filename: str):
    # serve an MP3 from MP3_FOLDER so the browser can preview the alarm sound.
    # restrict to a plain basename ending in .mp3 to block path traversal.
    name = os.path.basename(filename)

    if name != filename or not name.lower().endswith(".mp3"):
        return HTMLResponse("Invalid file", status_code=400)

    path = os.path.join(MP3_FOLDER, name)

    if not os.path.isfile(path):
        return HTMLResponse("Not found", status_code=404)

    return FileResponse(path, media_type="audio/mpeg")
