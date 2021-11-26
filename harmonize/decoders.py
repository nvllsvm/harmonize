import asyncio
import contextlib
import logging
import os

LOGGER = logging.getLogger(__name__)


@contextlib.asynccontextmanager
async def flac(path):
    """Decode a FLAC file

    Decodes through any errors.

    :param pathlib.Path path: The FLAC file path
    """
    read_pipe, write_pipe = os.pipe()

    proc = await asyncio.create_subprocess_exec(
        'flac', '-csd', path,
        stdout=write_pipe,
        stderr=asyncio.subprocess.PIPE)

    os.close(write_pipe)

    yield read_pipe
    await proc.wait()
    # Decode errors may are non-fatal, but may indicate a problem
    stderr = await proc.stderr.read()
    if proc.returncode:
        raise asyncio.subprocess.CalledProcessError(
            proc.returncode,
            proc.args,
            stderr=stderr
        )
    if stderr:
        LOGGER.warning('Decode "%s" "%s"', path, stderr)
