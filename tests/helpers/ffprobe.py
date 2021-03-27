import json
import subprocess


def get_metadata(path):
    proc = subprocess.run(
        ['ffprobe', '-i', str(path),
         '-v', 'quiet',
         '-show_streams', '-show_format',
         '-of', 'json'],
        stdout=subprocess.PIPE,
        check=True)
    return json.loads(proc.stdout)
