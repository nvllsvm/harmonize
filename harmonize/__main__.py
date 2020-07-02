import argparse
import concurrent.futures
import contextlib
import functools
import logging
import os
import pathlib
import shutil
import tempfile

import mutagen
import mutagen.mp3
import pkg_resources

from . import decoders, encoders

LOGGER = logging.getLogger('harmonize')

try:
    VERSION = pkg_resources.get_distribution('harmonize').version
except pkg_resources.DistributionNotFound:
    VERSION = 'unknown'


class Targets:

    def __init__(self, source_base, target_base, target_codec):
        """
        :param pathlib.Path base: Base path for all targets
        """
        self.target_base = target_base
        self.source_base = source_base
        self.target_codec = target_codec
        self._paths = set()

    def build_target_path(self, source_path):
        """Return the corresponding target path for a FLAC path

        :param pathlib.Path source_path: FLAC path
        :rtype: pathlib.Path
        """
        split_name = source_path.name.split('.')
        if len(split_name) > 1 and split_name[-1].lower() == 'flac':
            split_name[-1] = self.target_codec
            name = '.'.join(split_name)
            if pathlib.Path(source_path.parent, name).exists():
                # TODO: not sure how to handle this
                LOGGER.error('Duplicate file found: %s', source_path)
                raise NotImplementedError
        else:
            name = source_path.name

        target_path = self.target_base.joinpath(
            source_path.parent.relative_to(self.source_base), name)
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
                        self._delete_if_exists(path)
            else:
                LOGGER.info('Deleting %s', root_path)
                self._delete_if_exists(root_path)

    @staticmethod
    def _delete_if_exists(path):
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

    def _get_paths(self):
        """Generator which returns a tuple of source and target paths

        :param pathlib.Path source_base:
        :rtype: tuple
        """
        LOGGER.info('Scanning "%s"', self.source_base)
        count = 0
        for path in _all_files(self.source_base):
            target_path = self.build_target_path(path)
            count += 1
            yield path, target_path
        LOGGER.info('Scanned %d items', count)


def _all_files(root):
    """Return a list of all files under a root path"""
    files = []
    stack = [root]
    while stack:
        for path in stack.pop().iterdir():
            if path.is_file():
                files.append(path)
            elif path.is_dir():
                stack.append(path)
    return files


def sync_file(source, target, encoder):
    """Synchronize source file with target if out-of-sync

    :param pathlib.Path source:
    :param pathlib.Path target:
    """
    # lstat the source only as source file may change during transcode
    source_mtime = source.lstat().st_mtime

    if target.exists() and target.lstat().st_mtime == source_mtime:
        return

    target.parent.mkdir(parents=True, exist_ok=True)
    with TempPath(dir=target.parent, suffix='.temp') as temp_target:
        if source.suffix.lower() == '.flac':
            transcode(decoders.flac, encoder, source, temp_target)
            copy_audio_metadata(source, temp_target)
        else:
            copy(source, temp_target)
        temp_target.chmod(source.stat().st_mode)
        os.utime(
            temp_target,
            (temp_target.lstat().st_atime, source_mtime)
        )
        temp_target.rename(target)


def copy(source, target):
    """Copy a file while retaining the original's modified time

    Creates parent directories if they do not exist.

    :param pathlib.Path source: Source path
    :param pathlib.Path source: Target path
    """
    LOGGER.info('Copying %s', source)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(source, target)


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
        finally:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass


def copy_audio_metadata(source, target):
    source_metadata = mutagen.File(source, easy=True)
    target_metadata = mutagen.File(target, easy=True)
    if target_metadata is None:
        # this will barf for other types
        target_metadata = mutagen.mp3.EasyMP3(target)
    for key, value in source_metadata.items():
        try:
            target_metadata[key] = value
        except KeyError:
            LOGGER.debug('Cannot set tag "%s" for %s', key, target)
    target_metadata.save()


def transcode(decoder, encoder, source, target):
    """Transcode a FLAC file to MP3

    :param pathlib.Path source:
    :param pathlib.Path target:
    """
    LOGGER.info('Transcoding %s', source)
    target.parent.mkdir(parents=True, exist_ok=True)
    with decoder(source) as decoded:
        encoder(decoded, target)


_CODEC_ENCODERS = {
    'mp3': encoders.lame,
    'opus': encoders.opus
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--codec', default='mp3', choices=_CODEC_ENCODERS,
        help=('codec to output as. encoder configuration may be specified as '
              'additional arguments to harmonize'))
    parser.add_argument(
        '-n', dest='num_processes',
        help='Number of processes to use',
        type=int,
        default=1)
    parser.add_argument(
        '-q', '--quiet', action='store_true',
        help='suppress informational output')
    parser.add_argument(
        '--version', action='version', version=VERSION,
    )
    parser.add_argument(
        'source', type=pathlib.Path, help='Source directory')
    parser.add_argument(
        'target', type=pathlib.Path, help='Target directory')

    args, encoder_options = parser.parse_known_args()

    logging.basicConfig(
        format='%(message)s',
        level=logging.WARNING if args.quiet else logging.INFO)

    encoder = functools.partial(
        _CODEC_ENCODERS[args.codec], options=encoder_options)
    targets = Targets(args.source, args.target, args.codec)
    with concurrent.futures.ProcessPoolExecutor(args.num_processes) as pool:
        futures = [
            pool.submit(sync_file, source, target, encoder)
            for source, target in sorted(targets._get_paths())
        ]
        for future in concurrent.futures.as_completed(futures):
            future.result()
    targets.sanitize()

    LOGGER.info('Processing complete')


if __name__ == '__main__':
    main()
