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
logging.basicConfig(level=logging.DEBUG)
#logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
# Database initialization
conn = sqlite3.connect('/usr/src/app/database/files.db')
cursor = conn.cursor()
# Create files table
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
    """Retrieve items from a WebDAV directory."""
    url = f"{webdav_url}/{path}"
    response = requests.request("PROPFIND", url, auth=HTTPDigestAuth(webdav_login, webdav_password), headers={'Depth': '1'})
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

def notify_discord_new_folder(path):
    """Send a notification to Discord about a new folder."""
    foldername = os.path.basename(path)
    parent_info = get_parent_folders(path, coursefolders_path)
    if foldername:
        message = f"New folder detected:\nName: {foldername}\nParent Folders: {parent_info}"
        response = requests.post(discord_webhook, json={"content": message})
        if response.status_code == 204:
            logging.info(f"Notification sent to Discord for new folder: {foldername}")
        else:
            logging.error(f"Failed to send folder notification to Discord: {response.status_code}, {response.text}")

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
    response = requests.get(file_url, auth=HTTPDigestAuth(webdav_login, webdav_password))
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
        if discord_response.status_code == 204:
            logging.info(f"Notification sent to Discord for new file: {filename}")
        else:
            logging.error(f"Failed to send file notification to Discord: {discord_response.status_code}, {discord_response.text}")

        # Clean up the downloaded file
        os.remove(filename)
    else:
        logging.error(f"Failed to download file for Discord notification: {response.status_code}, {response.text}")

def process_webdav_directory(relative_path, processed_paths):
    """Process a WebDAV directory, checking for new files and directories."""
    if relative_path in processed_paths:
        return
    processed_paths.add(relative_path)

    items = get_webdav_items(relative_path)
    for href, is_directory in items:
        corrected_path = urllib.parse.unquote(href.replace(webdav_url, '').lstrip('/'))
        if corrected_path == relative_path or corrected_path in processed_paths:
            continue

        if is_directory:
            # This check avoids reprocessing the same folder
            if corrected_path not in processed_paths:
                notify_discord_new_folder(corrected_path)
                processed_paths.add(corrected_path)

            process_webdav_directory(corrected_path, processed_paths)
        else:
            process_file(corrected_path)


def process_file(path):
    """Process a single file, checking if it's new or updated."""
    url = f"{webdav_url}/{path}"
    response = requests.head(url, auth=HTTPDigestAuth(webdav_login, webdav_password))
    
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
    processed_paths = set()
    process_webdav_directory(coursefolders_path, processed_paths)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logging.error(f"Script encountered an error: {e}")
    finally:
        cursor.close()
        conn.close()

