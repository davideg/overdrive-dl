#!/usr/bin/env python3

import argparse
import base64
import hashlib
import logging
import math
import os
import re
import sys
import time
import uuid
import xml.etree.ElementTree as ET 

import requests

from os.path import abspath, exists, expanduser

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


def download_audiobook(odm_filename):
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

    odm_str = ''
    with open(odm_filename, 'r') as fd:
        odm_str = fd.read()

    m = re.search(r'<Metadata>.*</Metadata>', odm_str, flags=re.S)
    if not m:
        _die('Could not find Metadata in {}'.format(odm_filename))
    metadata = ET.fromstring(m.group(0))
    author_elements = metadata.findall('.//Creator[@role="Author"]')
    author = ';'.join([e.text for e in author_elements])
    title = metadata.findtext('Title')
    cover_url = metadata.findtext('CoverUrl', '')
    
    if LOWERCASE:
        author = author.lower()
        title = title.lower()

    download_dir = DOWNLOAD_DIR + DOWNLOAD_PATH_FORMAT.format(
            author=author,
            title=title,
            filename='')
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

    root = ET.fromstring(odm_str)
    # Find the Protocol element with the URL for downloading
    p = root.find('.//Protocol[@method="download"]')
    url = p.get('baseurl', default='') if p is not None else ''
    if not url:
        _die('Trouble extracting URL from ODM file')

    p = root.find('.//Parts')
    num_parts = int(p.get('count', default=0)) if p is not None else 0
    # Find all the parts to download
    parts = root.findall('.//Part')
    if len(parts) != num_parts:
        _die('Bad ODM file: Expecting {} parts, but found {}'
        'part records'.format(num_parts, len(parts)))

    headers = {
        'License': license,
        'ClientID': client_id,
        'User-Agent': USER_AGENT
        }
    for part in parts:
        logging.info('Downloading {}'.format(part.get('name')))
        logging.debug('Filename: {}\nFilesize: {}\nDuration: {}'.format(
                part.get('filename'),
                part.get('filesize'),
                part.get('duration')))
        dl_url = url + '/' + part.get('filename')
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
    logging.error(msg)
    sys.exit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('filename')
    parser.add_argument(
            '-d', '--debug', action='store_true', help='print debug messages')
    args = parser.parse_args()
    log_level = logging.INFO
    if args.debug:
        log_level = logging.DEBUG
    _setup_logging(log_level)
    odm_filename = abspath(expanduser(args.filename))
    download_audiobook(odm_filename)