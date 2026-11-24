"""AutoT diagnostics and backup/restore operations: python -m autot.ops --help."""
import argparse
import json
import os
from pathlib import Path
import tempfile

from autot.application.system_health import snapshot


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('status', 'check', 'validate', 'backup',
        'list-backups', 'verify-backup', 'restore', 'prune-backups'))
    parser.add_argument('backup_path', nargs='?')
    parser.add_argument('--output', help='Backup repository (default AUTOT_BACKUP_DIR or sibling of data directory)')
    parser.add_argument('--destination', help='New restore directory; must not already exist')
    parser.add_argument('--keep', type=int, default=14)
    parser.add_argument('--days', type=int, default=30)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--service', choices=('web', 'paper', 'scanner', 'notifications'), default='web')
    args = parser.parse_args(argv)
    if args.command in ('backup', 'list-backups', 'verify-backup', 'restore', 'prune-backups'):
        from autot import backup
        import sqlite3
        try:
            if args.command == 'backup':
                result = backup.create_backup(args.output)
            elif args.command == 'list-backups':
                result = backup.list_backups(args.output, verify=True)
            elif args.command == 'prune-backups':
                result = backup.prune_backups(args.output, keep=args.keep, days=args.days, dry_run=args.dry_run)
            else:
                if not args.backup_path:
                    parser.error('backup_path is required')
                if args.command == 'restore':
                    if not args.destination:
                        parser.error('--destination is required')
                    result = backup.restore_backup(args.backup_path, args.destination)
                else:
                    result = backup.verify_backup(args.backup_path)
            print(json.dumps(result, indent=2))
            return int(args.command == 'list-backups' and any(r['verification'] == 'invalid' for r in result))
        except (OSError, sqlite3.Error, ValueError, KeyError, TypeError) as error:
            print(json.dumps({'error': str(error)}))
            return 1
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
