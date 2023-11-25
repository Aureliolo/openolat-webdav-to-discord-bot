import logging
import os
import sqlite3
import time
import xml.etree.ElementTree as ET
from requests.auth import HTTPDigestAuth
import requests
import json
from urllib.parse import unquote

# Configure logging
logging.basicConfig(level=logging.DEBUG)

# Constants and global variables
webdav_url = os.getenv("WEBDAV_URL")
webdav_login = os.getenv("WEBDAV_LOGIN")
webdav_password = os.getenv("WEBDAV_PASSWORD")
discord_webhook = os.getenv("DISCORD_WEBHOOK")
visited_directories = set()

# SQLite connection
conn = sqlite3.connect('files.db')
cursor = conn.cursor()

def post_to_discord(message, file_path=None):
    """
    Post a message to Discord.
    """
    headers = {
        "Content-Type": "application/json"
    }
    payload = {
        "content": message
    }
    if file_path:
        files = {'file': open(file_path, 'rb')}
        response = requests.post(discord_webhook, data=payload, headers=headers, files=files)
    else:
        response = requests.post(discord_webhook, data=json.dumps(payload), headers=headers)
    
    if response.status_code != 204:
        logging.error(f"Failed to send message to Discord: {response.status_code}, {response.text}")

def process_webdav_directory(relative_path):
    """
    Process a given directory in the WebDAV server.
    """
    # Correct the path if it starts with 'webdav/'
    corrected_path = relative_path[len('webdav/'):] if relative_path.startswith('webdav/') else relative_path

    if corrected_path in visited_directories:
        return  # Skip processing if already visited

    visited_directories.add(corrected_path)
    full_url = f"{webdav_url}/{corrected_path.lstrip('/')}"
    logging.debug(f"Accessing WebDAV URL: {full_url}")
    response = requests.request(
        "PROPFIND",
        full_url,
        auth=HTTPDigestAuth(webdav_login, webdav_password),
        headers={'Depth': '1'}
    )

    if response.status_code != 207:
        logging.error(f"Failed to access WebDAV directory: {relative_path} with status code {response.status_code}")
        return

    root = ET.fromstring(response.content)
    for response_elem in root.findall('{DAV:}response'):
        href = response_elem.find('{DAV:}href').text
        resourcetype = response_elem.find('.//{DAV:}resourcetype')

        if resourcetype is not None and len(resourcetype):  # Directory
            relative_href = href.replace(webdav_url, '').lstrip('/')
            process_webdav_directory(relative_href)
        else:  # File
            file_name = unquote(href.split('/')[-1])
            logging.debug(f"Found file: {file_name}")
            post_to_discord(f"New file detected:\nName: {file_name}\nURL: {webdav_url}{href}")
            # Additional logic for SQLite and other operations can be included here
def initialize_database():
    """
    Initialize the SQLite database.
    """
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY,
        name TEXT,
        path TEXT,
        last_modified TEXT
    )
    ''')
    conn.commit()

def record_file_in_database(file_path, last_modified):
    """
    Record a file's details in the SQLite database.
    """
    cursor.execute('''
    INSERT INTO files (name, path, last_modified) VALUES (?, ?, ?)
    ''', (os.path.basename(file_path), file_path, last_modified))
    conn.commit()

def main():
    """
    Main function to start the WebDAV processing.
    """
    logging.info("Starting WebDAV directory processing")
    initialize_database()
    process_webdav_directory('coursefolders')  # Replace with your base directory

    # Add any other necessary logic here

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logging.info("Script interrupted by user")
    finally:
        conn.close()

