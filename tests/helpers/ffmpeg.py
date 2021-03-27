import subprocess


def generate_silence(seconds, dest):
    subprocess.run(
        ['ffmpeg', '-f', 'lavfi',
         '-v', 'quiet',
         '-i', 'anullsrc=channel_layout=stereo:sample_rate=44100',
         '-t', str(seconds), str(dest)],
        check=True)
