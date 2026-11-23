"""Read-only operations: python -m autot.ops status|check|validate [--service ...]."""
import argparse
import json
import os
from pathlib import Path
import tempfile

from autot.application.system_health import snapshot


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('status', 'check', 'validate'))
    parser.add_argument('--service', choices=('web', 'paper', 'scanner', 'notifications'), default='web')
    args = parser.parse_args(argv)
    report = snapshot(integrity=args.command != 'status')
    recovery = report['recovery']
    errors = recovery['errors']
    if args.command == 'validate':
        root = Path(recovery['data_directory'])
        if not root.is_dir():
            errors.append('Provision the persistent data directory before service startup.')
        else:
            # Temporary probes only; no schema, heartbeat or trade mutations.
            directories = {root}
            directories.update(Path(d['path']).parent for d in recovery['databases'].values()
                               if Path(d['path']).parent.exists())
            for directory in directories:
                try:
                    with tempfile.TemporaryFile(dir=directory):
                        pass
                except OSError as error:
                    errors.append(f'Storage write probe failed: {error}')
            for db in recovery['databases'].values():
                if Path(db['path']).exists() and not os.access(db['path'], os.W_OK):
                    errors.append(f"Database not writable: {db['path']}")
        key = {'paper': 'monitor', 'scanner': 'scheduler'}.get(args.service)
        if key and recovery['locks'].get(key, {}).get('held'):
            errors.append(f'{key} already owns its service lock.')
        config = report['monitoring']
        if args.service in ('paper', 'scanner') and not getattr(config,
                'paper_monitor_enabled' if args.service == 'paper' else 'daily_scan_enabled'):
            errors.append(f'{args.service} service is disabled in saved settings.')
    report['monitoring'] = report['monitoring'].model_dump(mode='json')
    print(json.dumps(report, indent=2))
    return 1 if errors or any(report[k].get('unavailable') for k in ('paper', 'scanner')) else 0


if __name__ == '__main__':
    raise SystemExit(main())
