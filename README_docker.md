Create and synchronize transcoded copies of audio folders.

* Transcodes FLAC files to MP3 with tags
* Copies everything else as-is
* Parallelized
* Additional runs synchronize changes since the initial run

# Usage

The Docker container uses harmonize as the entrypoint, passing any arguments to it.

You probably want to use the ``--user`` option to ensure the target files are
created with a specific UID and GID.

```
$ docker run \
    --user 1000:1000 \
    -v /media/flac:/media/flac \
    -v /media/mp3:/media/mp3 \
    nvllsvm/harmonize /media/flac /media/mp3
```

