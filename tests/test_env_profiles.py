"""Offline configuration tests; never import application runtimes or connect to services."""
import shutil
import ast
import os
import runpy
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dotenv import dotenv_values
from dotenv.parser import parse_stream

ROOT = Path(__file__).resolve().parents[2]
APPS = (
    ('OpcTagManager', 'config/config.py', 'OPCTAGMANAGER_ENV_FILE', 'config/.env'),
    ('AlarmHelp', 'app.py', 'ALARM_HELP_ENV_FILE', '.env'),
    ('alarm_sound', 'config/config.py', 'ALARM_SOUND_ENV_FILE', 'config/.env'),
)


def load_only(app, source, selector, env):
    """Execute the real loader AST, excluding application and database imports."""
    path = ROOT / app / source
    tree = ast.parse(path.read_text(encoding='utf-8-sig'))
    if app == 'AlarmHelp':
        start = next(i for i, n in enumerate(tree.body)
                     if isinstance(n, ast.FunctionDef) and n.name == 'load_env_file')
        stop = next(i for i, n in enumerate(tree.body)
                    if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'UPSTREAM_BASE_URL' for t in n.targets))
        tree.body = tree.body[start:stop]
    else:
        stop = next(i for i, n in enumerate(tree.body)
                    if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
                    and isinstance(n.value.func, ast.Name) and n.value.func.id == 'load_dotenv')
        tree.body = tree.body[:stop + 1]
        tree.body = [n for n in tree.body if not (isinstance(n, ast.ImportFrom) and n.module == 'config.sql_connection')]
    namespace = {'__file__': str(path), 'ROOT': path.parent, 'Path': Path, 'os': os}
    with patch.dict(os.environ, env, clear=True):
        exec(compile(tree, str(path), 'exec'), namespace)
        return dict(os.environ)


class ProfileTests(unittest.TestCase):
    def setUp(self):
        # Never read private deployment profiles, even on assertion failures.
        global ROOT, APPS
        original_root, original_apps = ROOT, APPS
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.addCleanup(lambda: globals().update(ROOT=original_root, APPS=original_apps))
        APPS = tuple(item for item in original_apps if (original_root / item[0] / item[1]).is_file())
        ROOT = Path(directory.name)
        for app, source, selector, legacy in APPS:
            target = ROOT / app / source
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original_root / app / source, target)
            example = original_root / app / (legacy + '.example')
            defaults = dotenv_values(example) if example.is_file() else {}
            if app == 'OpcTagManager':
                defaults['SQL_DB'] = 'OpcTagMgr'
            legacy_path = ROOT / app / legacy
            legacy_path.parent.mkdir(parents=True, exist_ok=True)
            legacy_path.write_text('\n'.join(f'{k}={v}' for k,v in defaults.items() if v is not None))
            for line, port in [('SB11',1863),('SB12',1865)]:
                values = dict(defaults) if app == 'OpcTagManager' else {}
                values.update(LINE_NAME=line, MP3_FOLDER=('Y:\\' if line=='SB11' else 'Z:\\') if app=='OpcTagManager' else 'C:\\Alarm')
                if app == 'OpcTagManager':
                    values.update(APP_PORT=str(port), INFLUX_DB='opc_'+line,
                                  KEPWARE_CHANNEL_PATTERNS=f'{line},{line}_*,{line}S7')
                elif app == 'AlarmHelp':
                    values.update(ALARM_HELP_PORT=str(port+1), OPC_TAG_MANAGER_BASE_URL=f'http://127.0.0.1:{port}')
                (ROOT/app/(legacy+'.'+line.lower())).write_text('\n'.join(f'{k}={v}' for k,v in values.items() if v is not None))
                shutil.copyfile(original_root/app/f'{app}_{line}.bat', ROOT/app/f'{app}_{line}.bat')

    def test_profiles_override_inherited_other_line(self):
        for app, source, selector, legacy in APPS:
            for line in ('sb11', 'sb12'):
                with self.subTest(app=app, line=line):
                    relative = legacy + '.' + line
                    values = load_only(app, source, selector, {
                        selector: relative, 'LINE_NAME': 'WRONG', 'MP3_FOLDER': 'WRONG',
                        'APP_PORT': '9999', 'OPC_TAG_MANAGER_BASE_URL': 'http://wrong',
                        'SQL_PASS': 'test-only-secret',
                    })
                    self.assertEqual(values['LINE_NAME'], line.upper())
                    if app != 'OpcTagManager':
                        self.assertEqual(values['SQL_PASS'], 'test-only-secret')
                    if app == 'OpcTagManager':
                        self.assertEqual(values['APP_PORT'], '1863' if line == 'sb11' else '1865')
                        self.assertEqual(values['MP3_FOLDER'], 'Y:\\' if line == 'sb11' else 'Z:\\')
                        self.assertEqual(values['INFLUX_DB'], 'opc_' + line.upper())
                        self.assertEqual(values['KEPWARE_CHANNEL_PATTERNS'], f'{line.upper()},{line.upper()}_*,{line.upper()}S7')
                    elif app == 'AlarmHelp':
                        self.assertEqual(values['ALARM_HELP_PORT'], '1864' if line == 'sb11' else '1866')
                        self.assertEqual(values['OPC_TAG_MANAGER_BASE_URL'], 'http://127.0.0.1:' + ('1863' if line == 'sb11' else '1865'))
                        self.assertNotIn('ALARM_HELP_SQL_ENV_FILE', values)
                    else:
                        self.assertEqual(values['MP3_FOLDER'], 'C:\\Alarm')

    def test_explicit_file_never_loads_legacy_and_accepts_absolute_path(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / 'profile.env'
            profile.write_text('LINE_NAME=ISOLATED\n')
            for app, source, selector, _ in APPS:
                values = load_only(app, source, selector, {selector: str(profile)})
                self.assertEqual(values, {selector: str(profile), 'LINE_NAME': 'ISOLATED'})

    def test_missing_or_blank_explicit_profile_fails(self):
        for app, source, selector, _ in APPS:
            for value in ('', 'missing-profile-for-test.env'):
                with self.subTest(app=app, value=value), self.assertRaises(RuntimeError):
                    load_only(app, source, selector, {selector: value})

    def test_legacy_path_and_environment_precedence_unchanged(self):
        # Mock file reads to avoid reading any production credentials.
        for app, source, selector, legacy in APPS:
            observed = []
            def fake_load(path, override=False):
                observed.append((Path(path), override))
            if app == 'AlarmHelp':
                with patch.object(Path, 'exists', return_value=True), patch.object(Path, 'read_text', autospec=True) as read:
                    original = (ROOT / app / source).read_bytes().decode('utf-8-sig')
                    read.side_effect = lambda path, **kw: original if path.name == 'app.py' else 'APP_PORT=1234\n'
                    values = load_only(app, source, selector, {'APP_PORT': '9999'})
                    self.assertEqual(values['APP_PORT'], '9999')
            else:
                with patch('dotenv.load_dotenv', side_effect=fake_load):
                    load_only(app, source, selector, {})
                self.assertEqual(observed, [(ROOT / app / legacy, False)])

    def test_profile_syntax_and_launchers(self):
        for app, _, selector, legacy in APPS:
            for line in ('sb11', 'sb12'):
                path = ROOT / app / (legacy + '.' + line)
                with path.open(encoding='utf-8') as stream:
                    self.assertFalse(any(binding.error for binding in parse_stream(stream)),
                                     'Invalid dotenv syntax: ' + str(path))
                keys = []
                for row in path.read_text().splitlines():
                    if not row or row.startswith('#'):
                        continue
                    key, value = row.split('=', 1)
                    self.assertEqual(key, key.strip().upper())
                    self.assertEqual(value, value.strip())
                    keys.append(key)
                self.assertEqual(len(keys), len(set(keys)))
                if app != 'OpcTagManager':
                    self.assertNotIn('SQL_PASS', dotenv_values(path))
                self.assertIn('LINE_NAME', dotenv_values(path))
                self.assertNotIn('LINE_ID', dotenv_values(path))
                launcher = (ROOT / app / f'{app}_{line.upper()}.bat').read_text()
                self.assertIn('setlocal', launcher)
                self.assertIn(f'set "{selector}=%~dp0', launcher)
                self.assertIn('.env.' + line + '"', launcher)

    def test_opctagmanager_profiles_are_complete_standalone_configurations(self):
        root = ROOT / 'OpcTagManager'
        source = root / 'config/config.py'
        tree = ast.parse(source.read_text())
        required = {
            node.args[0].value for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id in {'get_required', 'get_configured', 'get_int', 'get_bool'}
            and node.args and isinstance(node.args[0], ast.Constant)
        } - {'PRODUCTION_LINE'}  # Derived from LINE_NAME in scoped mode.
        for line, port in [('SB11', 1863), ('SB12', 1865)]:
            path = root / ('config/.env.' + line.lower())
            with self.subTest(line=line), patch.dict(os.environ, {}, clear=True):
                profile = dotenv_values(path)
                missing = sorted(key for key in required if profile.get(key) is None)
                self.assertFalse(missing, 'Missing configuration keys: ' + ', '.join(missing))
                os.environ['OPCTAGMANAGER_ENV_FILE'] = str(path)
                # Execute only configuration, never the application/runtime.
                # Track file reads to prove legacy .env was not merged.
                from dotenv import load_dotenv
                with patch('dotenv.load_dotenv', wraps=load_dotenv) as loader, patch.object(sys, 'path', [str(root), *sys.path]):
                    try:
                        config = runpy.run_path(str(source))
                    except Exception:
                        self.fail('Standalone configuration validation failed for ' + line)
                self.assertEqual(loader.call_count, 1)
                self.assertEqual(Path(loader.call_args.args[0]), path)
                self.assertEqual(config['LINE_NAME'], line)
                self.assertEqual(config['APP_PORT'], port)
                self.assertEqual(config['KEPWARE_CHANNEL_PATTERNS'], (line, line + '_*', line + 'S7'))
                self.assertEqual(config['INFLUX_DB'], 'opc_' + line)
                self.assertEqual(config['SQL_DB'], 'OpcTagMgr')

    def test_fixture_profiles_preserve_copied_connection_settings(self):
        root = ROOT / 'OpcTagManager' / 'config'
        connection_keys = ('OPC_URL', 'SQL_SERVER', 'SQL_DB', 'SQL_DRIVER', 'SQL_USER', 'SQL_PASS',
                           'SQL_ENCRYPT', 'SQL_TRUST_SERVER_CERTIFICATE', 'INFLUX_HOST', 'INFLUX_PORT',
                           'INFLUX_USER', 'INFLUX_PASS', 'KEPWARE_CONFIG_API_SCHEME',
                           'KEPWARE_CONFIG_API_HOST', 'KEPWARE_CONFIG_API_PORT',
                           'KEPWARE_CONFIG_API_USER', 'KEPWARE_CONFIG_API_PASSWORD',
                           'KEPWARE_CONFIG_API_VERIFY_SSL', 'KEPWARE_MODBUS_HOST', 'KEPWARE_MODBUS_PORT')
        with patch.dict(os.environ, {}, clear=True):
            legacy = dotenv_values(root / '.env')
            for line in ('sb11', 'sb12'):
                profile = dotenv_values(root / ('.env.' + line))
                mismatches = [key for key in connection_keys
                              if key in legacy and profile.get(key) != legacy[key]]
                self.assertFalse(mismatches, 'Connection setting mismatch: ' + ', '.join(mismatches))


if __name__ == '__main__':
    unittest.main()
