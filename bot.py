import os
import sqlite3
import asyncio
import requests
import discord
from xml.etree import ElementTree
from datetime import datetime
import json
import logging
from requests.auth import HTTPDigestAuth

# Logging configuration
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')

# Environment Variables
webdav_url = os.getenv('WEBDAV_URL')
webdav_login = os.getenv('WEBDAV_LOGIN')
webdav_password = os.getenv('WEBDAV_PASSWORD')
discord_webhook_url = os.getenv('DISCORD_WEBHOOK')
coursefolders_path = os.getenv('COURSEFOLDERS_PATH') 

# Database Setup
try:
    db_connection = sqlite3.connect('database/files.db')
    db_cursor = db_connection.cursor()
    logging.info("Connected to SQLite database")
except sqlite3.Error as e:
    logging.error(f"SQLite error: {e}")

# Create table if it doesn't exist
try:
    db_cursor.execute('''
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_name TEXT,
            file_url TEXT,
            timestamp TEXT,
            author TEXT,
            status TEXT
        )
    ''')
    db_connection.commit()
    logging.info("SQLite table 'files' is ready")
except sqlite3.Error as e:
    logging.error(f"SQLite table creation error: {e}")

# Function to send Discord notification
def send_discord_notification(file_info, is_updated=False):
    message_content = {
        "content": f"{'Updated' if is_updated else 'New'} file detected:\n"
                   f"Name: {file_info['file_name']}\n"
                   f"URL: {file_info['file_url']}\n"
                   f"Timestamp: {file_info['timestamp']}\n"
    }
    try:
        response = requests.post(discord_webhook_url, data=json.dumps(message_content), headers={'Content-Type': 'application/json'})
        if response.status_code != 204:
            logging.warning(f"Failed to send message to Discord: {response.status_code}, {response.text}")
        else:
            logging.info("Message sent to Discord successfully")
    except requests.RequestException as e:
        logging.error(f"Error sending message to Discord: {e}")

def is_file(element):
    # If the 'resourcetype' tag contains 'collection', it's a directory
    resourcetype = element.find('.//{DAV:}resourcetype')
    if resourcetype is not None and resourcetype.find('{DAV:}collection') is None:
        return True  # It's a file
    return False  # It's a directory or something else

# Function to get file metadata from the WebDAV response element
def get_file_metadata(element):
    file_metadata = {}
    file_metadata['href'] = element.find('{DAV:}href').text
    file_metadata['creationdate'] = element.find('.//{DAV:}creationdate').text
    file_metadata['getlastmodified'] = element.find('.//{DAV:}getlastmodified').text
    file_metadata['getcontentlength'] = element.find('.//{DAV:}getcontentlength').text
    return file_metadata

# Function to process the WebDAV response and extract files metadata
def process_webdav_response(response_content):
    root = ElementTree.fromstring(response_content)
    files_metadata = []
    for element in root.findall('{DAV:}response'):
        if is_file(element):
            files_metadata.append(get_file_metadata(element))
    return files_metadata

# Function to fetch and process files from WebDAV
async def fetch_and_process_webdav_files():
    while True:
        try:
            response = requests.request("PROPFIND", webdav_url + '/' + coursefolders_path, auth=HTTPDigestAuth(webdav_login, webdav_password))
            if response.status_code == 207:
                root = ElementTree.fromstring(response.content)
                for response_elem in root.findall('{DAV:}response'):
                    href = response_elem.find('{DAV:}href').text
                    creationdate = response_elem.find('.//{DAV:}creationdate').text
                    displayname = response_elem.find('.//{DAV:}displayname').text

                    file_info = {'file_name': displayname, 'file_url': webdav_url + href, 'timestamp': creationdate, 'author': 'N/A'}
                    db_cursor.execute('SELECT * FROM files WHERE file_name = ?', (file_info['file_name'],))
                    db_file = db_cursor.fetchone()

                    if db_file:
                        if db_file[3] != file_info['timestamp']:  # Compare timestamps
                            db_cursor.execute('UPDATE files SET timestamp = ?, status = ? WHERE id = ?', (file_info['timestamp'], 'updated', db_file[0]))
                            db_connection.commit()
                            logging.info(f"File updated in database: {file_info['file_name']}")
                            send_discord_notification(file_info, is_updated=True)
                    else:
                        db_cursor.execute('INSERT INTO files (file_name, file_url, timestamp, author, status) VALUES (?, ?, ?, ?, ?)', 
                                          (file_info['file_name'], file_info['file_url'], file_info['timestamp'], file_info['author'], 'new'))
                        db_connection.commit()
                        logging.info(f"New file added to database: {file_info['file_name']}")
                        send_discord_notification(file_info)
            else:
                logging.error(f"Error fetching WebDAV files: HTTP {response.status_code}")
        except Exception as e:
            logging.error(f"Error in fetch_and_process_webdav_files: {e}")
        await asyncio.sleep(900)  # 15 minutes interval

# Main logic to start the process
async def main():
    await fetch_and_process_webdav_files()

# Run the main function
if __name__ == "__main__":
    logging.info("Starting WebDAV to Discord bot")
    asyncio.run(main())
