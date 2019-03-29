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

from os.path import abspath, exists, expanduser
from mutagen.easyid3 import EasyID3

USER_AGENT = 'OverDrive Media Console'
USER_AGENT_LONG = 'OverDrive Media Console (unknown version)' \
        'CFNetwork/976 Darwin/18.2.0 (x86_64)'
OMC = '1.2.0'
OS = '10.14.2'
HASH_SECRET = 'ELOSNOC*AIDEM*EVIRDREVO'
CLIENT_ID_PATH = expanduser('~/.overdrive-dl.clientid')

# TODO: make into config file options
DOWNLOAD_DIR = expanduser('~/Documents/audiobooks/')
DOWNLOAD_PATH_FORMAT = '{author}/{title}/{filename}'
DOWNLOAD_FILENAME_FORMAT = 'part{number:02d}.mp3'
COVER_FILENAME_FORMAT = '{title}.jpg'
LOWERCASE = True
CHUNK_SIZE = 1024
TAGS_TO_UPDATE = {'genre': 'Audiobook'}
OWNER_USER = 'deg'
OWNER_GROUP = 'media'

def download_audiobook(odm_filename, update_tags=False, update_owner=False):
    license, client_id = _get_license_and_client_id(odm_filename)
    author, title, cover_url, base_url, parts = \
            _extract_author_title_urls_parts(odm_filename)
    num_parts = len(parts)

    download_dir = _construct_download_dir_path(author, title)
    logging.debug('Will save files to {}'.format(download_dir))
    if not exists(download_dir):
        logging.debug('Creating {}'.format(download_dir))
        os.makedirs(download_dir, exist_ok=True)

    logging.debug('Downloading using ODM file: {}'.format(odm_filename))
    if cover_url:
        logging.debug('Downloading cover image: {}'.format(cover_url))
        cover_path = download_dir + COVER_FILENAME_FORMAT.format(title=title)
        headers = {'User-Agent': USER_AGENT_LONG}
        r = requests.get(cover_url, headers=headers)
        if r.status_code == 200:
            with open(cover_path, 'wb') as fd:
                logging.debug('Saving as {}'.format(cover_path))
                fd.write(r.content)
        else:
            logging.debug('Could not download cover. Status code: {}'.format(
                r.status_code))
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
                + DOWNLOAD_FILENAME_FORMAT.format(
                        number=int(part.get('number')))
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
    if update_tags and TAGS_TO_UPDATE:
        _update_tags(TAGS_TO_UPDATE, download_dir, num_parts)

    # Update Owner info
    if update_owner and (OWNER_USER or OWNER_GROUP):
        _update_owner(OWNER_USER, OWNER_GROUP, download_dir, num_parts, title)

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
    
    if LOWERCASE:
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
                    + DOWNLOAD_FILENAME_FORMAT.format(
                        number=part)
            logging.debug('Updating tag for {}'.format(filepath))
            tag = EasyID3(filepath)
            for key in tags_to_update:
                tag[key] = tags_to_update[key]
            tag.save()

def _update_tags_only(tags_to_update, odm_filename):
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
    for part in range(1, num_parts+1):
        filepath = download_dir + DOWNLOAD_FILENAME_FORMAT.format(number=part)
        logging.debug('Updating owner for {}'.format(filepath))
        os.chown(filepath, user_id, group_id)
    # Update owner info for cover
    cover_path = download_dir + COVER_FILENAME_FORMAT.format(title=title)
    if os.path.exists(cover_path):
        logging.debug('Updating owner for cover image: {}'.format(
            cover_path))
        os.chown(cover_path, user_id, group_id)

def _update_owner_only(user, group, odm_filename):
    author, title, _, _, parts = _extract_author_title_urls_parts(odm_filename)
    num_parts = len(parts)
    download_dir = _construct_download_dir_path(author, title)
    _die_if_missing_files(download_dir, num_parts)
    _update_owner(user, group, download_dir, num_parts, title)

def _construct_download_dir_path(author, title):
    return DOWNLOAD_DIR + DOWNLOAD_PATH_FORMAT.format(
            author=author,
            title=title,
            filename='')

def _die_if_missing_files(dir_path, num_parts):
    for part in range(1, num_parts+1):
        filepath = dir_path + DOWNLOAD_FILENAME_FORMAT.format(number=part)
        if not exists(filepath):
            _die('Expected file "{}" does not exist'.format(filepath))

def _get_license_and_client_id(odm_filename):
    license = ''
    license_filepath = odm_filename + '.license'
    if not exists(license_filepath):
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
    if not exists(CLIENT_ID_PATH):
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
    args = parser.parse_args()
    log_level = logging.INFO
    if args.debug:
        log_level = logging.DEBUG
    _setup_logging(log_level)
    odm_filename = abspath(expanduser(args.filename))
    if args.skip_download and (args.tags + args.owner == 0):
        _die('Must include \'--tags\' or \'--owner options\''
                ' when specifying \'--skip-download\'')
    if args.skip_download:
        if args.tags:
            _update_tags_only(TAGS_TO_UPDATE, odm_filename)
        if args.owner:
            _update_owner_only(OWNER_USER, OWNER_GROUP, odm_filename)
    else:
        download_audiobook(
                odm_filename,
                update_tags=args.tags,
                update_owner=args.owner)
