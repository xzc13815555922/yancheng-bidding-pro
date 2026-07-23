#!/usr/bin/env python3
"""
flock.py — macOS 替代 /usr/bin/flock 的纯 Python 实现

用法跟 flock 一样:
  flock.py [-n] <lockfile> <command...>
  flock.py -n /tmp/openclaw/ybp-collect.lock /usr/bin/python3 incremental_collect.py

行为对齐 Linux flock:
  -n: 非阻塞, 拿不到锁立即 exit 1
  无 -n: 阻塞, 等到拿锁为止

实现: fcntl.flock (macOS 自带)
"""
import fcntl
import os
import sys


def main():
    args = sys.argv[1:]
    nonblock = False
    if "-n" in args:
        nonblock = True
        args.remove("-n")
    if len(args) < 2:
        print("用法: flock.py [-n] <lockfile> <command...>", file=sys.stderr)
        sys.exit(2)
    lockfile = args[0]
    cmd = args[1:]

    os.makedirs(os.path.dirname(lockfile) or ".", exist_ok=True)
    fd = open(lockfile, "w")
    try:
        if nonblock:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        else:
            fcntl.flock(fd, fcntl.LOCK_EX)
    except (BlockingIOError, OSError):
        sys.stderr.write(f"flock: {lockfile} 已被锁, 退出 (--no-wait)\n")
        sys.exit(1)

    fd.write(str(os.getpid()))
    fd.flush()
    # 执行命令
    os.execvp(cmd[0], cmd)


if __name__ == "__main__":
    main()