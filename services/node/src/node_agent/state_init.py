"""Initialize only empty local adapter volumes; never rewrite existing node data."""

import os
import stat


def initialize(path: str, uid: int) -> None:
    info = os.lstat(path)
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise ValueError("Real volume root required")
    if (info.st_uid, info.st_gid) == (uid, uid):
        if info.st_mode & 0o077:
            raise ValueError("Existing state root is not private")
        return
    if info.st_uid != 0 or os.listdir(path):
        raise ValueError("Refusing to adopt nonempty or foreign-owned state")
    os.chmod(path, 0o700)
    os.chown(path, uid, uid)


if __name__ == "__main__":
    initialize("/node-state", 2201)
    initialize("/registry-state", 1000)
