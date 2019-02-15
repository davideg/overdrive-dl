# overdrive-dl
Command-line tool to download audiobooks from OverDrive

Download an OverDrive file (.odm) from your library (e.g. `book.odm`) and then call `python3 overdrive-dl.py book.odm` to download that book as mp3s. Currently it's hard-coded to save audiobook files in a place and format that works for me. Eventually it could be nice to make this configurable.

Requires Python 3 and [Requests](http://docs.python-requests.org)


```
python3 overdrive-dl.py --help
usage: overdrive-dl.py [-h] [-d] filename

positional arguments:
  filename

optional arguments:
  -h, --help   show this help message and exit
  -d, --debug  print debug messages
```

Wrote this to scratch my own itch. Inspired in parts by https://github.com/chbrown/overdrive and https://github.com/jvolkening/gloc
