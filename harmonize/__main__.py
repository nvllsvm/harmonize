import argparse
import asyncio
import contextlib
import fnmatch
import functools
import importlib.metadata
import logging
import os
import pathlib
import shutil
import tempfile

import mutagen
import mutagen.mp3

from . import decoders, encoders

LOGGER = logging.getLogger('harmonize')

try:
    VERSION = importlib.metadata.version('harmonize')
except importlib.metadata.PackageNotFoundError:
    VERSION = 'unknown'


class Targets:

    def __init__(self, source_base, target_base, target_codec, exclude):
        """
        :param pathlib.Path base: Base path for all targets
        """
        self.target_base = target_base
        self.source_base = source_base
        self.target_codec = target_codec
        self.exclude = set()
        if exclude:
            self.exclude.update(exclude)
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
            excluded = False
            for exclude in self.exclude:
                if fnmatch.fnmatch(path, exclude):
                    excluded = True

            if not excluded:
                target_path = self.build_target_path(path)
                count += 1
                yield path, target_path
        LOGGER.info('Scanned %d items', count)


def _all_files(root):
    """Return a list of all files under a root path"""
    stack = [root]
    while stack:
        for path in stack.pop().iterdir():
            if path.is_file():
                yield path
            elif path.is_dir():
                stack.append(path)


async def sync_file(source, target, encoder):
    """Synchronize source file with target if out-of-sync

    :param pathlib.Path source:
    :param pathlib.Path target:
    """
    # lstat the source only as source file may change during transcode
    source_lstat = source.lstat()

    if target.exists() and target.lstat().st_mtime == source_lstat.st_mtime:
        return

    target.parent.mkdir(parents=True, exist_ok=True)
    with TempPath(dir=target.parent, suffix='.temp') as temp_target:
        if source.suffix.lower() == '.flac':
            await transcode(decoders.flac, encoder, source, temp_target)
            copy_audio_metadata(source, temp_target)
        else:
            copy(source, temp_target)
        copy_path_attr(source_lstat, temp_target)
        temp_target.rename(target)


def copy_path_attr(source_lstat, target):
    target.chmod(source_lstat.st_mode)
    os.utime(
        target,
        (target.lstat().st_atime, source_lstat.st_mtime)
    )


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


async def transcode(decoder, encoder, source, target):
    """Transcode a FLAC file to MP3

    :param pathlib.Path source:
    :param pathlib.Path target:
    """
    LOGGER.info('Transcoding %s', source)
    target.parent.mkdir(parents=True, exist_ok=True)
    async with decoder(source) as decoded:
        await encoder(decoded, target)


_CODEC_ENCODERS = {
    'mp3': encoders.lame,
    'opus': encoders.opus
}


class AsyncExecutor:
    def __init__(self, max_pending=None):
        self._max_pending = max_pending
        self._queued = []
        self._pending = set()

    def submit(self, func, *args, **kwargs):
        self._queued.append((func, args, kwargs))
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            self._fill()

    async def as_completed(self):
        while self._queued or self._pending:
            self._fill()

            done, self._pending = await asyncio.wait(
                self._pending, return_when=asyncio.FIRST_COMPLETED)

            for result in done:
                yield result

    def _fill(self):
        for _ in range(self._max_pending - len(self._pending)):
            if not self._queued:
                return
            func, args, kwargs = self._queued.pop()
            self._pending.add(asyncio.create_task(func(*args, **kwargs)))


async def run(executor):
    async for result in executor.as_completed():
        try:
            result = result.result()
        except Exception as e:
            print('error', type(e).__name__, e)
        else:
            print('slept', result)


async def async_run(args, encoder_options):
    encoder = functools.partial(
        _CODEC_ENCODERS[args.codec], options=encoder_options)
    targets = Targets(
        args.source, args.target, args.codec,
        exclude=args.exclude)

    executor = AsyncExecutor(args.num_processes)
    for source, target in sorted(targets._get_paths()):
        executor.submit(sync_file, source, target, encoder)
    async for result in executor.as_completed():
        result.result()

    targets.sanitize()

    LOGGER.info('Processing complete')


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
        default=os.cpu_count())
    parser.add_argument(
        '-q', '--quiet', action='store_true',
        help='suppress informational output')
    parser.add_argument(
        '--version', action='version', version=VERSION,
    )
    parser.add_argument(
        '--exclude', metavar='PATTERN', action='append',
        help='ignore files matching this pattern')
    parser.add_argument(
        'source', type=pathlib.Path, help='Source directory')
    parser.add_argument(
        'target', type=pathlib.Path, help='Target directory')

    args, encoder_options = parser.parse_known_args()

    logging.basicConfig(
        format='%(message)s',
        level=logging.WARNING if args.quiet else logging.INFO)

    asyncio.run(async_run(args, encoder_options))


if __name__ == '__main__':
    main()
