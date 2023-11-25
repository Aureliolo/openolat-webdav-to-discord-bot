import os
import sqlite3
import asyncio
import requests
import discord
import json
from xml.etree import ElementTree
from datetime import datetime

# Environment Variables
webdav_url = os.getenv('WEBDAV_URL')
webdav_login = os.getenv('WEBDAV_LOGIN')
webdav_password = os.getenv('WEBDAV_PASSWORD')
discord_webhook_url = os.getenv('DIRSCORD_WEBHOOK')
coursefolders_path = os.getenv('COURSEFOLDERS_PATH')  

# Database Setup
db_connection = sqlite3.connect('database/files.db')
db_cursor = db_connection.cursor()

# Create table if it doesn't exist
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

# Define the intents
#intents = discord.Intents.default()
# Initialize the Discord client with intents
#discord_client = discord.Client(intents=intents)

async def send_discord_notification(file_info, is_updated=False):
    # Create Discord message content
    message_content = {
        "content": f"{'Updated' if is_updated else 'New'} file detected:\n"
                   f"Name: {file_info['file_name']}\n"
                   f"URL: {file_info['file_url']}\n"
                   f"Timestamp: {file_info['timestamp']}\n"
    }

    # Send POST request to Discord webhook URL
    webhook_url = os.getenv('DISCORD_WEBHOOK')
    response = requests.post(webhook_url, data=json.dumps(message_content), headers={'Content-Type': 'application/json'})

    # Check response
    if response.status_code != 204:
        print(f"Failed to send message to Discord: {response.status_code}, {response.text}")

# Function to determine if a response element is a file
def is_file(element):
    # Check if the element represents a file (not a directory)
    # This can vary depending on the WebDAV server's response structure
    # Typically, a file will not have a <D:collection> tag in its <D:resourcetype>
    resourcetype = element.find('.//{DAV:}resourcetype')
    if resourcetype is not None and not list(resourcetype):
        return True
    return False

# Function to fetch and process files from WebDAV
async def fetch_and_process_webdav_files():
    while True:
        try:
            # Fetch files from WebDAV using ipv4 and digest authentication
            response = requests.request("PROPFIND", webdav_url + coursefolders_path, auth=(webdav_login, webdav_password))
            if response.status_code == 207:
                # Parse the XML response to extract file details
                root = ElementTree.fromstring(response.content)
                for response_elem in root.findall('{DAV:}response'):
                    if is_file(response_elem):
                        href = response_elem.find('{DAV:}href').text
                        creationdate = response_elem.find('.//{DAV:}creationdate').text
                        displayname = response_elem.find('.//{DAV:}displayname').text

                        file_info = {
                            'file_name': displayname,
                            'file_url': webdav_url + href,
                            'timestamp': creationdate,
                            'author': 'N/A'
                        }

                  # Check if file is in the database
                    db_cursor.execute('SELECT * FROM files WHERE file_name = ?', (file_info['file_name'],))
                    db_file = db_cursor.fetchone()

                    if db_file:
                        if db_file['timestamp'] != file_info['timestamp']:
                            # File is updated
                            db_cursor.execute('UPDATE files SET timestamp = ?, status = ? WHERE id = ?', 
                                              (file_info['timestamp'], 'updated', db_file['id']))
                            db_connection.commit()
                            await send_discord_notification(file_info, is_updated=True)
                    else:
                        # New file
                        db_cursor.execute('INSERT INTO files (file_name, file_url, timestamp, author, status) VALUES (?, ?, ?, ?, ?)', 
                                          (file_info['file_name'], file_info['file_url'], file_info['timestamp'], file_info['author'], 'new'))
                        db_connection.commit()
                        await send_discord_notification(file_info)

            else:
                print(f"Error fetching WebDAV files: {response.status_code}")
        except Exception as e:
            print(f"Error: {e}")
        await asyncio.sleep(900)  # 15 minutes interval

# Main logic to start the process
async def main():
    await fetch_and_process_webdav_files()

# Run the main function
if __name__ == "__main__":
    asyncio.run(main())
