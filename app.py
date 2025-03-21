import os
import logging
import traceback
import time
import requests
import paramiko
import urllib3

from flask import Flask, render_template, request, redirect, flash, url_for

# Disable insecure request warnings for self-signed certificates.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'default_secret_key')

# Configure logging for production
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def check_destination_account(destination_host, destination_root_user, destination_root_pass, domain, username):
    """
    Connects via SSH to the destination server and checks if an account exists.
    Uses /scripts/whoowns for the username and searches /var/cpanel/users for the domain.
    
    Returns:
      - "overwrite_allowed": account exists with the same username and domain.
      - "username_conflict": domain exists but under a different username.
      - "domain_conflict": only the domain exists.
      - "no_conflict": no conflicts detected.
      - "connection_error": unable to connect to the destination.
    """
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        logger.info("Connecting to destination server: %s", destination_host)
        ssh.connect(destination_host, username=destination_root_user, password=destination_root_pass, timeout=10)

        # Check if the username exists
        cmd_username = f"/scripts/whoowns {username}"
        logger.info("Executing command: %s", cmd_username)
        stdin, stdout, stderr = ssh.exec_command(cmd_username)
        result_username = stdout.read().decode().strip()

        # Check if the domain exists by searching through /var/cpanel/users
        cmd_domain = f"grep -R '{domain}' /var/cpanel/users"
        logger.info("Executing command: %s", cmd_domain)
        stdin, stdout, stderr = ssh.exec_command(cmd_domain)
        result_domain = stdout.read().decode().strip()

        ssh.close()

        if result_username and result_domain:
            if username in result_domain:
                return "overwrite_allowed"
            else:
                return "username_conflict"
        elif result_domain:
            return "domain_conflict"
        else:
            return "no_conflict"

    except Exception as e:
        logger.error("Error checking destination account: %s", e)
        logger.error(traceback.format_exc())
        return "connection_error"

def transfer_account(source_host, source_user, source_pass, destination_host, destination_root_user,
                     destination_root_pass):
    """
    Transfers a cPanel account by:
      1. Triggering a full backup on the source cPanel server via its HTTPS API.
      2. Polling for the backup's download URL.
      3. Downloading the backup file to the local destination /home directory,
         using the original filename (do not rename it).
      4. Uploading the backup file to the destination server via SFTP.
      5. Executing the restore command (/scripts/restorepkg) on the destination and capturing progress.
      
    Returns a tuple (success:bool, progress_output:str).
    """
    try:
        # --- Step 1: Trigger Backup on Source cPanel ---
        backup_api_url = f"https://{source_host}:2083/execute/Backup/fullbackup?api.version=1"
        logger.info("Triggering backup creation on source server: %s", source_host)
        trigger_resp = requests.get(backup_api_url, auth=(source_user, source_pass), verify=False)
        if trigger_resp.status_code != 200:
            logger.error("Failed to trigger backup. Status code: %s, Response: %s",
                         trigger_resp.status_code, trigger_resp.text)
            return (False, "Failed to trigger backup on source server.")

        # --- Step 2: Poll for Backup File URL ---
        logger.info("Polling for backup file URL...")
        download_url = None
        timeout = 600  # seconds
        interval = 10  # seconds
        elapsed = 0

        while elapsed < timeout:
            time.sleep(interval)
            elapsed += interval
            poll_resp = requests.get(backup_api_url, auth=(source_user, source_pass), verify=False)
            if poll_resp.status_code != 200:
                logger.error("Error polling backup API. Status code: %s, Response: %s",
                             poll_resp.status_code, poll_resp.text)
                continue
            json_data = poll_resp.json()
            download_url = json_data.get("data", {}).get("download_url")
            if download_url:
                logger.info("Backup ready. Download URL: %s", download_url)
                break
            else:
                logger.info("Backup not ready yet. Elapsed time: %s seconds", elapsed)
        if not download_url:
            logger.error("Backup file was not ready after %s seconds", timeout)
            return (False, "Backup file was not ready in time.")

        # --- Step 3: Download Backup File to /home ---
        # Extract the original filename from the download URL.
        filename = os.path.basename(download_url)
        backup_local_path = f"/home/{filename}"
        logger.info("Downloading backup file to: %s", backup_local_path)
        backup_resp = requests.get(download_url, auth=(source_user, source_pass), verify=False, stream=True)
        if backup_resp.status_code != 200:
            logger.error("Failed to download backup file. Status code: %s", backup_resp.status_code)
            return (False, "Failed to download backup file.")
        with open(backup_local_path, 'wb') as f:
            for chunk in backup_resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        logger.info("Backup file downloaded successfully to %s", backup_local_path)

        # --- Step 4: Upload Backup File to Destination via SFTP ---
        logger.info("Connecting to destination server for SFTP upload: %s", destination_host)
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(destination_host, username=destination_root_user, password=destination_root_pass, timeout=10)
        sftp = ssh.open_sftp()
        # Upload to /home/ keeping the original filename.
        remote_backup_path = backup_local_path
        logger.info("Uploading backup file to destination at %s", remote_backup_path)
        sftp.put(backup_local_path, remote_backup_path)
        sftp.close()

        # --- Step 5: Execute Restore Command and Capture Progress ---
        restore_cmd = f"/scripts/restorepkg {remote_backup_path}"
        logger.info("Executing restore command: %s", restore_cmd)
        channel = ssh.get_transport().open_session()
        # Request a pseudo-terminal to capture live output.
        channel.get_pty()
        channel.exec_command(restore_cmd)

        progress_output = ""
        # Read output in real time until command finishes.
        while True:
            if channel.recv_ready():
                data = channel.recv(1024).decode()
                progress_output += data
                logger.info(data.strip())
            if channel.exit_status_ready():
                break
            time.sleep(1)  # slight delay to avoid tight loop

        exit_status = channel.recv_exit_status()
        ssh.close()

        if exit_status != 0:
            logger.error("Restore command failed with exit status %s", exit_status)
            return (False, progress_output)
        logger.info("Restore completed successfully.")
        return (True, progress_output)

    except Exception as e:
        logger.error("Error during account transfer: %s", e)
        logger.error(traceback.format_exc())
        return (False, f"Exception occurred: {str(e)}")

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        # Gather form data.
        source_host = request.form.get("source_host")
        source_user = request.form.get("source_user")
        source_pass = request.form.get("source_pass")
        destination_host = request.form.get("destination_host")
        destination_root_user = request.form.get("destination_root_user")
        destination_root_pass = request.form.get("destination_root_pass")
        username = request.form.get("username")
        domain = request.form.get("domain")
        overwrite = request.form.get("overwrite") == "on"

        logger.info("Received transfer request for username: %s, domain: %s", username, domain)

        # Check for account conflicts on destination.
        conflict_status = check_destination_account(
            destination_host, destination_root_user, destination_root_pass, domain, username
        )

        if conflict_status == "connection_error":
            flash("Unable to connect to the destination server. Check credentials and network connectivity.", "error")
            return redirect(url_for("index"))
        elif conflict_status == "username_conflict":
            flash("The domain exists with a different username on the destination. Update the username on the destination first.", "error")
            return redirect(url_for("index"))
        elif conflict_status == "overwrite_allowed" and not overwrite:
            flash("An account with this domain and username already exists. Check the overwrite option to proceed.", "warning")
            return redirect(url_for("index"))
        else:
            # Transfer the account. This returns (success, progress_output).
            success, progress = transfer_account(
                source_host, source_user, source_pass,
                destination_host, destination_root_user, destination_root_pass
            )
            if success:
                return render_template("progress.html", progress=progress)
            else:
                flash(f"Transfer failed. Progress details: {progress}", "error")
                return redirect(url_for("index"))
    return render_template("index.html")

if __name__ == "__main__":
    # For production, run using a production WSGI server (e.g. Gunicorn) behind HTTPS.
    app.run(host="0.0.0.0", port=5000, debug=False)
