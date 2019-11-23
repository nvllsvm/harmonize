import contextlib
import logging
import subprocess

LOGGER = logging.getLogger(__name__)


@contextlib.contextmanager
def flac(path):
    """Decode a FLAC file

    Decodes through any errors.

    :param pathlib.Path path: The FLAC file path
    """
    process = subprocess.Popen(
        ['flac', '-csd', path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    yield process.stdout
    process.wait()
    # Decode errors may are non-fatal, but may indicate a problem
    stderr = process.stderr.read()
    if process.returncode:
        raise subprocess.CalledProcessError(
            process.returncode,
            process.args,
            stderr=stderr
        )
    if stderr:
        LOGGER.warning('Decode "%s" "%s"', path, stderr)
