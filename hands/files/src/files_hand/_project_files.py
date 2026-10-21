"""Descriptor-confined I/O extracted from the existing private Files runtime.

This class supplies no identity or permission. Each transport must validate
the current Core effect authority before invoking it and before releasing output.
"""
import base64
import hashlib
import os
import stat
import unicodedata
from contextlib import contextmanager

from modules.project_runtime.workspace_roots import ProjectFileError, _open_beneath

TOOLS = frozenset({"file_list", "file_info", "file_read", "file_hash"})
FLAGS = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK


class ProjectFiles:
    def __init__(self, root):
        self.root = os.open(root, FLAGS | os.O_DIRECTORY)
        self.root_info = os.fstat(self.root)
        if self.root_info.st_uid != os.geteuid() or self.root_info.st_mode & 0o077:
            os.close(self.root)
            raise ValueError("Files project root must be owner-private")

    def close(self):
        os.close(self.root)

    @contextmanager
    def opened(self, path, *, directory=False):
        if (not isinstance(path, str) or len(path.encode("utf-8")) > 4096
            or not unicodedata.is_normalized("NFC", path)
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in path)):
            raise ValueError("Canonical relative path required")
        parts = path.split("/") if path else []
        if len(parts) > 64 or any(p in {"", ".", ".."} or "\\" in p for p in parts):
            raise ValueError("Path must stay beneath the project root")
        fd = os.dup(self.root)
        try:
            for index, part in enumerate(parts):
                flags = FLAGS | (os.O_DIRECTORY if directory or index < len(parts)-1 else 0)
                child = _open_beneath(fd, part, flags)
                os.close(fd)
                fd = child
            info = os.fstat(fd)
            if (info.st_dev != self.root_info.st_dev or info.st_uid != os.geteuid()
                or info.st_mode & 0o077 or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode))
                or (stat.S_ISREG(info.st_mode) and info.st_nlink != 1)):
                raise ValueError("Unsafe project entry")
            yield fd,info
        finally:
            os.close(fd)

    @staticmethod
    def entry(path,info):
        return {"path":path,"name":path.rsplit("/",1)[-1],
            "type":"directory" if stat.S_ISDIR(info.st_mode) else "file",
            "size_bytes":info.st_size if stat.S_ISREG(info.st_mode) else 0}

    def execute(self, tool, args):
        if tool not in TOOLS or not isinstance(args,dict) or set(args)-(
            {"path","offset","length"} if tool=="file_read" else {"path"}):
            raise ValueError("Unknown tool or argument")
        path=args.get("path","")
        with self.opened(path,directory=tool=="file_list") as (fd,info):
            if tool=="file_list":
                entries=[]
                with os.scandir(fd) as items:
                    for index,item in enumerate(items):
                        if index>=1000:
                            raise ValueError("Directory exceeds minimum-runtime listing budget")
                        candidate=(path+"/" if path else "")+item.name
                        try:
                            with self.opened(candidate) as (_,child):
                                entries.append(self.entry(candidate,child))
                        except (OSError,ValueError,ProjectFileError):
                            continue
                return {"path":path,"entries":sorted(entries,key=lambda item:(item["type"]!="directory",item["name"].casefold()))}
            if tool=="file_info":
                return self.entry(path,info)
            if not stat.S_ISREG(info.st_mode) or info.st_size>262144:
                raise ValueError("Bounded regular file required")
            offset,length=args.get("offset",0),args.get("length",262144)
            if (type(offset) is not int or type(length) is not int or not 0<=offset<2**63
                or not 1<=length<=262144):
                raise ValueError("Invalid read budget")
            data=os.pread(fd,length,offset) if tool=="file_read" else os.pread(fd,262145,0)
            after=os.fstat(fd)
            if (after.st_size!=info.st_size or after.st_mtime_ns!=info.st_mtime_ns
                or after.st_ctime_ns!=info.st_ctime_ns or len(data)>262144):
                raise ValueError("File changed during bounded read")
            return ({"path":path,"data_base64":base64.b64encode(data).decode("ascii"),
                "offset":offset,"size_bytes":info.st_size} if tool=="file_read" else
                {"path":path,"sha256":hashlib.sha256(data).hexdigest()})
