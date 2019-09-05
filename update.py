import requests
from datetime import datetime
import os.path
import sys
import version
import multiprocessing
import time
import logging

URL_BINARY = "https://github.com/NguyenKhong/Download_Edumall_beta/raw/master/dist/DownloadEdumall.exe"
URL_VERSION = "https://raw.githubusercontent.com/NguyenKhong/Download_Edumall_beta/master/version.py"
HEADERS = {"User-Agent" : "Mozilla/5.0 (Windows NT 6.1; WOW64; rv:44.0) Gecko/20100101 Firefox/44.0"}
UPDATE_OK = 1
UPDATE_ERROR = 2
UPDATE_UNNECESSARY = 3
    
logger = logging.getLogger("DownloadEdumall")

def CheckUpdate():
    logger.info("Dang cap nhat phan mem moi ...")
    logger.info("Phien ban hien tai: %s" % version.VERSION)
    try:
        status_code = Update()
        if status_code == UPDATE_OK:
            logger.info("Cap nhat phan mem moi thanh cong")
            sys.exit(0)
        elif status_code == UPDATE_UNNECESSARY:
            logger.info("Phan mem dang su dung phien ban moi nhat")
            return
        else:
            raise
    except Exception as e:
        if e != "":
            logger.warning("Cap nhat phan mem khong thanh cong - loi: %s", str(e))
        else:
            logger.warning("Cap nhat phan mem khong thanh cong")


def Update():
    VERSION_OLD = version.VERSION
    try:
        r = requests.get(URL_VERSION, headers = HEADERS)
    except Exception as e:
        raise e
    index = r.content.find("VERSION")
    if index == -1: return UPDATE_ERROR
    VERSION = r.content[index+11:index+21]
    if datetime.strptime(VERSION_OLD, "%Y.%m.%d") >= datetime.strptime(VERSION, "%Y.%m.%d"): return UPDATE_UNNECESSARY
    try:
        r = requests.get(URL_BINARY, headers = HEADERS)
    except Exception as e:
        raise e
    if getattr(sys, 'frozen', False):
        file_name_origin = os.path.realpath(os.path.abspath(sys.executable))
        name, real_ext = os.path.splitext(file_name_origin)
        file_name = "%s.new%s" % (name, real_ext)
        with open(file_name, 'wb') as f:
            for chunk in r.iter_content(5242880):
                f.write(chunk)
        file_name_old = "%s.old%s" % (name, real_ext)
        os.rename(file_name_origin, file_name_old)
        os.rename(file_name, file_name_origin)
        return UPDATE_OK
    return UPDATE_ERROR



