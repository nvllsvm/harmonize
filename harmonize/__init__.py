import argparse
import contextlib
import logging
import multiprocessing
import os
import pathlib
import shutil
import subprocess
import tempfile

LOGGER = logging.getLogger('harmonize')


class Targets:

    def __init__(self, base):
        """
        :param pathlib.Path base: Base path for all targets
        """
        self.base = base
        self._paths = set()

    def build_target_path(self, source_path, target_root):
        """Return the corresponding MP3 path for a FLAC path

        :param pathlib.Path source_path: FLAC path
        :param pathlib.Path target_root: Target root path
        :rtype: pathlib.Path
        """
        split_name = source_path.name.split('.')
        if len(split_name) > 1 and split_name[-1].lower() == 'flac':
            split_name[-1] = 'mp3'
            name = '.'.join(split_name)
            if pathlib.Path(source_path.parent, name).exists():
                # TODO: not sure how to handle this
                raise NotImplementedError
        else:
            name = source_path.name

        target_path = pathlib.Path(target_root, name)
        self._paths.add(target_path)
        return target_path

    def sanitize(self):
        """Remove unexpected files"""
        # TODO: remove unexpected directories
        for root, _, files in os.walk(self.base):
            for path_str in files:
                path = pathlib.Path(root, path_str)
                if path not in self._paths:
                    LOGGER.info('Deleteing %s', path)
                    delete_if_exists(path)


def transcode_and_sync(source_base, target_base, num_processes):
    """Transcode and/or synchronize a directory recursively

    :param pathlib.Path source_base: Base source path
    :param pathlib.Path target_base: Base target path
    :param int num_processes: Number of processes to use
    """
    targets = Targets(target_base)
    with multiprocessing.Pool(num_processes) as pool:
        pool.starmap(sync_file, get_paths(source_base, targets), 1)
    targets.sanitize()


def get_paths(source_base, targets):
    """Generator which returns a tuple of source and target paths

    :param pathlib.Path source_base:
    :param harmonize.Targets targets:
    :rtype: tuple
    """
    LOGGER.info('Scanning "%s"', source_base)
    count = 0
    for root, _, files in os.walk(source_base):
        new_parent = pathlib.Path(
            targets.base,
            pathlib.Path(root).relative_to(source_base)
        )
        for filename in files:
            source_path = pathlib.Path(root, filename)
            target_path = targets.build_target_path(source_path, new_parent)
            count += 1
            yield source_path, target_path
    LOGGER.info('Scanned %d items', count)

def set_mtime(source, target):
    """Copy mtime from source to target

    :param pathlib.Path source: Source path
    :param pathlib.Path target: Target path
    """
    os.utime(
        target,
        (target.lstat().st_atime, source.lstat().st_mtime)
    )


def needs_update(source, target):
    """Return True if a file does not exist or is out of sync

    :param pathlib.Path source: Source path
    :param pathlib.Path target: Target path
    """
    if target.exists() and target.lstat().st_mtime == source.lstat().st_mtime:
        return False
    else:
        return True


def sync_file(source, target):
    """Synchronize source file with target if out-of-sync

    :param pathlib.Path source:
    :param pathlib.Path target:
    """
    if needs_update(source, target):
        if source.suffix.lower() == '.flac':
            transcode_flac_to_mp3(source, target)
        else:
            copy_file_with_mtime(source, target)


def copy_file_with_mtime(source, target):
    """Copy a file while retaining the original's modified time

    Creates parent directories if they do not exist.

    :param pathlib.Path source: Source path
    :param pathlib.Path source: Target path
    """
    LOGGER.info('Copying %s', source)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(source, target)
    set_mtime(source, target)


def decode_flac_to_stdout(path):
    """Decode a FLAC file to stdout

    Decodes through any errors.

    :param pathlib.Path path: The FLAC file path
    """
    command = subprocess.run(
        ['flac', '-csdF', path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True
    )

    # Decode errors may are non-fatal, but may indicate a problem
    if command.stderr:
        LOGGER.warning('Decode "%s" "%s"', path, command.stderr)
    return command.stdout


def delete_if_exists(path):
    """Delete a file or directory if it exists

    :param pathlib.Path path:
    """
    try:
        if path.is_file():
            path.unlink()
        else:
            shutil.rmtree(path)
    except FileNotFoundError:
        pass


@contextlib.contextmanager
def TempPath(**kwargs):
    """Wrapper around tempfile.NamedTemporaryFile which returns a path object

    Unlike tempfile.NamedTemporaryFile, the FileNotFoundError exception is not
    raised if the file is deleted before the context closes.

    :rtype: pathlib.Path
    """
    with tempfile.NamedTemporaryFile(**kwargs, delete=False) as tmp:
        temp_path = pathlib.Path(tmp.name)
        try:
            yield temp_path
        except Exception:
            delete_if_exists(temp_path)
            raise
    delete_if_exists(temp_path)


def transcode_flac_to_mp3(flac_path, mp3_path):
    """Transcode a FLAC file to MP3

    :param pathlib.Path flac_path:
    :param pathlib.Path mp3_path:
    """
    LOGGER.info('Transcoding %s', flac_path)
    mp3_path.parent.mkdir(parents=True, exist_ok=True)
    with TempPath(dir=mp3_path.parent, suffix='.mp3') as temp_mp3_path:
        command = subprocess.run(
            ['ffmpeg', '-y', '-v', '16',
             '-i', 'pipe:0',
             '-i', flac_path,
             '-map_metadata', '1',
             '-codec:a', 'libmp3lame',
             '-qscale:a', '0', temp_mp3_path,
             ],
            input=decode_flac_to_stdout(flac_path),
            check=True
        )

        # Errors happen even if exit code is 0
        if command.stderr:
            raise subprocess.CalledProcessError(
                command.returncode,
                command.args,
                output=command.stdout,
                stderr=command.stderr
            )
        set_mtime(flac_path, temp_mp3_path)
        temp_mp3_path.rename(mp3_path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        'source', help='Source directory')
    parser.add_argument(
        'target', help='Target directory')
    parser.add_argument(
        '-n', dest='num_processes',
        help='Number of processes to use',
        type=int,
        default=1)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    transcode_and_sync(
        pathlib.Path(args.source),
        pathlib.Path(args.target),
        args.num_processes
    )
    LOGGER.info('Processing complete')


if __name__ == '__main__':
    main()
