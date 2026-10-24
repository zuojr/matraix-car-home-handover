"""Sample this coordinator's process tree, not other users' process contents."""

from collections import Counter
import os
from pathlib import Path
import threading
import time


def descendants(table, root):
    selected = {root} if root in table else set()
    while True:
        expanded = selected | {pid for pid, row in table.items() if row[0] in selected}
        if expanded == selected:
            return selected
        selected = expanded


def _linux():
    table = {}
    for directory in Path("/proc").iterdir():
        if not directory.name.isdigit():
            continue
        try:
            rows = dict(
                line.split(":", 1)
                for line in (directory / "status").read_text().splitlines()
                if ":" in line
            )
            table[int(directory.name)] = (
                int(rows["PPid"].strip()),
                int(rows.get("VmRSS", "0 kB").split()[0]) * 1024,
            )
        except (OSError, KeyError, ValueError):
            pass  # Processes may disappear while enumerating the OS snapshot.
    rows = dict(
        line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines()
    )
    return table, int(rows["MemAvailable"].split()[0]) * 1024


def _windows():
    import ctypes as c
    from ctypes import wintypes as w

    class Entry(c.Structure):
        _fields_ = [
            ("size", w.DWORD),
            ("usage", w.DWORD),
            ("pid", w.DWORD),
            ("heap", c.c_size_t),
            ("module", w.DWORD),
            ("threads", w.DWORD),
            ("ppid", w.DWORD),
            ("priority", w.LONG),
            ("flags", w.DWORD),
            ("exe", w.WCHAR * 260),
        ]

    class Counters(c.Structure):
        _fields_ = [("size", w.DWORD), ("faults", w.DWORD)] + [
            (name, c.c_size_t)
            for name in (
                "peak",
                "rss",
                "peak_paged",
                "paged",
                "peak_nonpaged",
                "nonpaged",
                "pagefile",
                "peak_pagefile",
            )
        ]

    class Memory(c.Structure):
        _fields_ = [("size", w.DWORD), ("load", w.DWORD)] + [
            (name, c.c_ulonglong)
            for name in (
                "total",
                "available",
                "total_pagefile",
                "available_pagefile",
                "total_virtual",
                "available_virtual",
                "extended",
            )
        ]

    kernel = c.WinDLL("kernel32", use_last_error=True)
    psapi = c.WinDLL("psapi", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [w.DWORD, w.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = w.HANDLE
    for name in ("Process32FirstW", "Process32NextW"):
        fn = getattr(kernel, name)
        fn.argtypes, fn.restype = [w.HANDLE, c.POINTER(Entry)], w.BOOL
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel.OpenProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    psapi.GetProcessMemoryInfo.argtypes = [w.HANDLE, c.POINTER(Counters), w.DWORD]
    psapi.GetProcessMemoryInfo.restype = w.BOOL
    kernel.GlobalMemoryStatusEx.argtypes = [c.POINTER(Memory)]
    kernel.GlobalMemoryStatusEx.restype = w.BOOL
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    if snapshot == c.c_void_p(-1).value:
        raise OSError("Process snapshot unavailable")
    table = {}
    try:
        entry = Entry()
        entry.size = c.sizeof(entry)
        ok = kernel.Process32FirstW(snapshot, c.byref(entry))
        while ok:
            table[entry.pid] = (entry.ppid, None)
            ok = kernel.Process32NextW(snapshot, c.byref(entry))
    finally:
        kernel.CloseHandle(snapshot)
    for pid in descendants(table, os.getpid()):
        handle = kernel.OpenProcess(0x0410, False, pid)
        if not handle:
            continue
        try:
            count = Counters()
            count.size = c.sizeof(count)
            if psapi.GetProcessMemoryInfo(handle, c.byref(count), c.sizeof(count)):
                table[pid] = (table[pid][0], int(count.rss))
        finally:
            kernel.CloseHandle(handle)
    memory = Memory()
    memory.size = c.sizeof(memory)
    if not kernel.GlobalMemoryStatusEx(c.byref(memory)):
        raise OSError("Host available memory unavailable")
    return table, int(memory.available)


def process_sample():
    table, available = _windows() if os.name == "nt" else _linux()
    selected = descendants(table, os.getpid())
    known = [table[pid][1] for pid in selected if table[pid][1] is not None]
    if os.getpid() not in selected or not known:
        raise OSError("Coordinator memory unavailable")
    return {
        "processes": len(selected),
        "rss_sum_bytes": sum(known),
        "unreadable_processes": len(selected) - len(known),
        "host_available_bytes": available,
    }


class MemorySampler:
    def __init__(self, out, interval=1.0):
        self.out, self.interval = Path(out), interval
        self.samples, self.errors = [], Counter()
        self.stop = threading.Event()
        self.existed = self.out.exists()

    def sample(self):
        try:
            self.samples.append(
                {"elapsed_seconds": time.monotonic() - self.started, **process_sample()}
            )
        except Exception as exc:
            self.errors[type(exc).__name__] += 1

    def __enter__(self):
        self.started = time.monotonic()
        self.sample()

        def loop():
            while not self.stop.wait(self.interval):
                self.sample()

        self.thread = threading.Thread(target=loop, name="journey-memory", daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stop.set()
        self.thread.join(timeout=5)
        self.sample()
        if self.existed or not self.out.is_dir():
            return  # Invalid/resumed runs must not modify an existing bundle.
        from .cohort import write_new

        write_new(
            self.out / "memory.json",
            {
                "scope": "coordinator plus current descendants; host available RAM",
                "method": "Windows working-set sum"
                if os.name == "nt"
                else "Linux proc VmRSS sum",
                "sample_interval_seconds": self.interval,
                "sampled_peak_rss_sum_bytes": max(
                    (s["rss_sum_bytes"] for s in self.samples), default=None
                ),
                "minimum_host_available_bytes": min(
                    (s["host_available_bytes"] for s in self.samples), default=None
                ),
                "peak_process_count": max(
                    (s["processes"] for s in self.samples), default=None
                ),
                "measurement_errors": dict(self.errors),
                "samples_with_unreadable_processes": sum(
                    bool(s["unreadable_processes"]) for s in self.samples
                ),
                "sampler_thread_stopped": not self.thread.is_alive(),
                "caveat": "Sampled RSS sum can double-count shared pages; not unique physical RAM, provider memory, cgroup limit or a guarantee against between-sample peaks.",
                "samples": self.samples,
            },
        )
