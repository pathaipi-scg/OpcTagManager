"""Offline diagnostic: python -m services.oui_diagnostics --file PATH --mac MAC.

Does not import/start the production application, scan, or write SQL history.
"""
import argparse
import json

from services.network_inventory import oui_lookup_diagnostics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--file', help='Local IEEE CSV/JSON; defaults to OT_OUI_FILE environment variable')
    parser.add_argument('--mac', required=True, help='Sample MAC copied from arp -a')
    args = parser.parse_args()
    result = oui_lookup_diagnostics(args.file, args.mac)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result['load_success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
