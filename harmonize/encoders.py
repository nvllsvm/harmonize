import subprocess


def lame(stdin, target):
    encode = subprocess.Popen(
        ['lame', '--quiet', '-V', '0', '-', target],
        stdin=stdin,
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
