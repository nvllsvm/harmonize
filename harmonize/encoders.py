import asyncio
import os


async def lame(stdin_pipe, target, options=[]):
    proc = await asyncio.create_subprocess_exec(
        'lame', '--quiet', *[str(o) for o in options], '-', target,
        stdin=stdin_pipe,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE)
    os.close(stdin_pipe)

    await proc.wait()

    # Errors happen even if exit code is 0
    stderr = await proc.stderr.read()
    if proc.returncode or stderr:
        raise asyncio.subprocess.CalledProcessError(
            proc.returncode,
            proc.args,
            output=proc.stdout.read(),
            proc=stderr
        )


async def opus(stdin_pipe, target, options=[]):
    proc = await asyncio.create_subprocess_exec(
        'opusenc', '--quiet', *[str(o) for o in options], '-', target,
        stdin=stdin_pipe)
    os.close(stdin_pipe)

    await proc.wait()

    if proc.returncode:
        raise asyncio.subprocess.CalledProcessError(
            proc.returncode,
            proc.args,
            output=await proc.stdout.read(),
            proc=await proc.stderr.read(),
        )
