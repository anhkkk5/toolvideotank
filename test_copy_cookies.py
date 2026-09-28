"""Test: Read cookies from all possible methods."""
import os, sys, sqlite3, subprocess, tempfile, shutil, ctypes

print("=" * 60)
print("COOKIE FILE ACCESS TEST")
print("=" * 60)

browsers = {
    "CocCoc": os.path.expandvars(r"%LOCALAPPDATA%\CocCoc\Browser\User Data\Default\Network\Cookies"),
    "Chrome": os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data\Default\Network\Cookies"),
    "Edge": os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\User Data\Default\Network\Cookies"),
}

for name, path in browsers.items():
    if not os.path.exists(path):
        print(f"\n{name}: NOT FOUND at {path}")
        continue
    print(f"\n{name}: {path}")
    print(f"  Size: {os.path.getsize(path)} bytes")
    
    # Check WAL and SHM files
    wal = path + "-wal"
    shm = path + "-shm"
    print(f"  WAL exists: {os.path.exists(wal)} ({os.path.getsize(wal) if os.path.exists(wal) else 0} bytes)")
    print(f"  SHM exists: {os.path.exists(shm)}")
    
    # Method A: Direct sqlite3 connect (no URI)
    print(f"  Direct connect...", end=" ")
    try:
        conn = sqlite3.connect(path, timeout=1)
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM cookies WHERE host_key LIKE '%douyin%'")
        print(f"OK! {cur.fetchone()[0]} douyin cookies")
        conn.close()
    except Exception as e:
        print(f"FAIL: {e}")
    
    # Method B: sqlite3 with PRAGMA journal_mode
    print(f"  PRAGMA wal_checkpoint...", end=" ")
    try:
        conn = sqlite3.connect(path, timeout=1)
        conn.execute("PRAGMA journal_mode=WAL")
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM cookies WHERE host_key LIKE '%douyin%'")
        print(f"OK! {cur.fetchone()[0]} douyin cookies")
        conn.close()
    except Exception as e:
        print(f"FAIL: {e}")
    
    # Method C: Copy WAL file approach - copy .db + .wal + .shm together
    print(f"  Copy DB+WAL+SHM...", end=" ")
    try:
        tmp = tempfile.mkdtemp()
        # Try to copy all 3 files
        for ext in ["", "-wal", "-shm"]:
            src = path + ext
            if os.path.exists(src):
                try:
                    # Use Win32 API for shared read
                    GENERIC_READ = 0x80000000
                    SHARE_ALL = 0x07  # READ|WRITE|DELETE
                    OPEN_EXISTING = 3
                    FILE_ATTRIBUTE_NORMAL = 0x80
                    
                    handle = ctypes.windll.kernel32.CreateFileW(
                        src, GENERIC_READ, SHARE_ALL, None, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, None
                    )
                    if handle and handle != -1 and handle != 0xFFFFFFFF and handle != 0xFFFFFFFFFFFFFFFF:
                        size = ctypes.windll.kernel32.GetFileSize(handle, None)
                        if size > 0:
                            buf = ctypes.create_string_buffer(size)
                            read = ctypes.c_ulong(0)
                            ctypes.windll.kernel32.ReadFile(handle, buf, size, ctypes.byref(read), None)
                            ctypes.windll.kernel32.CloseHandle(handle)
                            
                            dst = os.path.join(tmp, os.path.basename(src))
                            with open(dst, "wb") as f:
                                f.write(buf.raw[:read.value])
                            print(f"\n    Copied {os.path.basename(src)} ({read.value} bytes)", end="")
                        else:
                            ctypes.windll.kernel32.CloseHandle(handle)
                    else:
                        err = ctypes.windll.kernel32.GetLastError()
                        print(f"\n    Cannot open {os.path.basename(src)}, error={err}", end="")
                except Exception as ex:
                    print(f"\n    Error copying {os.path.basename(src)}: {ex}", end="")
        
        tmp_db = os.path.join(tmp, "Cookies")
        if os.path.exists(tmp_db):
            conn = sqlite3.connect(tmp_db)
            cur = conn.cursor()
            cur.execute("SELECT count(*) FROM cookies WHERE host_key LIKE '%douyin%'")
            count = cur.fetchone()[0]
            print(f"\n    SQLite read OK! {count} douyin cookies")
            if count > 0:
                cur.execute("SELECT name FROM cookies WHERE host_key LIKE '%douyin%' LIMIT 10")
                for row in cur.fetchall():
                    print(f"      - {row[0]}")
            conn.close()
        
        shutil.rmtree(tmp, ignore_errors=True)
    except Exception as e:
        print(f"FAIL: {e}")

print("\n\n--- Alternative: Check if sqlite3 .exe exists ---")
sqlite3_exe = shutil.which("sqlite3")
print(f"sqlite3.exe: {sqlite3_exe}")
