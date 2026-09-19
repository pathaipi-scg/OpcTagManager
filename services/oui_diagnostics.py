"""Offline diagnostic: python -m services.oui_diagnostics --file PATH --mac MAC.

Does not import/start the production application, scan, or write SQL history.
"""
import argparse
import json

from services.network_inventory import oui_lookup_diagnostics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--file', help='Inspect one local IEEE CSV/JSON in isolation')
    for registry in ('mal', 'mam', 'mas'):
        parser.add_argument(f'--{registry}-file', help=f'Local {registry.upper()} registry; defaults to OT_OUI_{registry.upper()}_FILE')
    parser.add_argument('--mac', required=True, help='Sample MAC copied from arp -a')
    args = parser.parse_args()
    result = oui_lookup_diagnostics(args.file, args.mac, mal_file=args.mal_file,
                                    mam_file=args.mam_file, mas_file=args.mas_file)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result['load_success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
