# Instance environment profiles

One source checkout serves both profiles. Runtime line/channel isolation is now
implemented. Before deployment, manually apply and validate the migration and
follow [MULTI_LINE_DEPLOYMENT.md](MULTI_LINE_DEPLOYMENT.md), starting with SB12.
ALARM_SOUND_IP remains deployment metadata; the existing shared OPC reload node
is retained. No automatic remote service management is introduced.

## Selection

All new profiles use LINE_NAME. LINE_ID is a deprecated fallback only when
LINE_NAME is blank/unset. Runtime identity is line_name; SQL ownership is LineName.
Apply the canonical migration before using an old LineId-only alarm schema.
Unconfigured legacy single-line sites need no migration.

From PowerShell, once deployment prerequisites are satisfied:

```powershell
& D:\AI\OpcTagManager\OpcTagManager_SB11.bat
# In another console:
& D:\AI\OpcTagManager\OpcTagManager_SB12.bat
```

Each launcher uses setlocal, sets OPCTAGMANAGER_ENV_FILE to its absolute
config/.env.sb11 or config/.env.sb12 path using %~dp0, then invokes the same
OpcTagManager.py with the checkout's virtualenv Python (or PATH Python).
No source copies, dotenv shell parsing, activation side effects or service
restarts are involved. The launcher returns the Python process exit code.

For direct invocation, set OPCTAGMANAGER_ENV_FILE to an absolute path or a path
relative to the OpcTagManager project root, then run OpcTagManager.py.
An explicitly empty or missing file fails immediately. Only that file is loaded;
config/.env is never merged in. Profile assignments override inherited process
variables, preventing inherited SB11 settings from overriding an SB12 profile.
Variables omitted from the profile can still be supplied by the process
environment, including secrets. Start each instance in a fresh process; changing
profiles in a running Python interpreter is unsupported.

With OPCTAGMANAGER_ENV_FILE unset, the original config/.env loader and process
environment precedence are preserved. Existing .env and legacy launchers have
not been edited.

## Site settings and credentials

The profiles contain the requested per-line endpoints, ports, MP3 roots, channel
patterns and Influx database names. Both local profiles are complete standalone
configurations populated from the existing working config/.env, including SQL,
OPC, Kepware API and Influx connection settings. SQL_DB is OpcTagMgr in both.

Explicit INFLUX_DB overrides the scoped default opc_<LINE_NAME>. The new profiles
keep explicit opc_SB11/opc_SB12 values and do not need PRODUCTION_LINE.

These two local profiles contain real site credentials and are excluded from Git.
Do not publish or commit them. They require no inherited credential variables or
runtime merge with config/.env. Credentials were copied locally without being
displayed; future changes to config/.env do not automatically update either profile.

Runtime supervision, startup reconciliation and write capabilities follow the
private deployment profile. Verify these settings deliberately before launching.
Migration and remap scripts are provided for manual review; they do not run
automatically at startup. Site-specific schema exports and one-off diagnostic
scripts are excluded from this checkpoint.

## Companion applications

AlarmHelp has .env.sb11 and .env.sb12 at its project root, selected by
ALARM_HELP_ENV_FILE via AlarmHelp_SB11.bat and AlarmHelp_SB12.bat. They use ports
1864 and 1866 and upstream ports 1863 and 1865 respectively. Its legacy .env
loader remains unchanged when the selector is unset. History/detail/Pareto SQL
queries now filter by LINE_NAME. Supply ALARM_HELP_SQL_ENV_FILE (an absolute path
to protected SQL settings) or ALARM_HELP_SQL_CONNECTION_STRING through the
process environment to enable SQL access; the profiles no longer clear these
settings. Neither profile loads a sibling application's legacy environment.

alarm_sound has config/.env.sb11 and config/.env.sb12, selected by
ALARM_SOUND_ENV_FILE via alarm_sound_SB11.bat and alarm_sound_SB12.bat. On the
respective mini-PC, run only its line's launcher. Both use C:\Alarm locally and
the existing shared reload node. Supply SQL credentials through the protected
process environment. The current alarm_sound LINE_NAME scoping is retained. Its
legacy config/.env and alarm_sound.bat remain untouched. The new launchers run
one foreground process and do not introduce automatic restart loops.

```powershell
& D:\AI\AlarmHelp\AlarmHelp_SB11.bat
& D:\AI\AlarmHelp\AlarmHelp_SB12.bat
# On the appropriate mini-PC, using its actual checkout location:
& C:\AI\alarm_sound\alarm_sound_SB11.bat
# SB12 mini-PC:
& C:\AI\alarm_sound\alarm_sound_SB12.bat
```

All three selectors use the same precedence and missing-file rules described
above. No selector automatically loads either sibling project's profile.

## Offline verification

```powershell
& D:\AI\OpcTagManager\.venv\Scripts\python.exe -m unittest discover -s D:\AI\OpcTagManager\tests -p test_env_profiles.py -v
```

These tests exercise the actual loader statements without importing runtimes or
connecting to SQL/OPC. They verify both profiles, inherited-value precedence,
Windows MP3 paths, missing/blank file rejection, absolute/relative selection,
legacy precedence, absence of legacy fallback, unique uppercase keys and launcher
selection. They do not certify shared-database runtime isolation.
