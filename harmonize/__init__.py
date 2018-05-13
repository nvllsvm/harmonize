import argparse
import logging
import os
import pathlib
import shutil
import subprocess
import tempfile

import consumers

LOGGER = logging.getLogger('harmonize')


class Targets:

    def __init__(self, base):
        """
        :param pathlib.Path base: Base path for all targets
        """
        self.base = base
        self.paths = []

    def build_target_path(self, source_path, target_root):
        """Return the corresponding MP3 path for a FLAC path

        :param pathlib.Path source_path: FLAC path
        :param pathlib.Path target_root: Target root path
        :rtype: pathlib.Path
        """
        s = source_path.name.split('.')
        if len(s) > 1 and s[-1].lower() == 'flac':
            s[-1] = 'mp3'
            name = '.'.join(s)
            if pathlib.Path(source_path.parent, name).exists():
                raise NotImplemented
            target_path = pathlib.Path(target_root, name)
        else:
            target_path = pathlib.Path(target_root, source_path.name)
        self.paths.append(target_path)
        return target_path

    def sanitize(self):
        """Remove unexpected files"""
        for root, dirs, files in os.walk(self.base):
            for f in files:
                p = pathlib.Path(root, f)
                if p not in self.paths:
                    LOGGER.warning('Deleting %s', p)
                    if p.is_dir():
                        shutil.rmtree(p)
                    else:
                        p.unlink()


def transcode_and_sync(source_base, target_base):
    """Transcode and/or synchronize a directory recursively

    :param pathlib.Path source_base: Base source path
    :param pathlib.Path target_base: Base target path
    """
    targets = Targets(target_base)

    with consumers.Pool(transcode_files) as pool:
        for root, _, files in os.walk(source_base):
            rel_root = pathlib.Path(root).relative_to(source_base)
            new_parent = pathlib.Path(target_base, rel_root)
            for f in files:
                source_path = pathlib.Path(root, f)
                target_path = targets.build_target_path(
                    source_path, new_parent)

                pool.put(source_path, target_path)


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
    """Return True if a file does not exist or  is out of sync

    :param pathlib.Path source: Source path
    :param pathlib.Path target: Target path
    """
    if target.exists() and target.lstat().st_mtime == source.lstat().st_mtime:
        return False
    else:
        return True


def transcode_files(paths):
    for source, target in paths:
        if needs_update(source, target):
            update_file(source, target)


def update_file(source, target):
    if source.suffix.lower() == '.flac':
        transcode_file(source, target)
    else:
        copy_file(source, target)


def copy_file(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(source, target)
    set_mtime(source, target)


def decode_flac_to_stdout(source):
    return subprocess.run(
        ['flac', '-csdfF', source],
        stdout=subprocess.PIPE,
        check=True
    ).stdout


def transcode_to_mp3(source_orig, flac_pipe, target):
    status = subprocess.run(
        ['ffmpeg', '-y', '-v', '16',
         '-i', 'pipe:0',
         '-i', source_orig,
         '-map_metadata', '1',
         '-codec:a', 'libmp3lame',
         '-qscale:a', '0', target,
         ],
        input=flac_pipe,
        check=True
    )
    if status.stderr:
        raise ValueError('Unable to convert')


def transcode_file(source, target):
    LOGGER.info('Transcoding %s', source)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent,
                                         suffix='.mp3') as tmp:
            target_temp = pathlib.Path(tmp.name)
            transcode_to_mp3(
                source,
                decode_flac_to_stdout(source),
                target_temp
            )
            set_mtime(source, target_temp)
            target_temp.rename(target)
    except FileNotFoundError:
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        'source', help='Source directory')
    parser.add_argument(
        'target', help='Target directory')
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    transcode_and_sync(
        pathlib.Path(args.source),
        pathlib.Path(args.target)
    )


if __name__ == '__main__':
    main()
