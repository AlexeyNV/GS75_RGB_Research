"""Nanosecond frame instrumentation, exclusive stages and portable resource sampling."""
from collections import defaultdict
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import ctypes
import os
import platform
import time
import numpy as np

ACTIVE=ContextVar('frame_profile',default=None)
STAGES=('VIDEO_DECODE','ARUCO_DETECT','HOMOGRAPHY','IMAGE_RECTIFICATION',
        'BACKGROUND_COMPENSATION','LED_DETECTION','COLOR_CLASSIFICATION','EVENT_AGGREGATION','FRAME_TOTAL')
AUX_STAGES=('DIAGNOSTIC_CREATION','DIAGNOSTIC_PNG','GUI_UPDATE','RESULT_WRITE')


class FrameProfile:
    def __init__(self):self.ns=defaultdict(int);self.stack=[]
    @contextmanager
    def activate(self):
        token=ACTIVE.set(self)
        try:yield self
        finally:ACTIVE.reset(token)
    @contextmanager
    def stage(self,name):
        entry=[time.perf_counter_ns(),0];self.stack.append(entry)
        try:yield
        finally:
            elapsed=time.perf_counter_ns()-entry[0];self.stack.pop()
            self.ns[name]+=elapsed if name=='FRAME_TOTAL' else max(0,elapsed-entry[1])
            if self.stack:self.stack[-1][1]+=elapsed
    def milliseconds(self):return {name:self.ns[name]/1e6 for name in STAGES+AUX_STAGES}


def timed(name):
    def decorate(function):
        @wraps(function)
        def wrapped(*args,**kwargs):
            profile=ACTIVE.get()
            if profile is None:return function(*args,**kwargs)
            with profile.stage(name):return function(*args,**kwargs)
        return wrapped
    return decorate


@timed('DIAGNOSTIC_CREATION')
def diagnostic(function,*args,**kwargs):return function(*args,**kwargs)


def stats(values):
    if not values:return dict(count=0,mean_ms=None,p50_ms=None,p95_ms=None,p99_ms=None,max_ms=None,fps=None)
    a=np.asarray(values,float);mean=float(a.mean())
    return dict(count=len(a),mean_ms=mean,p50_ms=float(np.median(a)),p95_ms=float(np.percentile(a,95)),
                p99_ms=float(np.percentile(a,99)),max_ms=float(a.max()),fps=1000/mean if mean>0 else None)


def rss_bytes():
    if os.name=='nt':
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_=[('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD)]+[(k,ctypes.c_size_t) for k in
                ('PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage',
                 'QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage')]
        counters=Counters();counters.cb=ctypes.sizeof(counters)
        kernel=ctypes.WinDLL('kernel32');kernel.GetCurrentProcess.restype=wintypes.HANDLE
        psapi=ctypes.WinDLL('psapi');psapi.GetProcessMemoryInfo.argtypes=[wintypes.HANDLE,ctypes.POINTER(Counters),wintypes.DWORD]
        if psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(),ctypes.byref(counters),counters.cb):return counters.WorkingSetSize
    try:
        with open('/proc/self/statm') as f:return int(f.read().split()[1])*os.sysconf('SC_PAGE_SIZE')
    except (OSError,AttributeError):return None


def machine_info():
    import cv2
    cpu=platform.processor();ram=None
    if os.name=='nt':
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,r'HARDWARE\DESCRIPTION\System\CentralProcessor\0') as key:
            cpu=winreg.QueryValueEx(key,'ProcessorNameString')[0].strip()
        class Memory(ctypes.Structure):
            _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong)]+[(k,ctypes.c_ulonglong) for k in
                ('total_phys','avail_phys','total_page','avail_page','total_virtual','avail_virtual','extended')]
        m=Memory();m.length=ctypes.sizeof(m)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):ram=m.total_phys
    else:
        try:ram=os.sysconf('SC_PAGE_SIZE')*os.sysconf('SC_PHYS_PAGES')
        except (ValueError,AttributeError):pass
    return dict(cpu=cpu,logical_cpus=os.cpu_count(),ram_bytes=ram,python=platform.python_version(),
                opencv=cv2.__version__,opencv_threads=cv2.getNumThreads(),os=platform.platform())
