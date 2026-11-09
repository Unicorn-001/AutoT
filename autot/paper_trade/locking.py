"""Local POSIX advisory locks. Keep lock files: unlinking permits two owners."""
from contextlib import contextmanager
import fcntl
from pathlib import Path


class MonitorAlreadyRunning(RuntimeError):
    pass


def lock_path(database, kind):
    return Path(str(Path(database).resolve()) + f'.{kind}.lock')


@contextmanager
def database_lock(database, kind, *, blocking=True):
    path = lock_path(database, kind)
    with path.open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError as error:
            raise MonitorAlreadyRunning('Another paper monitor owns this database lock.') from error
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def monitor_active(database):
    path = lock_path(database, 'monitor')
    try:
        with path.open('r') as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(handle, fcntl.LOCK_UN)
    except FileNotFoundError:
        pass
    return False
