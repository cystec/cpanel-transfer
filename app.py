import os
import logging
import traceback
import time
from flask import Flask, render_template, request, redirect, flash, url_for
import paramiko

app = Flask(__name__)
# Use an environment variable for the secret key in production
app.secret_key = os.environ.get('SECRET_KEY', 'default_secret_key')

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def check_destination_account(destination_host, destination_root_user, destination_root_pass, domain, username):
    """
    Connects via SSH to the destination server and checks if the account exists.
    Uses /scripts/whoowns to check for an existing username and greps /var/cpanel/users for the domain.
    
    Returns:
      - "overwrite_allowed": if the account exists with the same username and domain.
      - "username_conflict": if the domain exists but with a different username.
      - "domain_conflict": if only the domain exists.
      - "no_conflict": if no conflicts are detected.
      - "connection_error": if there was an error connecting to the destination server.
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

        # Check if the domain exists by searching in /var/cpanel/users
        cmd_domain = f"grep -R '{domain}' /var/cpanel/users"
        logger.info("Executing command: %s", cmd_domain)
        stdin, stdout, stderr = ssh.exec_command(cmd_domain)
        result_domain = stdout.read().decode().strip()

        ssh.close()

        # Decision logic based on command results
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
        logger.error("Error connecting or executing commands on destination: %s", e)
        logger.error(traceback.format_exc())
        return "connection_error"

def transfer_account(source_host, source_user, source_pass, username, backup_path):
    """
    Transfers the cPanel account from the source to the destination.
    
    In production, implement these steps:
      1. Connect to the source cPanel (using its API) to generate a backup.
      2. Download the backup to a secure temporary location.
      3. Connect to the destination server (via the WHM API or CLI) and restore the backup.
    
    This function simulates the transfer process.
    """
    try:
        logger.info("Simulating backup download from source server: %s", source_host)
        # In production, use secure HTTPS requests and the cPanel API to get the backup.
        time.sleep(2)  # Simulate delay for backup download
        
        logger.info("Simulating account restore on destination for user: %s", username)
        time.sleep(2)  # Simulate delay for account restore
        
        # If all steps succeed:
        return True
    except Exception as e:
        logger.error("Error during transfer: %s", e)
        logger.error(traceback.format_exc())
        return False

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        # Collect and validate form data
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

        # Check for conflicts on the destination server
        conflict_status = check_destination_account(
            destination_host,
            destination_root_user,
            destination_root_pass,
            domain,
            username
        )

        if conflict_status == "connection_error":
            flash("Unable to connect to the destination server. Verify credentials and network connectivity.", "error")
            return redirect(url_for("index"))
        elif conflict_status == "username_conflict":
            flash("The domain exists with a different username on the destination. Please update the username on the destination first.", "error")
            return redirect(url_for("index"))
        elif conflict_status == "overwrite_allowed" and not overwrite:
            flash("An account with this domain and username already exists. Check the overwrite option to proceed.", "warning")
            return redirect(url_for("index"))
        else:
            # For demonstration, we use a fixed backup file path.
            backup_path = "/tmp/backup.tar.gz"
            success = transfer_account(source_host, source_user, source_pass, username, backup_path)
            if success:
                flash("Transfer completed successfully!", "success")
            else:
                flash("Transfer failed. Please review logs and try again.", "error")
            return redirect(url_for("index"))
    return render_template("index.html")

if __name__ == "__main__":
    # In production, run via a production WSGI server (e.g. Gunicorn)
    app.run(host="0.0.0.0", port=5000, debug=False)
