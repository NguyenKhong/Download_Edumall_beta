# -*- coding: utf-8 -*-
import requests
import os
import sys
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
import ffmpeg
import threading
import urllib
import logging
import ctypes
import json
import Queue
from mpegdash.parser import MPEGDASHParser

reload(sys)
sys.setdefaultencoding('utf-8')
os.environ['HTTPSVERIFY'] = '0'

g_session = None

USER_AGENT = 'Mozilla/5.0 (Windows NT 6.1; WOW64; rv:44.0) Gecko/20100101 Firefox/44.0'
BASE_URL = 'https://beta.edumall.vn'
LOGIN_URL = 'https://lms.edumall.vn/users/sign_in'
COURSES_URL = 'https://lms.edumall.vn/home/my-course/learning'

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

def GetFileNameFromUrl(url):
    urlParsed = urlparse(urllib.unquote(url))
    fileName = os.path.basename(urlParsed.path).encode('utf-8')
    return removeCharacters(fileName)

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
    
    error = re.findall(r"<div class='error-message'>\s(.*?)\n<\/div>", r.content, re.DOTALL)
    if error:
        logger.critical("Dang nhap loi: %s" % error[0])
        sys.exit(1)
    return True

def GetCourses():
    
    r = Request(COURSES_URL, session = g_session)
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

    def UrlForMaxBandwith(baseUrl, adaptation_set):
        bandwidth = []
        for rep in adaptation_set.representations:
            bandwidth.append(int(rep.bandwidth))
        
        urls = Queue.Queue()
        seg = adaptation_set.representations[bandwidth.index(max(bandwidth))].segment_lists[0]
        if seg.initializations[0].source_url:
            urls.put(urljoin(baseUrl, seg.initializations[0].source_url))
        for seg_url in seg.segment_urls:
            urls.put(urljoin(baseUrl, seg_url.media))
        return urls

    def ExtractInfoMedia(urlMpd):
        r = Request(urlMpd, headers = headers)
        infoVideo = {}
        infoAudio = {}
        try:
            mpd = MPEGDASHParser.parse(r.content)
            period = mpd.periods[0]

            for adapt_set in period.adaptation_sets:
                if 'video' in adapt_set.mime_type:
                    infoVideo['urls'] = UrlForMaxBandwith(urlMpd, adapt_set)
                if 'audio' in adapt_set.mime_type:
                    infoAudio['urls'] = UrlForMaxBandwith(urlMpd, adapt_set)
            return {'video' : infoVideo, 'audio' : infoAudio, 'headers' : headers}
        except Exception as e:
            logger.warning("Loi: %s - url: %s" % (e, urlMpd))
            return False

    r = Request(url, session = g_session)
    entity_id = re.findall(r'media_uiza_id\s=\s\"(.*?)\"', r.content)
    appId = re.findall(r"appId:\s\'(.*?)\'", r.content)
    infoToken = {}
    infoMedia = {}
    if entity_id and appId:
        infoToken['appId'] = appId[0]
        infoToken['entity_id'] = entity_id[0]
        token = GetToken(infoToken)
        if token == False:
            return infoMedia, []
        urlMpd = GetLinkPlay(infoToken, token)
        if urlMpd == False:
            return infoMedia, []
        infoMedia = ExtractInfoMedia(urlMpd)
        if infoMedia == False:
            return infoMedia, []
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
    try:
        fileName = GetFileNameFromUrl(url)
        session = None
        if isSession: session = g_session
        r = Request(url, session = session, stream = True, headers = headers)
        
        with open(os.path.join(pathLocal, fileName), 'wb') as f:
            for chunk in r.iter_content(5242880):
                f.write(chunk)
        print fileName
    except Exception as e:
        logger.warning("Loi: %s - url: %s", e, url)
        return False
    finally:
        if not r:
            r.close()
    return True

def TryDownloadMedia(info, pathLocal, headers = {}):
    i = 0
    q = info['urls']
    while True:
        url = q.get()
        for i in xrange(5):
            if DownloadFile(url, pathLocal, headers = headers):
                break
            time.sleep(1)
        if i == 4:
            logger.warning("Tai tap tin %s khong thanh cong", url)
        q.task_done()

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
        NumOfThread = raw_input('So luong download [6]: ')
        if NumOfThread == "":
            NumOfThread = 6
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
            pathDirLession = os.path.join(pathDirCourse, lessionTitleClean)
            if not os.path.exists(pathDirLession): os.mkdir(pathDirLession) 
            listPathDirLessions.append(pathDirLession)
            pathDirLessionVideo = os.path.join(pathDirLession, 'video')
            if not os.path.exists(pathDirLessionVideo): os.mkdir(pathDirLessionVideo)
            pathDirLessionAudio = os.path.join(pathDirLession, 'audio')
            if not os.path.exists(pathDirLessionAudio): os.mkdir(pathDirLessionAudio)

            infoMedia, urlDocuments = GetVideoAndDocument(Lession['url'])
            
            if not infoMedia: continue

            threadDownloadDocument = threading.Thread(target = TryDownloadDocument, args = (urlDocuments, DirDocuments))
            threadDownloadDocument.setDaemon(True)
            threadDownloadDocument.start()

            MakeListFileName(list(infoMedia['video']['urls'].queue), os.path.join(pathDirLessionVideo, 'video.txt'))
            MakeListFileName(list(infoMedia['audio']['urls'].queue), os.path.join(pathDirLessionAudio, 'audio.txt'))
            

            for i in range(int(NumOfThread/2)):
                thread = threading.Thread(target = TryDownloadMedia, args = (infoMedia['video'], pathDirLessionVideo, infoMedia['headers']))
                thread.setDaemon(True)
                thread.start()

            for i in range(int(NumOfThread/2)):
                thread = threading.Thread(target = TryDownloadMedia, args = (infoMedia['audio'], pathDirLessionAudio, infoMedia['headers']))
                thread.setDaemon(True)
                thread.start()

            infoMedia['video']['urls'].join()
            infoMedia['audio']['urls'].join()
            threadDownloadDocument.join()

            print "Xuat dinh dang mp4"
            ffmpeg.ConvertInFolder(pathDirLession)

            if os.path.exists(os.path.join(pathDirComplete, lessionTitleClean + ".mp4")):
                shutil.rmtree(pathDirLession)
            
            percentLessions = iLessions*1.0/lenLessions*100.0
            kernel32.SetConsoleTitleA("Tong: %.2f%% - %s: %.2f%%" % (percentLessions/lenCourses + iCourses*1.0/lenCourses*100.0, course['title'], percentLessions))
            iLessions += 1
            #time.sleep(2)

        print 40*"="
        iCourses += 1
        kernel32.SetConsoleTitleA("Tong: %.2f%%" % (iCourses*1.0/lenCourses*100.0))
        

    #if IsConvert:
    #    print "Converting ..."
    #    for i in listPathDirLessions:

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
        NumOfThread = raw_input(' So luong download cung luc [6]: ')
        if NumOfThread == "":
            NumOfThread = 6
        NumOfThread = int(NumOfThread)
    except ValueError:
        print ">>> Nhap so"
        return

    for Lession in LessionsDownload:
        print Lession['title']
        
        lessionTitleClean = removeCharacters(Lession['title'], '.<>:"/\|?*\r\n')
        pathDirLession = os.path.join(pathDirCourse, lessionTitleClean)
        if not os.path.exists(pathDirLession): os.mkdir(pathDirLession) 
        pathDirLessionVideo = os.path.join(pathDirLession, 'video')
        if not os.path.exists(pathDirLessionVideo): os.mkdir(pathDirLessionVideo)
        pathDirLessionAudio = os.path.join(pathDirLession, 'audio')
        if not os.path.exists(pathDirLessionAudio): os.mkdir(pathDirLessionAudio)

        infoMedia, urlDocuments = GetVideoAndDocument(Lession['url'])
        
        if not infoMedia: continue

        threadDownloadDocument = threading.Thread(target = TryDownloadDocument, args = (urlDocuments, DirDocuments))
        threadDownloadDocument.setDaemon(True)
        threadDownloadDocument.start()

        MakeListFileName(list(infoMedia['video']['urls'].queue), os.path.join(pathDirLessionVideo, 'video.txt'))
        MakeListFileName(list(infoMedia['audio']['urls'].queue), os.path.join(pathDirLessionAudio, 'audio.txt'))
        

        for i in range(int(NumOfThread/2)):
            thread = threading.Thread(target = TryDownloadMedia, args = (infoMedia['video'], pathDirLessionVideo, infoMedia['headers']))
            thread.setDaemon(True)
            thread.start()

        for i in range(int(NumOfThread/2)):
            thread = threading.Thread(target = TryDownloadMedia, args = (infoMedia['audio'], pathDirLessionAudio, infoMedia['headers']))
            thread.setDaemon(True)
            thread.start()

        infoMedia['video']['urls'].join()
        infoMedia['audio']['urls'].join()
        threadDownloadDocument.join()

        print "Xuat dinh dang mp4"
        ffmpeg.ConvertInFolder(pathDirLession)

        if os.path.exists(os.path.join(pathDirComplete, lessionTitleClean + ".mp4")):
            shutil.rmtree(pathDirLession)
        print 40*"="

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
            
def MakeListFileName(urls, path):
    with open(path, 'w') as fw:
        for url in urls:
            fileName = GetFileNameFromUrl(url)
            fw.write(fileName + "\n")

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
        g_session.headers['user-agent'] = USER_AGENT
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


