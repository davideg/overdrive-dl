# overdrive-dl
Command-line tool to download audiobooks from OverDrive

Download an OverDrive file (.odm) from your library (e.g. `book.odm`) and then call `python3 overdrive-dl.py book.odm` to download that book as mp3s. Currently it's hard-coded to save audiobook files in a place and format that works for me. Eventually it could be nice to make this configurable.

Also includes functionality for updating ID3 tags and changing the owner and group of the files (assuming a Unix-based OS).

Requires:
- [Python 3](https://docs.python.org/3/)
- [Requests](http://docs.python-requests.org)
- [Mutagen](https://mutagen.readthedocs.io)


```
python3 overdrive-dl.py --help
usage: overdrive-dl.py [-h] [-d] [-t] [-o] [-s] filename

positional arguments:
  filename

optional arguments:
  -h, --help           show this help message and exit
  -d, --debug          print debug messages
  -t, --tags           Update ID3 tags according to configuration
  -o, --owner          Update file owner according to configuration
  -s, --skip-download  Skip downloading files. This option is only valid when
                       updating tags or owner, in which
```

Wrote this to scratch my own itch. Inspired in parts by https://github.com/chbrown/overdrive and https://github.com/jvolkening/gloc
