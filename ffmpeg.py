# -*- coding: utf-8 -*-
import sys
import os
import ntpath
import subprocess
import time
import sys
import glob
import re
from natsort import natsort

reload(sys)
sys.setdefaultencoding('utf-8')

if getattr(sys, 'frozen', False):
	FFMPEG_PATH = os.path.join(sys._MEIPASS, 'ffmpeg', 'ffmpeg.exe')
else:
	FFMPEG_PATH = os.path.join(os.getcwd(), 'ffmpeg', 'ffmpeg.exe')

def path_leaf(path):
    head, tail = ntpath.split(path)
    return tail or ntpath.basename(head)

def ToMp4(currentDir, outPutFileName = ""):
	
	videoDir = os.path.join(currentDir, 'video') 
	audioDir = os.path.join(currentDir, 'audio') 

	data = open(os.path.join(videoDir, 'video.txt'), 'r').read()
	listFileNameVideo = data.split('\n')[:-1]
	data = open(os.path.join(audioDir, 'audio.txt'), 'r').read()
	listFileNameAudio = data.split('\n')[:-1]

	videoFile = os.path.join(currentDir, 'video.mp4')
	with open(videoFile, 'wb') as fw:
		for fileName in listFileNameVideo:
			with open(os.path.join(videoDir, fileName), 'rb') as fr:
				fw.write(fr.read())
				fw.flush()

	audioFile = os.path.join(currentDir, 'audio.mp4')
	with open(audioFile, 'wb') as fw:
		for fileName in listFileNameAudio:
			with open(os.path.join(audioDir, fileName), 'rb') as fr:
				fw.write(fr.read())
				fw.flush()


	dirComplete = os.path.join(currentDir[0:currentDir.rfind("\\")], 'complete')
	if not os.path.exists(dirComplete): os.mkdir(dirComplete)
	dirLog = os.path.join(dirComplete, 'log')
	if not os.path.exists(dirLog): os.mkdir(dirLog)

	if outPutFileName:	
		outputFile = os.path.join(dirComplete, outPutFileName)
		FileLog = os.path.join(dirLog, outPutFileName + ".log")
	else:
		outputFile = os.path.join(dirComplete, 'output.mp4')
		FileLog = os.path.join(dirLog, 'output.log')

	args = [FFMPEG_PATH, '-y', '-i', videoFile, '-i', audioFile, '-c', 'copy', '-map', '0:v:0', '-map', '1:a:0', outputFile]

	with open(FileLog, 'w') as f:
		process = subprocess.Popen(args, stdout = subprocess.PIPE, stderr = subprocess.STDOUT)
		for line in iter(lambda: process.stdout.read(1), ''):
			sys.stdout.write(line)
			f.write(line.rstrip('\n'))

def ConvertInFolder(Folder):
	#for folderName, subfolders, filenames in os.walk(Folder):
	ToMp4(Folder, Folder.split("\\")[-1] + ".mp4")

if __name__ == '__main__':
	ConvertInFolder(r'E:\Language\Python\edumall\Download_Edumall_beta\DOWNLOAD\Lam Ban Cung Con\Bai giang 1 Gioi thieu khoa hoc')