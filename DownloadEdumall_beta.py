# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import sys

if __package__ is None and not hasattr(sys, 'frozen'):
    # direct call of __main__.py
    import os.path
    path = os.path.realpath(os.path.abspath(__file__))
    sys.path.insert(0, os.path.dirname(os.path.dirname(path)))

import requests
import os
import re
from bs4 import BeautifulSoup
import time
import timeit
from urlparse import urljoin, urlparse
import unicodedata
import datetime
import ntpath
import struct
import shutil
import threading
import urllib
import logging
import ctypes
import json
import Queue
from youtube_dl import YoutubeDL
from youtube_dl.utils import std_headers

reload(sys)
sys.setdefaultencoding('utf-8')
os.environ['HTTPSVERIFY'] = '0'

g_session = None

USER_AGENT = 'Mozilla/5.0 (Windows NT 6.1; WOW64; rv:44.0) Gecko/20100101 Firefox/44.0'
BASE_URL = 'https://beta.edumall.vn'
LOGIN_URL = 'https://sso.edumall.vn/users/sign_in'
COURSES_URL = 'https://lms.edumall.vn/home/my-course/learning'

if getattr(sys, 'frozen', False):
    FFMPEG_LOCATION = os.path.join(sys._MEIPASS, 'ffmpeg', 'ffmpeg.exe')
else:
    FFMPEG_LOCATION = os.path.join(os.getcwd(), 'ffmpeg', 'ffmpeg.exe')

std_headers['User-Agent'] = USER_AGENT

g_CurrentDir = os.getcwd()
kernel32 = ctypes.windll.kernel32

logger = logging.getLogger(__name__)

stdout_logger = logging.StreamHandler()
file_logger = logging.FileHandler("DownloadEdumall.log", mode = 'w')
formatter = logging.Formatter('%(asctime)s %(funcName)s %(levelname)s: %(message)s')
stdout_logger.setFormatter(formatter)
file_logger.setFormatter(formatter)

logger.addHandler(stdout_logger)
logger.addHandler(file_logger)
logger.setLevel(logging.INFO)

def NoAccentVietnamese(s):
    s = s.decode('utf-8')
    s = re.sub(u'Đ', 'D', s)
    s = re.sub(u'đ', 'd', s)
    return unicodedata.normalize('NFKD', unicode(s)).encode('ASCII', 'ignore')

def removeCharacters(value, deletechars = '<>:"/\|?*'):
    for c in deletechars:
        value = value.replace(c,'')
    return value

def GetFileNameFromUrl(url):
    urlParsed = urlparse(urllib.unquote(url))
    fileName = os.path.basename(urlParsed.path).encode('utf-8')
    return removeCharacters(fileName)

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


def Request(url, method = 'GET', session = None, **kwargs):
  
    if kwargs.get('headers') is None:
        kwargs['headers'] = {'User-Agent' : USER_AGENT}
    elif kwargs.get('headers').get('User-Agent') is None:
        kwargs['headers']['User-Agent'] = USER_AGENT    
   
    method = method.lower()
    if session:
        func = getattr(session, method)
    else:
        func = getattr(requests, method)
    try:
        response = func(url, **kwargs)
    except Exception as e:
        logger.critical("Error: %s - url: %s", e, url)
        return None
    
    if response.status_code != 200:
        logger.critical('Error: %s - url: %s', response.content, url)
        return None
    return response

def Login(user, password):
    
    r = Request(LOGIN_URL, session = g_session, headers = {'referer' : BASE_URL})

    authenticity_token = re.findall(r'"authenticity_token".*value="(.*?)"', r.content)
    if not authenticity_token:
        logger.critical("Dang nhap loi vui long lien he nha phat trien")
        sys.exit(1)

    payload = { 'user[email]' : user,
                'user[password]': password,
                'authenticity_token' : authenticity_token[0],
                'request' : '',
                'return' : ''
        }
    headers = { 'origin' : '{uri.scheme}://{uri.netloc}'.format(uri=urlparse(LOGIN_URL)) ,
                'referer' : LOGIN_URL
        }
    r = Request(LOGIN_URL, 'POST', data = payload, headers = headers, session = g_session)  
    
    error = re.findall(r"<p class=\"alert\">(.*?)<\/p>", r.content, re.DOTALL)
    if error and len(error[0]) != 0:
        logger.critical("Dang nhap loi: %s" % error[0])
        sys.exit(1)
    return True

def GetCourses():
    
    r = Request(COURSES_URL, session = g_session)
    if r is None:
        logger.warning("Yeu cau den %s bi loi" % COURSES_URL)
        return []
    soup = BeautifulSoup(r.content, 'html5lib')
    courses = soup.findAll('div', {'class': 'learning-card'})
    if courses == []:
        logger.warning("Loi Phan tich khoa hoc")
        return []

    UrlCourses = []
    for course in courses:
        name = course.a.find('div', {'class' : 'row ellipsis-2lines course-title'}).text
        if name == []:
            logger.warning("Loi Phan tich tieu de khoa hoc")
            return []
        UrlCourses.append({'url' : urljoin(COURSES_URL, course.a['href']), 'title' : NoAccentVietnamese(name).strip()})

    return UrlCourses

def GetLessions(url):
    r = Request(url, session = g_session)
    soup = BeautifulSoup(r.content, 'html5lib')
    Menu = soup.find('div', {'class' : 'menu'})
    
    buttonBuy = soup.findAll('a', {'class' : 'btn-red btn-buy'})
    if buttonBuy:
        print "Khoa hoc nay chua mua."
        return [] 
    if not Menu:
        logger.warning('Loi Khong the phan tich toan bo bai giang nay')
        return []
    if not Menu.a.get('href'):
        logger.warning('Loi Thieu url de phan tich bai giang')
        return []

    url = urljoin(url, Menu.a.get('href'))
    r = Request(url, session = g_session)
    soup = BeautifulSoup(r.content, 'html5lib') 
    Lessions = soup.findAll('div', {'class' : re.compile('^row chap-item')})
    if not Lessions:
        logger.warning('Loi Khong the lay danh sach bai giang')
        return []
    UrlLessions = []
    for lession in Lessions:
        name = lession.find('div', {'class' : 'row no-margin'})
        if not name:
            logger.warning("Loi Phan tich Ten bai giang")
            return []
        name = removeCharacters(name.text)
        UrlLessions.append({'url' : urljoin(url, lession.a.get('href')), 'title' : NoAccentVietnamese(name).strip()})
    return UrlLessions 

def GetVideoAndDocument(url, isGetLinkDocument = True):
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
    r = Request(url, session = g_session)
    entity_id = re.findall(r'media_uiza_id\s=\s\"(.*?)\"', r.content)
    appId = re.findall(r"appId:\s\'(.*?)\'", r.content)
    if entity_id and appId:
        infoToken = {}
        infoToken['appId'] = appId[0]
        infoToken['entity_id'] = entity_id[0]
        token = GetToken(infoToken)
        if token == False:
            return infoMedia, []
        urlMpd = GetLinkPlay(infoToken, token)
        if urlMpd == False:
            return infoMedia, []
        infoMedia['url'] = urlMpd
        infoMedia['headers'] = headers
        infoMedia['protocol'] = 'dash'
    else:    
        UrlMasterPlayList = re.findall(r'jw_video_url\s=\s"(.*)"', r.content)
        if UrlMasterPlayList:
            infoMedia['url'] = UrlMasterPlayList[0]
            infoMedia['headers'] = {'origin' : BASE_URL, 'referer' : url}
            infoMedia['protocol'] = 'm3u8'
        else:
            logger.warning('Loi lay thong tin tai video')

    if isGetLinkDocument:
        soup = BeautifulSoup(r.content, 'html5lib')
        documentDownload = soup.find('div', {'id': 'lecture-tab-download'})
        urlDocuments = [] 
        if documentDownload.text.find(u'Tài liệu của bài học') != -1:
            for i in documentDownload.findAll('li'):
                urlDocuments.append(urljoin(url, i.a.get('href'))) 
 
    return infoMedia, urlDocuments 

def DownloadFile(url, pathLocal, isSession = False, headers = {}):
    r = None
    fileName = ""
    try:
        session = None
        if isSession: session = g_session
        r = Request(url, session = session, stream = True, headers = headers)
        fileAttach = r.headers.get('Content-disposition', '')
        if 'attachment' in fileAttach:
            fileName = fileAttach[22:-1]
        else:
            fileName = GetFileNameFromUrl(url)
        
        fullPath = os.path.join(pathLocal, removeCharacters(fileName))
        if os.path.exists(fullPath):
            return True
        with open(fullPath, 'wb') as f:
            for chunk in r.iter_content(5242880):
                f.write(chunk)
        print fileName
    except Exception as e:
        logger.warning("Loi: %s - url: %s", e, url)
        return False
    # finally:
    #     if not r:
    #         r.close()
    return True

def TryDownloadDocument(urls, pathlocal):
    for url in urls:
        for i in xrange(5):
            if DownloadFile(url, pathLocal, isSession=True):
                break
            time.sleep(1)

def DownloadCourses():
    print ""
    email = raw_input(' Email: ')
    password = raw_input(' Password: ')
    if (email == "") or (password == ""):
        print ("email hoac password khong co")
        return
    
    if not Login(email, password):
        return

    print 30*"="
    Courses = GetCourses()
    if not Courses: return

    print "Danh sach cac khoa hoc: "
    i = 1
    for course in Courses:
        print "\t %d. %s" % (i, course['title'])
        i += 1

    print "\n  Lua chon tai ve cac khoa hoc"
    print "  Vd: 1, 2 hoac 1-5, 7"
    print "  Mac dinh la tai ve het\n"

    rawOption = raw_input('(%s)$: ' % email)
    CoursesDownload = ParseOption(Courses, rawOption)
    if not CoursesDownload: return
    
    try:
        NumOfThread = raw_input('So luong download [5]: ')
        if NumOfThread == "":
            NumOfThread = 5
        NumOfThread = int(NumOfThread)
    except ValueError:
        print ">>> Nhap so"
        return

    listPathDirLessions = []
    DirDownload = os.path.join(g_CurrentDir, "DOWNLOAD")
    if not os.path.exists(DirDownload): os.mkdir(DirDownload)
    print ""
    print 30*"="
    iCourses = 0
    lenCourses = len(CoursesDownload)
    for course in CoursesDownload:
        print course['title']
        pathDirCourse = os.path.join(DirDownload, removeCharacters(course['title'], '.<>:"/\|?*\r\n'))
        if not os.path.exists(pathDirCourse): os.mkdir(pathDirCourse)
        pathDirComplete = os.path.join(pathDirCourse, "complete")
        if not os.path.exists(pathDirComplete): os.mkdir(pathDirComplete)
        DirDocuments = os.path.join(pathDirComplete, "Documents")
        if not os.path.exists(DirDocuments): os.mkdir(DirDocuments)
        Lessions = GetLessions(course['url'])
        iLessions = 1
        lenLessions = len(Lessions)
        for Lession in Lessions:
            print Lession['title']
            
            lessionTitleClean = removeCharacters(Lession['title'], '.<>:"/\|?*\r\n')

            infoMedia, urlDocuments = GetVideoAndDocument(Lession['url'])
            
            if not infoMedia: continue

            threadDownloadDocument = threading.Thread(target = TryDownloadDocument, args = (urlDocuments, DirDocuments))
            threadDownloadDocument.setDaemon(False)
            threadDownloadDocument.start()

            
            std_headers.update(infoMedia['headers'])
            if not os.path.exists(os.path.join(pathDirComplete, lessionTitleClean + ".mp4")):
                outtemplate = os.path.join(pathDirComplete, lessionTitleClean + '.%(ext)s')
                
                hls_prefer_native = False
                format_opt = 'bestvideo+bestaudio'
                if infoMedia['protocol'] == 'm3u8':
                    hls_prefer_native = True
                    format_opt = 'best'

                opts = { 'format' : format_opt,
                        'num_of_thread' : NumOfThread,
                        'hls_prefer_native': hls_prefer_native,
                        'outtmpl' : outtemplate,
                        #'verbose' : True,
                        'logger' : logger,
                        'logtostderr': True,
                        'ffmpeg_location' : FFMPEG_LOCATION,
                        'consoletitle' : False
                }

                with YoutubeDL(opts) as ydl:
                    ydl.download([infoMedia['url']])
            
            percentLessions = iLessions*1.0/lenLessions*100.0
            message = "Total: %.2f%% - %s: %.2f%%" % (percentLessions/lenCourses + iCourses*1.0/lenCourses*100.0, course['title'], percentLessions)
            kernel32.SetConsoleTitleW(ctypes.c_wchar_p(message))
            
            iLessions += 1
            print 40*"*"
        
        print 50*"="
        iCourses += 1
        message = "Total: %.2f%%" % (iCourses*1.0/lenCourses*100.0)
        kernel32.SetConsoleTitleW(ctypes.c_wchar_p(message))        

def DonwloadLessions():
    print ""
    email = raw_input(' Email: ')
    password = raw_input(' Password: ')
    if (email == "") or (password == ""):
        logger.info("email hoac password khong co")
        return

    if not Login(email, password): return

    print 30*"="
    Courses = GetCourses()
    if not Courses: return

    print " Danh sach cac khoa hoc: "
    i = 1
    for course in Courses:
        print "\t %d. %s" % (i, course['title'])
        i += 1

    print "\n Lua chon tai ve 1 khoa hoc"

    rawOption = raw_input(' (%s)$: ' % email)
    try:
        lenCourses = len(Courses)
        index = int(rawOption) - 1
        if index > lenCourses:
            index = lenCourses - 1
        if index < 0:
            index = 0
        course = Courses[index]
    except ValueError:
        print " Lam on nhap SO"
        return

    DirDownload = os.path.join(g_CurrentDir, "DOWNLOAD")
    if not os.path.exists(DirDownload): os.mkdir(DirDownload)
    print 30*"="
    print ""
    print course['title']
    pathDirCourse = os.path.join(DirDownload, removeCharacters(course['title'], '.<>:"/\|?*\r\n'))
    if not os.path.exists(pathDirCourse): os.mkdir(pathDirCourse)
    pathDirComplete = os.path.join(pathDirCourse, "complete")
    if not os.path.exists(pathDirComplete): os.mkdir(pathDirComplete)
    DirDocuments = os.path.join(pathDirComplete, "Documents")
    if not os.path.exists(DirDocuments): os.mkdir(DirDocuments)
    Lessions = GetLessions(course['url'])
    if not Lessions: return
    print "Danh sach cac bai giang: "
    i = 1
    for Lession in Lessions:
        print "\t %d. %s" % (i, Lession['title'])
        i += 1

    print "\n  Lua chon tai ve cac bai giang"
    print "  Vd: 1, 2 hoac 1-5, 7"
    print "  Mac dinh la tai ve het\n"

    rawOption = raw_input('(%s)$: ' % email)
    LessionsDownload = ParseOption(Lessions, rawOption)
    if not LessionsDownload: return

    try:
        NumOfThread = raw_input(' So luong download cung luc [5]: ')
        if NumOfThread == "":
            NumOfThread = 5
        NumOfThread = int(NumOfThread)
    except ValueError:
        print ">>> Nhap so"
        return

    for Lession in LessionsDownload:
        print Lession['title']
        
        lessionTitleClean = removeCharacters(Lession['title'], '.<>:"/\|?*\r\n')

        infoMedia, urlDocuments = GetVideoAndDocument(Lession['url'])
        
        if not infoMedia: continue

        threadDownloadDocument = threading.Thread(target = TryDownloadDocument, args = (urlDocuments, DirDocuments))
        threadDownloadDocument.setDaemon(False)
        threadDownloadDocument.start()

        
        std_headers.update(infoMedia['headers'])
        if not os.path.exists(os.path.join(pathDirComplete, lessionTitleClean + ".mp4")):
            outtemplate = os.path.join(pathDirComplete, lessionTitleClean + '.%(ext)s')
            
            hls_prefer_native = False
            format_opt = 'bestvideo+bestaudio'
            if infoMedia['protocol'] == 'm3u8':
                hls_prefer_native = True
                format_opt = 'best'

            opts = { 'format' : format_opt,
                    'num_of_thread' : NumOfThread,
                    'hls_prefer_native': hls_prefer_native,
                    'outtmpl' : outtemplate,
                    #'verbose' : True,
                    'logger' : logger,
                    'logtostderr': True,
                    'ffmpeg_location' : FFMPEG_LOCATION,
                    'consoletitle' : False
            }

            with YoutubeDL(opts) as ydl:
                ydl.download([infoMedia['url']])

        print 50*"="

def ParseOption(listOption, rawOption):
    
    listOptionDownload = listOption
    if rawOption != "":
        try:
            listOptionDownload = []
            option = rawOption.split(",")
            lenCourses = len(listOption)
            for i in option:
                if i.find("-") != -1:
                    c = i.split("-")
                    c = map(int, c)
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
            print ">>> Lam on nhap so."
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

    print ""
    print "\t0. Thoat"
    print "\t1. Tai cac khoa hoc"
    print "\t2. Tai cac bai giang con thieu"
    print ""

def main():  
    while (True):
        global g_session
        g_session = requests.Session()
        os.system('cls')
        menu()
        option = raw_input("\t>> ")
        try:
            option = int(option)
        except ValueError:
            print "\n\t>> Nhap SO <<"
            continue
        if(option == 0):
            return
        elif(option == 1):
            DownloadCourses()
        elif(option == 2):
            DonwloadLessions()
        else:
            print "\n\t>> Khong co lua chon phu hop <<"
        g_session.close()
        raw_input('\n\tNhan enter de tiep tuc...')

if __name__ == '__main__':
    #os.environ['HTTP_PROXY'] = "http://127.0.0.1:8888"
    #os.environ['HTTPS_PROXY'] = os.environ['HTTP_PROXY']

    try:
        main()
    except KeyboardInterrupt:
        print "CTRL-C break"