import argparse
import contextlib
import logging
import multiprocessing
import os
import pathlib
import shutil
import subprocess
import tempfile

import mutagen.flac
import mutagen.mp3

import harmonize

LOGGER = logging.getLogger('harmonize')


class Targets:

    def __init__(self, source_base, target_base):
        """
        :param pathlib.Path base: Base path for all targets
        """
        self.target_base = target_base
        self.source_base = source_base
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
                LOGGER.error('Duplicate file found (FLAC & MP3): %s', source_path)
                raise NotImplementedError
        else:
            name = source_path.name

        target_path = pathlib.Path(target_root, name)
        self._paths.add(target_path)
        return target_path

    def sanitize(self):
        """Remove unexpected files and directories"""
        for root, _, files in os.walk(self.target_base):
            root_path = pathlib.Path(root)
            root_path_source = pathlib.Path(
                self.source_base,
                root_path.relative_to(self.target_base)
            )
            if root_path_source.is_dir():
                for path_str in files:
                    path = pathlib.Path(root, path_str)
                    if path not in self._paths:
                        LOGGER.info('Deleting %s', path)
                        delete_if_exists(path)
            else:
                LOGGER.info('Deleting %s', root_path)
                delete_if_exists(root_path)


def transcode_and_sync(source_base, target_base, num_processes):
    """Transcode and/or synchronize a directory recursively

    :param pathlib.Path source_base: Base source path
    :param pathlib.Path target_base: Base target path
    :param int num_processes: Number of processes to use
    """
    targets = Targets(source_base, target_base)
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
            targets.target_base,
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


@contextlib.contextmanager
def decode_flac_to_stdout(path):
    """Decode a FLAC file to stdout

    Decodes through any errors.

    :param pathlib.Path path: The FLAC file path
    """
    process = subprocess.Popen(
        ['flac', '-csd', path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    yield process
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
    decode = decode_flac_to_stdout(flac_path)
    with TempPath(dir=mp3_path.parent, suffix='.mp3.temp') as temp_mp3_path:
        with decode_flac_to_stdout(flac_path) as decode:
            encode = subprocess.Popen(
                ['lame', '--quiet', '-V', '0', '-', temp_mp3_path],
                stdin=decode.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            encode.wait()

        # Errors happen even if exit code is 0
        stderr = encode.stderr.read()
        if encode.returncode or stderr:
            raise subprocess.CalledProcessError(
                encode.returncode,
                encode.args,
                output=encode.stdout.read(),
                encode=stderr
            )

        # Copy tags from FLAC to MP3
        metadata_flac = mutagen.flac.FLAC(flac_path)
        metadata_mp3 = mutagen.mp3.EasyMP3(temp_mp3_path)
        for key, value in metadata_flac.items():
            try:
                metadata_mp3[key] = value
            except KeyError:
                LOGGER.warning('Cannot set tag "%s" for %s', key, mp3_path)
        metadata_mp3.save()

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
    parser.add_argument(
        '--version', action='version', version=harmonize.__version__
    )
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
