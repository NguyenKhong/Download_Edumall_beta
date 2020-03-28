import os
from urllib.parse import urljoin, urlparse
import urllib
import ntpath
import unicodedata

is_win32 = os.name == "nt"

def createDirectory(base, new_dir):
    if is_win32:
        new_dir = cleanName(new_dir, ".")
        if not base.startswith("\\\\?\\"): base = "\\\\?\\" + base
    path_new_dir = os.path.join(base, new_dir)
    if not os.path.exists(path_new_dir): os.mkdir(path_new_dir)
    return path_new_dir
    
def try_get(src, getter, expected_type=None):
    if not isinstance(getter, (list, tuple)):
        getter = [getter]
    for get in getter:
        try:
            v = get(src)
        except (AttributeError, KeyError, TypeError, IndexError):
            pass
        else:
            if expected_type is None or isinstance(v, expected_type):
                return v
    return None

def removeControlCharacters(s):
    return "".join(ch for ch in s if unicodedata.category(ch)[0]!="C")

def cleanName(value, deletechars = '<>:"/\\|?*\r\n'):
    value = str(value)
    value = filter(lambda x: x not in deletechars, value)
    return removeControlCharacters(value).strip()

def limitPath(s):
    if len(s) > 70:
        while True:
            yes_no = input(" +> Tên đường dẫn quá dài bạn muốn thay đổi chứ (Y/N): ").strip().lower()
            if yes_no == "y" or yes_no == "yes":
                new_path = input(" +> Vui lòng nhập tên đường đẫn mới: ").strip()
                if len(new_path) > 70:
                    continue
                else:
                    return new_path
            else:
                break
        return s[:70]
    return s

def GetFileNameFromUrl(url):
    urlParsed = urlparse(urllib.parse.unquote(url))
    fileName = os.path.basename(urlParsed.path)
    return cleanName(fileName)

def pathLeaf(path):
    '''
    Name..........: pathLeaf
    Description...: get file name from full path
    Parameters....: path - string. Full path
    Return values.: string file name
    Author........: None
    '''
    head, tail = ntpath.split(path)
    return tail or ntpath.basename(head)