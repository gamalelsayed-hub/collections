"""The shared data folder: database, files, lock and backups.

Layout (one folder, e.g. on Google Drive):
  data.db            the database
  files/             generated statements, zips, letters (per cycle month)
  assets/            logo, stamp, signature images
  backups/           automatic copies of data.db (newest 30 kept)
  app.lock           who has the program open (JSON)
"""
import getpass
import glob
import json
import os
import shutil
import socket
import sqlite3
import time
from datetime import datetime

DB_NAME = "data.db"
LOCK_NAME = "app.lock"
KEEP_BACKUPS = 30


class LockedError(Exception):
    def __init__(self, info):
        super().__init__(f"locked by {info.get('user')}")
        self.info = info


class DataFolder:
    def __init__(self, path):
        self.path = path
        for sub in ("files", "assets", "backups"):
            os.makedirs(os.path.join(path, sub), exist_ok=True)

    # ---------------- paths
    @property
    def db_path(self):
        return os.path.join(self.path, DB_NAME)

    @property
    def lock_path(self):
        return os.path.join(self.path, LOCK_NAME)

    def files_dir(self, *parts):
        p = os.path.join(self.path, "files", *parts)
        os.makedirs(p, exist_ok=True)
        return p

    def asset(self, name):
        return os.path.join(self.path, "assets", name)

    def conflict_copies(self):
        """Google Drive keeps both versions on a sync conflict as "data (1).db" — warn about them."""
        return [p for p in glob.glob(os.path.join(self.path, "data*.db")) if os.path.basename(p) != DB_NAME]

    # ---------------- lock
    def read_lock(self):
        try:
            with open(self.lock_path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def acquire(self, user):
        info = self.read_lock()
        me = self._me(user)
        if info and info.get("machine") != me["machine"]:
            raise LockedError(info)
        with open(self.lock_path, "w", encoding="utf-8") as f:
            json.dump(me, f, ensure_ascii=False)
        return me

    def release(self):
        info = self.read_lock()
        if info and info.get("machine") == socket.gethostname():
            try:
                os.remove(self.lock_path)
            except OSError:
                pass

    def force_unlock(self):
        try:
            os.remove(self.lock_path)
        except OSError:
            pass

    @staticmethod
    def _me(user):
        return {"user": user or getpass.getuser(), "machine": socket.gethostname(),
                "since": datetime.now().strftime("%Y-%m-%d %H:%M"), "pid": os.getpid()}

    # ---------------- backups
    def backup(self, tag):
        if not os.path.exists(self.db_path):
            return None
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        dest = os.path.join(self.path, "backups", f"data-{stamp}-{tag}.db")
        src = sqlite3.connect(self.db_path)
        dst = sqlite3.connect(dest)
        with dst:
            src.backup(dst)
        src.close()
        dst.close()
        self._prune()
        return dest

    def backups(self):
        return sorted(glob.glob(os.path.join(self.path, "backups", "data-*.db")), reverse=True)

    def _prune(self):
        for old in self.backups()[KEEP_BACKUPS:]:
            try:
                os.remove(old)
            except OSError:
                pass

    def restore(self, backup_path):
        self.backup("before-restore")
        shutil.copy2(backup_path, self.db_path)

    @staticmethod
    def wait_for_sync(path, seconds=3.0):
        """Give a syncing drive a moment if the database is being replaced right now."""
        end = time.time() + seconds
        last = None
        while time.time() < end:
            try:
                size = os.path.getsize(path)
            except OSError:
                return
            if size == last:
                return
            last = size
            time.sleep(0.5)
