import os
import subprocess
from datetime import datetime

BACKUP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backups")
os.makedirs(BACKUP_DIR, exist_ok=True)
PG_DUMP_PATH = r"C:\Program Files\PostgreSQL\18\bin\pg_dump.exe"


def backup_database():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = os.path.join(BACKUP_DIR, f"connector_ai_db_backup_{timestamp}.sql")

    env = os.environ.copy()
    env["PGPASSWORD"] = "admin123"

    cmd = [
        PG_DUMP_PATH,
        "-U", "postgres",
        "-h", "localhost",
        "-p", "5432",
        "-d", "connector_ai_db",
        "-f", backup_file,
    ]

    print(f"Starting database backup for 'connector_ai_db'...")
    res = subprocess.run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res.returncode == 0:
        file_size = os.path.getsize(backup_file)
        print(f"SUCCESS: Database backup completed! File: {backup_file} (Size: {file_size} bytes)")
        return backup_file
    else:
        print(f"FAILED: Backup failed. Stderr: {res.stderr}")
        return None


if __name__ == "__main__":
    backup_database()

