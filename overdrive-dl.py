#!/usr/bin/env python3

import argparse
import base64
import grp
import hashlib
import logging
import math
import os
import pwd
import re
import sys
import time
import uuid
import xml.etree.ElementTree as ET 

import requests

from os.path import (abspath, basename, dirname, expanduser, getsize, isdir,
        isfile, join, normpath, realpath, sep)
from mutagen.easyid3 import EasyID3

CONFIG_FILE = join(dirname(realpath(__file__)), 'config.toml')
config = {'download_dir': '~/Documents/audiobooks/',
        'filenames_lowercase': True,
        'tags': {'genre': 'Audiobook'},
        'owner': {'user': 'deg', 'group': 'media'}}

USER_AGENT = 'OverDrive Media Console'
USER_AGENT_LONG = 'OverDrive Media Console (unknown version)' \
        'CFNetwork/976 Darwin/18.2.0 (x86_64)'
OMC = '1.2.0'
OS = '10.14.2'
HASH_SECRET = 'ELOSNOC*AIDEM*EVIRDREVO'
CLIENT_ID_PATH = expanduser('~/.overdrive-dl.clientid')

# TODO: make path format into config file option
DOWNLOAD_PATH_FORMAT = '{author}/{title}/{filename}'
DOWNLOAD_FILENAME_FORMAT = 'part{number:02d}.mp3'
COVER_FILENAME_FORMAT = '{title}.jpg'
CHUNK_SIZE = 1024

def download_audiobook(
        odm_filename,
        update_tags=False,
        update_owner=False,
        force_download=False):
    _verify_odm_file(odm_filename)
    license, client_id = _get_license_and_client_id(odm_filename)
    author, title, cover_url, base_url, parts = \
            _extract_author_title_urls_parts(odm_filename)
    num_parts = len(parts)

    download_dir = _construct_download_dir_path(author, title)
    logging.debug('Will save files to {}'.format(download_dir))
    if not isdir(download_dir):
        logging.debug('Creating {}'.format(download_dir))
        os.makedirs(download_dir, exist_ok=True)

    logging.debug('Downloading using ODM file: {}'.format(odm_filename))
    if cover_url:
        logging.debug('Downloading cover image: {}'.format(cover_url))
        cover_path = download_dir + sep \
                + COVER_FILENAME_FORMAT.format(title=title)
        if _file_exists(cover_path):
            logging.info('Cover image {} already exists'.format(cover_path))
            if force_download:
                logging.info('Overwriting cover image {}'.format(cover_path))
                _download_cover_image(cover_url, cover_path)
            else:
                logging.debug('Skipping downloading cover image')
        else:
            _download_cover_image(cover_url, cover_path)
    logging.debug('Using ClientID: {}'.format(client_id))

    headers = {
        'License': license,
        'ClientID': client_id,
        'User-Agent': USER_AGENT
        }
    logging.info('Downloading {} parts:'.format(num_parts))
    for part in parts:
        logging.info('Downloading {} of {}'.format(
            part.get('name'),
            num_parts))
        logging.debug('Filename: {}\nFilesize: {}\nDuration: {}'.format(
                part.get('filename'),
                part.get('filesize'),
                part.get('duration')))
        dl_url = base_url + '/' + part.get('filename')
        filepath = download_dir \
                + sep \
                + DOWNLOAD_FILENAME_FORMAT.format(
                        number=int(part.get('number')))
        filesize = int(part.get('filesize'))
        if _file_exists(filepath, filesize):
            logging.info('{} already exists'.format(part.get('name')) \
                    + ' with expected size' \
                    + ' {:.2f}MB: {}'.format(filesize/(1024.0*1024.0), filepath))
            if not force_download:
                logging.info('Skipping downloading {}'.format(
                    part.get('name')))
                continue
            else:
                logging.info('Overwriting file {}'.format(filepath))

        r = requests.get(dl_url, headers=headers, stream=True)
        total_bytes = int(r.headers.get('content-length'))
        expected_iterations = int(math.ceil(total_bytes / CHUNK_SIZE))
        downloaded_bytes = 0
        with open(filepath, 'wb') as fd:
            start_time = time.time()
            for it, chunk in enumerate(r.iter_content(chunk_size=CHUNK_SIZE)):
                fd.write(chunk)
                now = time.time()
                bytes_downloaded = len(chunk)
                elapsed = now - start_time
                downloaded_bytes += bytes_downloaded
                percent = downloaded_bytes / total_bytes * 100
                avg_speed = downloaded_bytes / elapsed
                est_total = total_bytes / avg_speed
                est_eta = (total_bytes - downloaded_bytes) / avg_speed
                progress_str = '[{:.2f}%] {} / {}  {:.1f}s/{:.1f}s' \
                        '  {:.2f}B/s    {:.1f}s eta'.format(
                                percent,
                                downloaded_bytes,
                                total_bytes,
                                elapsed,
                                est_total,
                                avg_speed,
                                est_eta)
                if downloaded_bytes != CHUNK_SIZE:
                    # not first iteration
                    progress_str = '\033[G' + progress_str 
                if it + 1 == expected_iterations:
                    # last iteration
                    progress_str += '\n'
                sys.stdout.write(progress_str)
                sys.stdout.flush()
                # TODO look into using tqdm as progress bar

    # Update ID3 tags
    if update_tags and 'tags' in config:
        _update_tags(config['tags'], download_dir, num_parts)

    # Update Owner info
    if update_owner and 'owner' in config:
        _update_owner(config['owner'].get('user'),
                config['owner'].get('group'),
                download_dir,
                num_parts,
                title)

def _download_cover_image(cover_url, cover_path):
    headers = {'User-Agent': USER_AGENT_LONG}
    r = requests.get(cover_url, headers=headers)
    if r.status_code == 200:
        with open(cover_path, 'wb') as fd:
            logging.debug('Saving as {}'.format(cover_path))
            fd.write(r.content)
    else:
        logging.debug('Could not download cover. Status code: {}'.format(
            r.status_code))

def _extract_author_title_urls_parts(odm_filename):
    odm_str = ''
    with open(odm_filename, 'r') as fd:
        odm_str = fd.read()

    m = re.search(r'<Metadata>.*</Metadata>', odm_str, flags=re.S)
    if not m:
        _die('Could not find Metadata in {}'.format(odm_filename))
    metadata = ET.fromstring(m.group(0))
    author_elements = metadata.findall('.//Creator[@role="Author"]')
    author = ';'.join([e.text for e in author_elements])
    # Use editors if there are no authors
    if author == '':
        author_elements = metadata.findall('.//Creator[@role="Editor"]')
        author = ';'.join([e.text for e in author_elements])
    title = metadata.findtext('Title')
    cover_url = metadata.findtext('CoverUrl', '')
    logging.info('Got title "{}" and author'.format(title)
                 + ('s' if ';' in author else '')
                 + ' {} from ODM file {}'.format(
                     ', '.join(author.split(';')),
                     basename(odm_filename)))
    
    if config['filenames_lowercase']:
        author = author.lower()
        title = title.lower()

    root = ET.fromstring(odm_str)
    # Find the Protocol element with the URL for downloading
    p = root.find('.//Protocol[@method="download"]')
    base_url = p.get('baseurl', default='') if p is not None else ''
    if not base_url:
        _die('Trouble extracting URL from ODM file')

    p = root.find('.//Parts')
    num_parts = int(p.get('count', default=0)) if p is not None else 0
    # Find all the parts to download
    parts = root.findall('.//Part')
    if len(parts) != num_parts:
        _die('Bad ODM file: Expecting {} parts, but found {}'
        'part records'.format(num_parts, len(parts)))
    return (author, title, cover_url, base_url, parts)

def _update_tags(tags_to_update, download_dir, num_parts):
        logging.info('Updating ID3 tags')
        for part in range(1, num_parts+1):
            filepath = download_dir \
                    + sep \
                    + DOWNLOAD_FILENAME_FORMAT.format(
                        number=part)
            logging.debug('Updating tag for {}'.format(filepath))
            tag = EasyID3(filepath)
            for key in tags_to_update:
                tag[key] = tags_to_update[key]
            tag.save()

def _update_tags_only(tags_to_update, odm_filename):
    _verify_odm_file(odm_filename)
    author, title, _, _, parts = _extract_author_title_urls_parts(odm_filename)
    num_parts = len(parts)
    download_dir = _construct_download_dir_path(author, title)
    _die_if_missing_files(download_dir, num_parts)
    _update_tags(tags_to_update, download_dir, num_parts)

def _update_owner(user, group, download_dir, num_parts, title):
    logging.info('Updating file owner info')
    if user:
        try:
            user_id = pwd.getpwnam(user).pw_uid
        except KeyError:
            user_id = -1
    else:
        user_id = -1
    if group:
        try:
            group_id = grp.getgrnam(group).gr_gid
        except KeyError:
            group_id = -1
    else:
        group_id = -1
    # Update owner for author directory
    author_dir = dirname(download_dir)
    logging.debug('Updating owner for {}'.format(author_dir))
    os.chown(author_dir, user_id, group_id)
    # Update owner for title directory
    logging.debug('Updating owner for {}'.format(download_dir))
    os.chown(download_dir, user_id, group_id)
    # Update owner for audiobook files
    for part in range(1, num_parts+1):
        filepath = download_dir \
                + sep \
                + DOWNLOAD_FILENAME_FORMAT.format(number=part)
        logging.debug('Updating owner for {}'.format(filepath))
        os.chown(filepath, user_id, group_id)
    # Update owner info for cover
    cover_path = download_dir \
            + sep \
            + COVER_FILENAME_FORMAT.format(title=title)
    if os.path.isfile(cover_path):
        logging.debug('Updating owner for cover image: {}'.format(
            cover_path))
        os.chown(cover_path, user_id, group_id)

def _update_owner_only(user, group, odm_filename):
    _verify_odm_file(odm_filename)
    author, title, _, _, parts = _extract_author_title_urls_parts(odm_filename)
    num_parts = len(parts)
    download_dir = _construct_download_dir_path(author, title)
    _die_if_missing_files(download_dir, num_parts)
    _update_owner(user, group, download_dir, num_parts, title)

def _construct_download_dir_path(author, title):
    return abspath(expanduser(config['download_dir'])
            + sep
            + DOWNLOAD_PATH_FORMAT.format(
                    author=author,
                    title=title,
                    filename=''))

def _file_exists(file_path, expected_size_bytes=None):
    does_file_exist = isfile(file_path) \
            and (expected_size_bytes is None
                    or getsize(file_path) == expected_size_bytes)
    logging.debug('File \"{}\" exists'.format(file_path) \
            + (' with size {} bytes?'.format(expected_size_bytes)
            if expected_size_bytes
            else '?') \
            + ' {}'.format(does_file_exist))
    return does_file_exist

def _die_if_missing_files(dir_path, num_parts):
    if not isdir(dir_path):
        _die('Expected to find directory "{}",'
                ' but it does not exist'.format(dir_path))
    for part in range(1, num_parts+1):
        filepath = normpath(dir_path) \
                + sep \
                + DOWNLOAD_FILENAME_FORMAT.format(number=part)
        if not isfile(filepath):
            _die('Expected file "{}" does not exist'.format(filepath))

def _verify_odm_file(odm_filename):
    logging.debug('Attempting to verify ODM file "{}"'.format(odm_filename))
    if isfile(odm_filename):
        with open(odm_filename, 'r') as f:
            if not re.search(r'<OverDriveMedia', f.read(100)):
                _die('Expected ODM file. Specified file "{}"'
                        ' is not in the correct OverDriveMedia'
                        ' format'.format(basename(odm_filename)))
    elif isdir(odm_filename):
        _die('Expected ODM file. Given directory: {}'.format(
            basename(odm_filename)))
    else:
        _die('Expected ODM file. Specified file "{}"'
                ' does not exist'.format(basename(odm_filename)))

def _get_license_and_client_id(odm_filename):
    license = ''
    license_filepath = odm_filename + '.license'
    if not isfile(license_filepath):
        license = acquire_license(odm_filename)
        logging.debug('Writing to license file: {}'.format(license_filepath))
        with open(license_filepath, 'w') as fd:
            fd.write(license)
    else:
        logging.debug('Reading from license file: {}'.format(license_filepath))
        with open(license_filepath, 'r') as fd:
            license = fd.read()
    if not license:
        _die('Missing license content')
    license_xml = ET.fromstring(license)
    client_id = license_xml.findtext(
            './{http://license.overdrive.com/2008/03/License.xsd}SignedInfo'
            '/{http://license.overdrive.com/2008/03/License.xsd}ClientID')
    if not client_id:
        _die('Failed to extract ClientID from License')
    return (license, client_id)

def _generate_hash(client_id):
    """Hash algorithm and secret complements of
    https://github.com/jvolkening/gloc/blob/v0.601/gloc#L1523-L1531"""
    rawhash = '|'.join([client_id, OMC, OS, HASH_SECRET])
    return base64.b64encode(hashlib.sha1(rawhash.encode('utf-16-le')).digest())

def acquire_license(odm_filename):
    logging.debug('Acquiring license')
    tree = ET.parse(odm_filename)
    root = tree.getroot()
    acquisition_url = root.findtext('./License/AcquisitionUrl')
    logging.debug('Using AcquisitionUrl: {}'.format(acquisition_url))
    media_id = root.attrib.get('id', '')
    logging.debug('Using MediaID: {}'.format(media_id))

    client_id = ''
    if not isfile(CLIENT_ID_PATH):
        # Generate random Client ID
        client_id = str(uuid.uuid4()).upper()
        with open(CLIENT_ID_PATH, 'w') as fd:
            fd.write(client_id)
    else:
        with open(CLIENT_ID_PATH, 'r') as fd:
            client_id = fd.read()
    logging.debug('Using ClientID: {}'.format(client_id))

    hsh = _generate_hash(client_id)
    logging.debug('Using Hash: {}'.format(hsh))
    
    headers = {'User-Agent': USER_AGENT}
    payload = {
        'MediaID': media_id,
        'ClientID': client_id,
        'OMC': OMC,
        'OS': OS,
        'Hash': hsh}
    r = requests.get(acquisition_url, params=payload, headers=headers)
    if r.status_code == 200:
        return r.text
    else:
        _die('Failed to acquire License for {}'.format(odm_filename))

def _load_config(config_file):
    global config
    try:
        import toml
        if isfile(config_file):
            config = toml.load(config_file)
        else:
            logging.warning('No configuration file "{}" found.' \
                    ' Using hard-coded defaults.'.format(config_file))
    except ModuleNotFoundError:
        logging.warning('Python TOML library not installed so configuration' 
                ' files will not work. Check out https://github.com/uiri/toml')
    
def _setup_logging(level):
    logging.basicConfig(
            format='%(asctime)s - %(levelname)s - %(message)s',
            level=level)

def _die(msg):
    sys.stderr.write('ERROR: ' + msg + '\n')
    sys.exit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('filename')
    parser.add_argument(
            '-d', '--debug', action='store_true', help='print debug messages')
    parser.add_argument(
            '-t', '--tags', action='store_true',
            help='Update ID3 tags according to configuration')
    parser.add_argument(
            '-o', '--owner', action='store_true',
            help='Update file owner according to configuration')
    parser.add_argument(
            '-s', '--skip-download', action='store_true',
            help='Skip downloading files. This option is only valid'
            ' when updating tags or owner, in which case it is assumed'
            ' the expected files already exist')
    parser.add_argument(
            '-f', '--force', action='store_true',
            help='Ignore whether audiobook files already exist'
            ' and download all files, replacing any existing files')
    parser.add_argument(
            '-c', '--config', help='Specify configuration file in TOML format'
            ' (see https://github.com/toml-lang/toml).'
            ' Without specifying this flag, %(prog)s will look for'
            ' file named config.toml to read configuration')
    args = parser.parse_args()
    log_level = logging.INFO
    if args.debug:
        log_level = logging.DEBUG
    _setup_logging(log_level)
    odm_filename = abspath(expanduser(args.filename))
    if args.skip_download and (args.tags + args.owner == 0):
        _die('Must include \'--tags\' or \'--owner\' options'
                ' when specifying \'--skip-download\'')
    config_file = args.config if args.config else CONFIG_FILE
    # modifies global config variable with configuration from file
    _load_config(config_file)
    if args.skip_download:
        if args.tags and 'tags' not in config:
            logging.error('Specified \'--skip-download\' and \'--tags\''
                    ' but no tags have been specified in the configuration'
                    ' file {}'.format(config_file))
        if args.owner and 'owner' not in config:
            logging.error('Specified \'--skip-download\' and \'--owner\''
                    ' but no owner information has been specified in the'
                    ' configuration file {}'.format(config_file))
        if args.tags and 'tags' in config:
                _update_tags_only(config['tags'], odm_filename)
        if args.owner and 'owner' in config:
            _update_owner_only(config['owner'].get('user'),
                    config['owner'].get('group'),
                    odm_filename)
    else:
        download_audiobook(
                odm_filename,
                update_tags=args.tags,
                update_owner=args.owner,
                force_download=args.force)
