import pathlib
import shutil
import subprocess
import unittest

from tests import helpers

TMP = pathlib.Path(__file__).parent.joinpath('tmp')


class TestApp(unittest.TestCase):

    def setUp(self):
        try:
            shutil.rmtree(TMP)
        except FileNotFoundError:
            pass
        TMP.mkdir()

    def test_transcodes_flac_to_mp3(self):
        source_dir = TMP / 'source'
        source_dir.mkdir()
        target_dir = TMP / 'target'
        helpers.ffmpeg.generate_silence(1, source_dir / 'audio.flac')

        subprocess.run(
            ['harmonize', str(source_dir), str(target_dir)],
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
            check=True)

        metadata = helpers.ffprobe.get_metadata(target_dir / 'audio.mp3')

        self.assertEqual('mp3', metadata['format']['format_name'])
        self.assertEqual(1, len(metadata['streams']))
        self.assertEqual('mp3', metadata['streams'][0]['codec_name'])
        # mp3 will not be exact duration as input
        self.assertTrue(1 <= float(metadata['format']['duration']) <= 1.1)

        # TODO test output
        # self.assertEqual(proc.stderr, b'')
        # self.assertEqual(proc.stdout, b'')

    def test_transcodes_flac_to_opus(self):
        source_dir = TMP / 'source'
        source_dir.mkdir()
        target_dir = TMP / 'target'
        helpers.ffmpeg.generate_silence(1, source_dir / 'audio.flac')

        subprocess.run(
            ['harmonize', '--codec', 'opus', str(source_dir), str(target_dir)],
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
            check=True)

        metadata = helpers.ffprobe.get_metadata(target_dir / 'audio.opus')

        self.assertEqual('ogg', metadata['format']['format_name'])
        self.assertEqual(1, len(metadata['streams']))
        self.assertEqual('opus', metadata['streams'][0]['codec_name'])
        # mp3 will not be exact duration as input
        self.assertTrue(1 <= float(metadata['format']['duration']) <= 1.1)

        # TODO test output
        # self.assertEqual(proc.stderr, b'')
        # self.assertEqual(proc.stdout, b'')
