import requests
from datetime import datetime
import os.path
import sys
import version

URL_BINARY = "https://github.com/NguyenKhong/Download_Edumall_beta/raw/version/dist/DownloadEdumall.exe"
URL_VERSION = "https://raw.githubusercontent.com/NguyenKhong/Download_Edumall_beta/version/version.py"
HEADERS = {"User-Agent" : "Mozilla/5.0 (Windows NT 6.1; WOW64; rv:44.0) Gecko/20100101 Firefox/44.0"}

def Update():
    print version.VERSION   
    VERSION_OLD = version.VERSION
    try:
        r = requests.get(URL_VERSION, headers = HEADERS)
    except:
        raise
    if 'VERSION' not in r.content: raise
    # exec(compile(r.content, "version.py", "exec"))
    index = r.content.find("VERSION")
    VERSION = r.content[index+11:index+21]
    if datetime.strptime(VERSION_OLD, "%Y.%m.%d") >= datetime.strptime(VERSION, "%Y.%m.%d"): return
    try:
        r = requests.get(URL_BINARY, headers = HEADERS)
    except:
        raise
    if getattr(sys, 'frozen', False):
        file_name_origin = os.path.realpath(os.path.abspath(sys.executable))
        name, real_ext = os.path.splitext(file_name_origin)
        file_name = "%s.new%s" % (name, real_ext)
        with open(file_name, 'wb') as f:
            for chunk in r.iter_content(5242880):
                f.write(chunk)
        os.remove(file_name_origin)
        os.rename(file_name, file_name_origin)