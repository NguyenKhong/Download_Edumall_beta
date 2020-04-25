# -*- coding: utf-8 -*-
import sys
import requests
import os
import re
from bs4 import BeautifulSoup
import time
from urllib.parse import urljoin, urlparse, quote, unquote
import threading
import logging
import ctypes
import json
import update
import version
import argparse
from streamlink_cli.main import main as streamlink_cli_main
from utils import *

os.environ['HTTPSVERIFY'] = '0'

g_session = logger = None

USER_AGENT = 'Mozilla/5.0 (Windows NT 6.1; WOW64; rv:44.0) Gecko/20100101 Firefox/44.0'
BASE_URL = 'https://edumall.vn/'
LOGIN_URL = 'https://sso.edumall.vn/users/sign_in'
GET_COURSES_URL = 'https://lms.edumall.vn/users/get_courses?page=%s'
COURSES_URL = "https://lms.edumall.vn/home/my-course/learning"

# EXTRA_INFO = {"description": "Download_Edumall (^v^)"}

PLUGIN_DIR = ""
if getattr(sys, 'frozen', False):
    FFMPEG_LOCATION = os.path.join(sys._MEIPASS, 'ffmpeg', 'ffmpeg.exe')
    PLUGIN_DIR = os.path.join(sys._MEIPASS, 'plugins')
else:
    FFMPEG_LOCATION = os.path.join(os.getcwd(), 'ffmpeg', 'ffmpeg.exe')

# std_headers['User-Agent'] = USER_AGENT

g_CurrentDir = os.getcwd()
kernel32 = ctypes.windll.kernel32

def setupLogger():
    global logger
    logger = logging.getLogger("DownloadEdumall")

    stdout_logger = logging.StreamHandler()
    file_logger = logging.FileHandler("DownloadEdumall.log", 'w', 'utf-8')
    formatter = logging.Formatter('%(asctime)s %(funcName)s %(levelname)s: %(message)s')
    stdout_logger.setFormatter(formatter)
    file_logger.setFormatter(formatter)

    logger.addHandler(stdout_logger)
    logger.addHandler(file_logger)
    logger.setLevel(logging.INFO)

def Request(url, method = 'GET', **kwargs):
  
    if kwargs.get('headers') is None:
        kwargs['headers'] = {'User-Agent' : USER_AGENT}
    elif kwargs.get('headers').get('User-Agent') is None:
        kwargs['headers']['User-Agent'] = USER_AGENT    

    timeout = kwargs.pop("timeout", None) or 60 # set http timeout = 1 min
    method = method.lower()
    func = getattr(g_session, method)
    try:
        response = func(url, timeout = timeout, **kwargs)
        if response.status_code != 200:
            return response.raise_for_status()
    except Exception as e:
        logger.error("Error: %s - url: %s", e, url)
        return None
    return response

def Login(user, password):
    # Request(BASE_URL, session = g_session)
    r = Request(LOGIN_URL, headers = {'referer' : BASE_URL})

    authenticity_token = re.findall(r'"authenticity_token".*value="(.*?)"', r.text)
    if not authenticity_token:
        logger.error("Dang nhap loi vui long lien he nha phat trien")
        sys.exit(1)

    payload = { 'user[email]' : user,
                'user[password]': password,
                'authenticity_token' : authenticity_token[0]
        }
    headers = { 'origin' : '{uri.scheme}://{uri.netloc}'.format(uri=urlparse(LOGIN_URL)) ,
                'referer' : LOGIN_URL
        }
    r = Request(LOGIN_URL, 'POST', data = payload, headers = headers)  
    
    error = re.findall(r"<p class=\"alert\">(.*?)<\/p>", r.text, re.DOTALL)
    if error and len(error[0]) != 0:
        logger.error("Dang nhap loi: %s" % error[0])
        sys.exit(1)
    return True

def GetCoursesPerPage(index):
    try:
        r = Request(GET_COURSES_URL % index, headers = {'referer' : COURSES_URL})
        if r is None:
            logger.warning("Yeu cau den %s bi loi" % GET_COURSES_URL)
            return []
        result = r.json if isinstance(r.json, dict) else r.json()
        return result.get("courses", [])
    except Exception as e:
        logger.error('Error: %s - url: %s', e, GET_COURSES_URL)
        return []

def GetCourses():
    courses = []
    for i in range(1, 100):
        result = GetCoursesPerPage(i)
        if result == []: break
        courses += result
    if courses == []:
        logger.warning("Loi Phan tich khoa hoc")
        return []
    UrlCourses = []
    for course in courses:
        name = course.get('name', '')
        if name == []:
            logger.warning("Loi Phan tich tieu de khoa hoc")
            return []
        url = urljoin(COURSES_URL, "/course/%s/lecture/%s" % (course.get('alias_name'), course.get('last_lecture_index')))
        UrlCourses.append({'url' : url, 'title' : name.strip()})
    return UrlCourses

def GetLessions(url):
    r = Request(url)
    soup = BeautifulSoup(r.content, 'html5lib') 
    Lessions = soup.select('.course_chapter')
    if not Lessions:
        logger.warning('Loi Khong the lay danh sach bai giang')
        return []
    UrlLessions = []
    for lession in Lessions:
        name = lession.find('div', {'class' : 'name_course'})
        if not name:
            logger.warning("Loi Phan tich Ten bai giang")
            return []
        name = cleanName(name.text)
        UrlLessions.append({'url' : urljoin(url, lession.get('href')), 'title' : name.strip()})

    documents = soup.select('.document')
    urlDocuments = []    
    for document in documents:
        urlDocuments.append(urljoin(url, document.a.get('href'))) 
    return UrlLessions, urlDocuments 

def GetVideo(url):
    headers = { 'origin' : 'https://sdk.uiza.io',
                    'referer' : 'https://sdk.uiza.io/v3/index.html'
            }

    def GetToken(infoToken):
        urlToken = 'https://edm.uiza.co/api/public/v3/media/entity/playback/token'
        headersToken = headers.copy()
        headersToken['Content-Type'] = 'application/json;charset=UTF-8'
        if not infoToken:
            return False
        payload = '{"entity_id": "%s", "app_id": "%s", "content_type": "stream", "drm_token": ["widevine"]}' % ( infoToken['entity_id'], infoToken['appId'])

        r = Request(urlToken, "POST", data = payload, headers = headersToken)
        if r is None: return False
        try:
            content = r.json if isinstance(r.json, dict) else r.json()
        except ValueError:
            logger.warning('Khong the phan tich json')
            return False
        return content['data']['token']

    def GetLinkPlay(infoToken, token):
    
        urlLinkPlay = 'https://ucc.uiza.io/api/private/v1/cdn/linkplay?entity_id=%s&app_id=%s&type_content=stream' % (infoToken['entity_id'], infoToken['appId'])
        headersLinkPlay = headers.copy()
        headersLinkPlay['Authorization'] = token
        r = Request(urlLinkPlay, headers = headersLinkPlay)
        if r is None: return False
        try:
            content = r.json if isinstance(r.json, dict) else r.json()
        except ValueError:
            logger.warning('Khong the phan tich json')
            return False
            
        for item in content['data']['urls']:
            if item['support'] == 'mpd':
                return item['url']

    infoMedia = {}
    r = Request(url)
    entity_id = re.findall(r'media_uiza_id\s=\s\"(.*?)\"', r.text)
    appId = re.findall(r"appId:\s\'(.*?)\'", r.text)
    if entity_id and appId:
        infoToken = {}
        infoToken['appId'] = appId[0]
        infoToken['entity_id'] = entity_id[0]
        token = GetToken(infoToken)
        if token == False:
            return infoMedia
        urlMpd = GetLinkPlay(infoToken, token)
        if urlMpd == False:
            return infoMedia
        infoMedia['url'] = urlMpd
        infoMedia['headers'] = headers
        infoMedia['protocol'] = 'dash'
    else:    
        UrlMasterPlayList = re.findall(r'jw_video_url\s=\s"(.*)"', r.text)
        if UrlMasterPlayList:
            infoMedia['url'] = UrlMasterPlayList[0]
            #fix referer url path do not encode
            tmp = url.split("/")
            if len(tmp) >= 3:
                url_referer = tmp[0] + "//" + tmp[2] + "/" + quote("/".join(tmp[3:]))
            else:
                url_referer = tmp[0] + "//" + tmp[2] + "/"
            infoMedia['headers'] = {'origin' : BASE_URL, 'referer' : url_referer}
            infoMedia['protocol'] = 'm3u8'
        else:
            logger.warning('Loi lay thong tin tai video')
    return infoMedia

def fixUrl(url):
    new_url = url
    if url.count("https://") >= 2:
        rfind_http = url.rfind("https://")
        if rfind_http > -1:
            new_url = url[rfind_http:]
    new_url = unquote(new_url)
    tmp = new_url.split("/")
    if len(tmp) >= 3:
        new_url = tmp[0] + "//" + tmp[2] + "/" + quote("/".join(tmp[3:]))
    else:
        new_url = tmp[0] + "//" + tmp[2] + "/"
    return new_url


def DownloadFile(url, pathLocal, headers = {}):
    url = fixUrl(url)
    r = None
    fileName = ""
    try:
        r = Request(url, stream = True, headers = headers)
        if r is None: return False
        fileAttach = r.headers.get('Content-disposition', '')
        if 'attachment' in fileAttach:
            fileName = fileAttach[22:-1]
        else:
            fileName = GetFileNameFromUrl(url)
        
        fullPath = os.path.join(pathLocal, cleanName(fileName))
        if not fullPath.startswith("\\\\?\\"):
            fullPath = "\\\\?\\" + fullPath
        if os.path.exists(fullPath):
            return True
        with open(fullPath, 'wb') as f:
            for chunk in r.iter_content(5242880):
                f.write(chunk)
        print(" +> %s download completed" % fileName)
    except Exception as e:
        logger.warning("Loi: %s - url: %s", e, url)
        return False
    # finally:
    #     if not r:
    #         r.close()
    return True

def TryDownloadDocument(urls, pathLocal):
    for url in urls:
        for i in range(5):
            if DownloadFile(url, pathLocal):
                break
            time.sleep(1)

def DownloadCourses():
    print("")
    email = input(' Email: ')
    password = input(' Password: ')
    if (email == "") or (password == ""):
        print ("email hoac password khong co")
        return
    
    if not Login(email, password):
        return

    print(30*"=")
    Courses = GetCourses()
    if not Courses: return

    print("Danh sach cac khoa hoc: ")
    i = 1
    for course in Courses:
        print("\t %d. %s" % (i, course['title']))
        i += 1

    print("\n  Lua chon tai ve cac khoa hoc")
    print("  Vd: 1, 2 hoac 1-5, 7")
    print("  Mac dinh la tai ve het\n")

    rawOption = input('(%s)$: ' % email)
    CoursesDownload = ParseOption(Courses, rawOption)
    if not CoursesDownload: return
    
    try:
        NumOfThread = input('So luong download [5]: ')
        if NumOfThread == "":
            NumOfThread = 5
        NumOfThread = int(NumOfThread)
    except ValueError:
        print(">>> Nhap so")
        return

    listPathDirLessions = []

    DirDownload = createDirectory(g_CurrentDir, "DOWNLOAD")
    print("")
    print(30*"=")
    iCourses = 0
    lenCourses = len(CoursesDownload)
    for course in CoursesDownload:
        print(" +> %s" % course['title'])
        DirCourse = createDirectory(DirDownload, cleanName(course['title']))
        DirDocuments = createDirectory(DirCourse, "Documents")
        Lessions, urlDocuments = GetLessions(course['url'])
        DownloadVideoAndDocument(Lessions, DirCourse, DirDocuments, urlDocuments, NumOfThread)  
        print(50*"=")
        iCourses += 1
        message = "Total: %.2f%%" % (iCourses*1.0/lenCourses*100.0)
        kernel32.SetConsoleTitleW(ctypes.c_wchar_p(message))        

def DonwloadLessions():
    print("")
    email = input(' Email: ')
    password = input(' Password: ')
    if (email == "") or (password == ""):
        logger.info("email hoac password khong co")
        return

    if not Login(email, password): return

    print(30*"=")
    Courses = GetCourses()
    if not Courses: return

    print(" Danh sach cac khoa hoc: ")
    i = 1
    for course in Courses:
        print("\t %d. %s" % (i, course['title']))
        i += 1

    print("\n Lua chon tai ve 1 khoa hoc")

    rawOption = input(' (%s)$: ' % email)
    try:
        lenCourses = len(Courses)
        index = int(rawOption) - 1
        if index > lenCourses:
            index = lenCourses - 1
        if index < 0:
            index = 0
        course = Courses[index]
    except ValueError:
        print(" Lam on nhap SO")
        return

    DirDownload = createDirectory(g_CurrentDir, "DOWNLOAD")
    print(30*"=")
    print("")
    print(" +> %s" % course['title'])
    DirCourse = createDirectory(DirDownload, cleanName(course['title']))
    DirDocuments = createDirectory(DirCourse, "Documents")
    Lessions, urlDocuments = GetLessions(course['url'])
    if not Lessions: return
    print("Danh sach cac bai giang: ")
    i = 1
    for Lession in Lessions:
        print("\t %d. %s" % (i, Lession['title']))
        i += 1

    print("\n  Lua chon tai ve cac bai giang")
    print("  Vd: 1, 2 hoac 1-5, 7")
    print("  Mac dinh la tai ve het\n")

    rawOption = input('(%s)$: ' % email)
    LessionsDownload = ParseOption(Lessions, rawOption)
    if not LessionsDownload: return

    try:
        NumOfThread = input(' So luong download cung luc [5]: ')
        if NumOfThread == "":
            NumOfThread = 5
        NumOfThread = int(NumOfThread)
    except ValueError:
        print(">>> Nhap so")
        return
    DownloadVideoAndDocument(LessionsDownload, DirCourse, DirDocuments, urlDocuments, NumOfThread)    

def DownloadVideoAndDocument(lessons, DirCourse, DirDocuments, urlDocuments, NumOfThread):
    threadDownloadDocument = None
    if urlDocuments:
        threadDownloadDocument = threading.Thread(target = TryDownloadDocument, args = (urlDocuments, DirDocuments))
        threadDownloadDocument.setDaemon(False)
        threadDownloadDocument.start()
    for lesson in lessons:
        print(" +> %s" % lesson['title'])

        infoMedia = GetVideo(lesson['url'])

        if not infoMedia: continue

        pathFileOutput = os.path.join(DirCourse, "%s.mp4" % (cleanName(lesson['title'])))
        if not pathFileOutput.startswith("\\\\?\\"):
            pathFileOutput = "\\\\?\\" + pathFileOutput
        if not os.path.exists(pathFileOutput):
            options = [
                '--stream-timeout',
                '120',
                '--loglevel',
                'warning',
                '--ringbuffer-size',
                '64M',
                '--ffmpeg-ffmpeg',
                FFMPEG_LOCATION,
                # '--output',
                # pathFileOutput,
                '--player-no-close',
                '--player',
                FFMPEG_LOCATION,
                '-a',
                '-i {filename} -y -c copy -bsf:a aac_adtstoasc -metadata "comment=Download_Edumall (^v^)" "%s"' % pathFileOutput,
                '--fifo',
                # '--stream-sorting-excludes',
                # '>720p',
                '--hls-segment-threads',
                str(NumOfThread),
                infoMedia['url'],
                'best'
            ]
            if PLUGIN_DIR:
                options.append('--plugin-dirs')
                options.append(PLUGIN_DIR)
            if "headers" not in infoMedia:
                infoMedia["headers"] = {}
            infoMedia["headers"].update({"User-Agent": USER_AGENT})
            
            for k, v in infoMedia["headers"].items():
                options.append("--http-header")
                options.append("%s=%s" % (k, v))
            streamlink_cli_main(options)
        print(50*"-")
    if threadDownloadDocument and threadDownloadDocument.is_alive(): 
        print (" +> Waiting download file document...")
        while threadDownloadDocument.is_alive():
            time.sleep(1)

def ParseOption(listOption, rawOption):
    
    listOptionDownload = listOption
    if rawOption == "": return listOptionDownload
    try:
        listOptionDownload = []
        option = rawOption.split(",")
        lenCourses = len(listOption)
        for i in option:
            if i.find("-") != -1:
                c = i.split("-")
                c = list(map(int, c))
                c[0] -= 1
                if c[0] < 0:
                    c[0] = 0
                listOptionDownload += listOption[c[0]:c[1]]
            else:
                index = int(i) - 1
                if index > lenCourses - 1:
                    index = lenCourses - 1
                if index < 0:
                    index = 0
                listOptionDownload.append(listOption[index])
        return list(listOptionDownload)
    except ValueError:
        print(">>> Lam on nhap so.")
        return None

def menu():
    if getattr(sys, 'frozen', False):
        PATH_LOGO = os.path.join(sys._MEIPASS, 'logo', 'logo.txt')
    else:
        PATH_LOGO = os.path.join(os.getcwd(), 'logo', 'logo.txt')

    with open(PATH_LOGO, 'r') as f:
        for i in f:
            sys.stdout.write(i)
            time.sleep(0.07)
    print("Version: %s" % version.VERSION)
    print("")
    print("\t0. Thoat")
    print("\t1. Tai cac khoa hoc")
    print("\t2. Tai cac bai giang con thieu")
    print("")

def main():  
    while (True):
        global g_session
        g_session = requests.Session()
        os.system('cls')
        menu()
        option = input("\t>> ")
        try:
            option = int(option)
        except ValueError:
            print("\n\t>> Nhap SO <<")
            continue
        if(option == 0):
            return
        elif(option == 1):
            DownloadCourses()
        elif(option == 2):
            DonwloadLessions()
        else:
            print("\n\t>> Khong co lua chon phu hop <<")
        g_session.close()
        input('\n\tNhan enter de tiep tuc...')

if __name__ == '__main__':
    # os.environ['HTTP_PROXY'] = "http://127.0.0.1:8888"
    # os.environ['HTTPS_PROXY'] = os.environ['HTTP_PROXY']
    description = """\
Please enter -n or --no-update to disable process update."""
    parser = argparse.ArgumentParser(description = description, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument('-n', '--no-update', action = 'store_false', dest="no_update", help = 'Disable update')
    args = parser.parse_args()
    setupLogger()
    if args.no_update:
        update.CheckUpdate()
    try:
        main()
    except KeyboardInterrupt:
        print("CTRL-C break")
        sys.exit(0)