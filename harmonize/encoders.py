import subprocess


def lame(stdin, target, options=[]):
    encode = subprocess.Popen(
        ['lame', '--quiet', *[str(o) for o in options], '-', target],
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


def opus(stdin, target, options=[]):
    subprocess.run(
        ['opusenc', '--quiet', *[str(o) for o in options], '-', target],
        stdin=stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True
    )
