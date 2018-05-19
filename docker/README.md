Create and synchronize transcoded copies of audio folders.

* Transcodes FLAC files to MP3 with tags
* Copies everything else as-is
* Parallelized
* Additional runs synchronize changes since the initial run

# Environment Variables

**Required**
- ``PUID`` - User ID to run as.
- ``PGID`` - Group ID to run as.

**Optional**
- ``NUM_PROCESSES`` - Number of processes to transcode and copy with (default 1).

# Volumes

- ``/source`` - Source directory
- ``/target`` - Target directory

# Usage

```
$ docker run \
    -e NUM_PROCESSES=8 \
    -e PUID=1000 \
    -e PGID=100 \
    -v /media/flac:/source \
    -v /media/mp3:/target \
    nvllsvm/harmonize
```

