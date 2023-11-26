
import os
import logging
import sqlite3
import requests
from requests.auth import HTTPDigestAuth
import xml.etree.ElementTree as ET
import urllib.parse
import time

# Environment variables
webdav_url = os.getenv("WEBDAV_URL")
webdav_login = os.getenv("WEBDAV_LOGIN")
webdav_password = os.getenv("WEBDAV_PASSWORD")
discord_webhook = os.getenv("DISCORD_WEBHOOK")
coursefolders_path = os.getenv("COURSEFOLDERS_PATH")

# Logging configuration
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Session initialization for preemptive digest authentication
def initialize_session():
    global session
    session = requests.Session()
    session.auth = HTTPDigestAuth(webdav_login, webdav_password)

# Initialize session
initialize_session()

# Function to handle requests with session checks
def make_authenticated_request(method, url, **kwargs):
    global session
    response = session.request(method, url, **kwargs)
    if response.status_code == 401:
        initialize_session()
        response = session.request(method, url, **kwargs)
        if response.status_code == 401:
            raise Exception("Failed to re-authenticate")
    return response

# Database initialization
conn = sqlite3.connect('/usr/src/app/database/files.db')
cursor = conn.cursor()
cursor.execute('''
    CREATE TABLE IF NOT EXISTS files (
        path TEXT PRIMARY KEY,
        last_modified TEXT,
        size TEXT
    )
''')

# Create folders table
cursor.execute('''
    CREATE TABLE IF NOT EXISTS folders (
        path TEXT PRIMARY KEY
    )
''')

conn.commit()

def get_webdav_items(path):
    logging.debug(f"Getting WebDAV items for path: {path}")
    url = f"{webdav_url}/{path}"
    response = make_authenticated_request("PROPFIND", url, headers={'Depth': '1'})
    if response.status_code != 207:
        logging.error(f"Failed to access WebDAV directory: {path} with status code {response.status_code}")
        return []
    tree = ET.fromstring(response.content)
    items = []
    for response in tree.findall('{DAV:}response'):
        href = response.find('{DAV:}href').text
        is_directory = response.find('.//{DAV:}collection') is not None
        items.append((href, is_directory))
    return items

def get_parent_folders(path, base_path):
    """Return a string representing the parent folders of a given path, excluding the base path."""
    if path.startswith(base_path):
        path = path[len(base_path):].lstrip('/')
    folders = path.split('/')
    if len(folders) > 1:
        return ' -> '.join(folders[:-1])
    return "Root"

def notify_discord_new_folder(folder_path):
    # Remove the base path from the folder path
    display_path = folder_path.replace(coursefolders_path, '').lstrip('/').rstrip('/')
    if not display_path:  # Skip notification if the path is just the base path
        return

    # Check if the folder is already in the database
    cursor.execute("SELECT path FROM folders WHERE path = ?", (folder_path,))
    if cursor.fetchone() is not None:
        # Folder already processed
        logging.debug(f"Folder already processed: {folder_path}")
        return

    # Construct the message for Discord
    message = {
        "content": f"New folder detected: {display_path}"
    }

    # Send the notification to Discord
    discord_response = requests.post(discord_webhook, json=message)
    if discord_response.status_code in [200, 204]:
        logging.info(f"Notification sent to Discord for new folder: {display_path}")
        # Record the folder in the database
        cursor.execute("INSERT INTO folders (path) VALUES (?)", (folder_path,))
        conn.commit()
    else:
        logging.error(f"Failed to send folder notification to Discord: {discord_response.status_code}, {discord_response.text}")

def get_folder_path(path, base_path):
    """Return the folder path excluding the base path."""
    if path.startswith(base_path):
        path = path[len(base_path):].lstrip('/')
    return os.path.dirname(path)

def notify_discord_new_file(path):
    """Send a notification to Discord about a new file with the file attached."""
    folder_path = get_folder_path(path, coursefolders_path)
    file_url = f"{webdav_url}/{urllib.parse.quote(path)}"
    filename = os.path.basename(path)

    # Download the file to attach it to Discord
    response = make_authenticated_request("GET", file_url)
    if response.status_code == 200:
        with open(filename, 'wb') as f:
            f.write(response.content)

        # Preparing Discord message
        message = {
            "content": f"New file detected in folder: {folder_path}\nName: {filename}"
        }
        files = {
            "file": (filename, open(filename, 'rb'))
        }

        # Sending the message
        discord_response = requests.post(discord_webhook, data=message, files=files)
        if discord_response.status_code in [200, 204]:
            logging.info(f"Notification sent to Discord for new file: {filename}")
        else:
            logging.error(f"Failed to send file notification to Discord: {discord_response.status_code}, {discord_response.text}")

        # Clean up the downloaded file
        os.remove(filename)
    else:
        logging.error(f"Failed to download file for Discord notification: {response.status_code}, {response.text}")


def process_webdav_directory(relative_path, processed_paths):
    logging.debug(f"Entering directory: {relative_path}")
    if relative_path in processed_paths:
        logging.debug(f"Already processed: {relative_path}")
        return
    processed_paths.add(relative_path)

    items = get_webdav_items(relative_path)
    for href, is_directory in items:
        corrected_path = urllib.parse.unquote(href.replace(webdav_url, '').lstrip('/'))
        logging.debug(f"Found item: {corrected_path}, Is directory: {is_directory}")

        if corrected_path == relative_path or corrected_path in processed_paths:
            logging.debug(f"Skipping: {corrected_path}")
            continue

        # Adjusted to handle path correctly
        if corrected_path.startswith('webdav/'):
            corrected_path = corrected_path[len('webdav/'):]

        if is_directory:
            logging.debug(f"Processing subdirectory: {corrected_path}")
            if corrected_path not in processed_paths:
                notify_discord_new_folder(corrected_path)

            process_webdav_directory(corrected_path, processed_paths)
        else:
            process_file(corrected_path)

def process_file(path):
    logging.debug(f"Processing file: {path}")
    url = f"{webdav_url}/{path}"
    response = make_authenticated_request("HEAD", url)

    if response.status_code != 200:
        logging.error(f"Failed to access file: {path} with status code {response.status_code}")
        return

    last_modified = response.headers.get('Last-Modified', None)
    cursor.execute("SELECT last_modified FROM files WHERE path = ?", (path,))
    result = cursor.fetchone()

    if not result:
        # New file
        notify_discord_new_file(path)
        cursor.execute("INSERT INTO files (path, last_modified) VALUES (?, ?)", (path, last_modified))
    elif result[0] != last_modified:
        # File updated
        notify_discord_updated_file(path)
        cursor.execute("UPDATE files SET last_modified = ? WHERE path = ?", (last_modified, path))

    conn.commit()

def notify_discord_updated_file(path):
    """Send a notification to Discord about an updated file."""
    filename = os.path.basename(path)
    file_url = f"{webdav_url}/{urllib.parse.quote(path)}"
    message = f"File updated:\nName: {filename}\nURL: {file_url}\nLast Modified: {last_modified}"
    discord_response = requests.post(discord_webhook, data=message, files=files)
    if discord_response.status_code == 200 or discord_response.status_code == 204:
        logging.info(f"Notification sent to Discord for new file: {filename}")
    else:
        logging.error(f"Failed to send file notification to Discord: {discord_response.status_code}, {discord_response.text}")
    os.remove(filename)


def main():
    while True:
        processed_paths = set()
        process_webdav_directory(coursefolders_path, processed_paths)

        logging.info("Waiting for 15 minutes before next run.")
        time.sleep(900)  # Wait for 900 seconds (30 minutes)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logging.info("Script interrupted by user")
    except Exception as e:
        logging.error(f"An error occurred: {e}")
