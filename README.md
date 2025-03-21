# cPanel Transfer Utility Web App

This repository provides a production-ready Flask web application for transferring cPanel accounts between servers. The web app allows administrators to migrate a cPanel account from a source server (with only cPanel access) to a destination server (with root access) while performing conflict checks for existing domains or usernames.

## Features

- **Secure Web Interface:** Built with Flask for a clean and responsive UI.
- **Conflict Detection:** Checks if the same domain or username exists on the destination server.
- **Overwrite Option:** Allows forced transfer if both the domain and username already exist.
- **Username Conflict Handling:** Prompts for a username change if the domain exists under a different username.
- **SSH Connectivity:** Uses Paramiko for secure remote command execution on the destination server.
- **Logging & Error Handling:** Provides detailed logging for production troubleshooting.

## Requirements

- Python 3.6 or later
- Flask (v2.2.2)
- Paramiko (v2.12.0)
- A destination server with root access and cPanel/WHM installed
- A source server with cPanel access
