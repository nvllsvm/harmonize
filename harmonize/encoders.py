import os
import subprocess


def lame(stdin_pipe, target, options=[]):
    encode = subprocess.Popen(
        ['lame', '--quiet', *[str(o) for o in options], '-', target],
        stdin=stdin_pipe,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    os.close(stdin_pipe)
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


def opus(stdin_pipe, target, options=[]):
    subprocess.run(
        ['opusenc', '--quiet', *[str(o) for o in options], '-', target],
        stdin=stdin_pipe,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True
    )
    os.close(stdin_pipe)
