from __future__ import unicode_literals

import re
import binascii
from Queue import Queue
import time
from threading import Thread
from shutil import copyfileobj
import os
try:
    from Crypto.Cipher import AES
    can_decrypt_frag = True
except ImportError:
    can_decrypt_frag = False

from .fragment import FragmentFD
from .external import FFmpegFD

from ..compat import (
    compat_urllib_error,
    compat_urlparse,
    compat_struct_pack,
)
from ..utils import (
    parse_m3u8_attributes,
    update_url_query,
    sanitize_open,
    encodeFilename,
)

from natsort import natsort


class HlsFDThread(FragmentFD):
    """ A limited implementation that does not require ffmpeg """

    FD_NAME = 'hlsnativethread'

    @staticmethod
    def can_download(manifest, info_dict):
        UNSUPPORTED_FEATURES = (
            r'#EXT-X-KEY:METHOD=(?!NONE|AES-128)',  # encrypted streams [1]
            # r'#EXT-X-BYTERANGE',  # playlists composed of byte ranges of media files [2]

            # Live streams heuristic does not always work (e.g. geo restricted to Germany
            # http://hls-geo.daserste.de/i/videoportal/Film/c_620000/622873/format,716451,716457,716450,716458,716459,.mp4.csmil/index_4_av.m3u8?null=0)
            # r'#EXT-X-MEDIA-SEQUENCE:(?!0$)',  # live streams [3]

            # This heuristic also is not correct since segments may not be appended as well.
            # Twitch vods of finished streams have EXT-X-PLAYLIST-TYPE:EVENT despite
            # no segments will definitely be appended to the end of the playlist.
            # r'#EXT-X-PLAYLIST-TYPE:EVENT',  # media segments may be appended to the end of
            #                                 # event media playlists [4]

            # 1. https://tools.ietf.org/html/draft-pantos-http-live-streaming-17#section-4.3.2.4
            # 2. https://tools.ietf.org/html/draft-pantos-http-live-streaming-17#section-4.3.2.2
            # 3. https://tools.ietf.org/html/draft-pantos-http-live-streaming-17#section-4.3.3.2
            # 4. https://tools.ietf.org/html/draft-pantos-http-live-streaming-17#section-4.3.3.5
        )
        check_results = [not re.search(feature, manifest) for feature in UNSUPPORTED_FEATURES]
        
        is_aes128_enc = '#EXT-X-KEY:METHOD=AES-128' in manifest
        check_results.append(can_decrypt_frag or not is_aes128_enc)
        check_results.append(not (is_aes128_enc and r'#EXT-X-BYTERANGE' in manifest))
        check_results.append(not info_dict.get('is_live'))
        return all(check_results)

    def real_download(self, filename, info_dict):
        man_url = info_dict['url']
        self.to_screen('[%s] Downloading m3u8 manifest' % self.FD_NAME)

        urlh = self.ydl.urlopen(self._prepare_url(info_dict, man_url))
        man_url = urlh.geturl()
        s = urlh.read().decode('utf-8', 'ignore')

        if not self.can_download(s, info_dict):
            if info_dict.get('extra_param_to_segment_url'):
                self.report_error('pycrypto not found. Please install it.')
                return False
            self.report_warning(
                'hlsnative has detected features it does not support, '
                'extraction will be delegated to ffmpeg')
            fd = FFmpegFD(self.ydl, self.params)
            for ph in self._progress_hooks:
                fd.add_progress_hook(ph)
            return fd.real_download(filename, info_dict)

        def is_ad_fragment_start(s):
            return (s.startswith('#ANVATO-SEGMENT-INFO') and 'type=ad' in s or
                    s.startswith('#UPLYNK-SEGMENT') and s.endswith(',ad'))

        def is_ad_fragment_end(s):
            return (s.startswith('#ANVATO-SEGMENT-INFO') and 'type=master' in s or
                    s.startswith('#UPLYNK-SEGMENT') and s.endswith(',segment'))

        media_frags = 0
        ad_frags = 0
        ad_frag_next = False
        for line in s.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith('#'):
                if is_ad_fragment_start(line):
                    ad_frag_next = True
                elif is_ad_fragment_end(line):
                    ad_frag_next = False
                continue
            if ad_frag_next:
                ad_frags += 1
                continue
            media_frags += 1

        ctx = {
            'filename': filename,
            'total_frags': media_frags,
            'ad_frags': ad_frags,
        }

        ctx['fragment_filename_sanitized'] = Queue()

        self._prepare_and_start_frag_download(ctx)

        frags_info = Queue()
        decrypt_info = {'METHOD': 'NONE', 'KEY': None}

        num_of_thread = int(self.params.get('num_of_thread', 10))
        threads = []
        for _ in xrange(num_of_thread):
            t = Thread(target = self._download_thread, args = [frags_info, ctx, info_dict, decrypt_info])
            t.setDaemon(True)
            t.start()
            threads.append(t)

        extra_query = None
        extra_param_to_segment_url = info_dict.get('extra_param_to_segment_url')
        if extra_param_to_segment_url:
            extra_query = compat_urlparse.parse_qs(extra_param_to_segment_url)
        i = 0
        media_sequence = 0
        
        byte_range = {}
        frag_index = 0
        ad_frag_next = False
        for line in s.splitlines():
            line = line.strip()
            if line:
                if not line.startswith('#'):
                    if ad_frag_next:
                        continue
                    frag_index += 1
                    if frag_index <= ctx['fragment_index']:
                        continue
                    frag_url = (
                        line
                        if re.match(r'^https?://', line)
                        else compat_urlparse.urljoin(man_url, line))
                    if extra_query:
                        frag_url = update_url_query(frag_url, extra_query)
                    headers = info_dict.get('http_headers', {})
                    if byte_range:
                        headers['Range'] = 'bytes=%d-%d' % (byte_range['start'], byte_range['end'])
                    frags_info.put((frag_index, frag_url, headers))
                    
                elif line.startswith('#EXT-X-KEY'):
                    decrypt_url = decrypt_info.get('URI')
                    decrypt_info.update(parse_m3u8_attributes(line[11:]))
                    
                    if decrypt_info['METHOD'] == 'AES-128':
                        if 'IV' in decrypt_info:
                            decrypt_info['IV'] = binascii.unhexlify(decrypt_info['IV'][2:].zfill(32))
                        if not re.match(r'^https?://', decrypt_info['URI']):
                            decrypt_info['URI'] = compat_urlparse.urljoin(
                                man_url, decrypt_info['URI'])
                        if extra_query:
                            decrypt_info['URI'] = update_url_query(decrypt_info['URI'], extra_query)
                        if decrypt_url != decrypt_info['URI']:
                            decrypt_info['KEY'] = None
                        decrypt_info['IV'] = decrypt_info.get('IV') or compat_struct_pack('>8xq', media_sequence)
                        decrypt_info['KEY'] = decrypt_info.get('KEY') or self.ydl.urlopen(
                            self._prepare_url(info_dict, decrypt_info['URI'])).read()
                        if len(decrypt_info['KEY']) % 16:
                            self.report_warning("[%s] download key decrypt failed" % self.FD_NAME)
                            return False
                elif line.startswith('#EXT-X-MEDIA-SEQUENCE'):
                    media_sequence = int(line[22:])
                elif line.startswith('#EXT-X-BYTERANGE'):
                    splitted_byte_range = line[17:].split('@')
                    sub_range_start = int(splitted_byte_range[1]) if len(splitted_byte_range) == 2 else byte_range['end']
                    byte_range = {
                        'start': sub_range_start,
                        'end': sub_range_start + int(splitted_byte_range[0]),
                    }
                elif is_ad_fragment_start(line):
                    ad_frag_next = True
                elif is_ad_fragment_end(line):
                    ad_frag_next = False

        for t in threads:
            frags_info.put(None)

        for t in threads:
            t.join()

        # frags_info.join()

        fragments_filename = list(ctx['fragment_filename_sanitized'].queue)
        #fragments_filename.sort()
        fragments_filename = natsort(fragments_filename)

        for filename in fragments_filename:
            with open(filename, 'rb') as f:
                self._append_fragment(ctx, f)
            os.remove(encodeFilename(filename))

        self._finish_frag_download(ctx)

        return True

    def _download_thread(self, frags_info, ctx, info_dict, decrypt_info):
        fragment_retries = self.params.get('fragment_retries', 0)
        skip_unavailable_fragments = self.params.get('skip_unavailable_fragments', True)
        test = self.params.get('test', False)

        while True:
            try:
                item = frags_info.get()
                if item is None:
                    break
                frag_index, frag_url, headers = item
                count = 0
                while count <= fragment_retries:
                    try:
                        success, frag_content, fragment_filename = self._download_fragment(
                            ctx, frag_url, info_dict, frag_index, headers)
                        if not success:
                            continue
                        break
                    except compat_urllib_error.HTTPError as err:
                        # Unavailable (possibly temporary) fragments may be served.
                        # First we try to retry then either skip or abort.
                        # See https://github.com/ytdl-org/youtube-dl/issues/10165,
                        # https://github.com/ytdl-org/youtube-dl/issues/10448).
                        count += 1
                        if count <= fragment_retries:
                            self.report_retry_fragment(err, frag_index, count, fragment_retries)
                if count > fragment_retries:
                    if skip_unavailable_fragments:
                        self.report_skip_fragment(frag_index)
                        continue
                    self.report_error(
                        'giving up after %s fragment retries' % fragment_retries)
                    return False
                
                if decrypt_info['METHOD'] == 'AES-128':
                    frag_content = AES.new(
                        decrypt_info['KEY'], AES.MODE_CBC, decrypt_info['IV']).decrypt(frag_content)
                    down_decrypt, _ = sanitize_open(fragment_filename, 'wb')
                    down_decrypt.write(frag_content)
                    down_decrypt.close()
            finally:
                frags_info.task_done()



    def _download_fragment(self, ctx, frag_url, info_dict, fragment_index, headers=None):
        fragment_filename = '%s-Frag%d' % (ctx['tmpfilename'], fragment_index)
        success = ctx['dl'].download(fragment_filename, {
            'url': frag_url,
            'http_headers': headers or info_dict.get('http_headers'),
        })
        if not success:
            return False, None, None
        down, frag_sanitized = sanitize_open(fragment_filename, 'rb')
        ctx['fragment_filename_sanitized'].put(frag_sanitized)
        frag_content = down.read()
        down.close()
        return True, frag_content, frag_sanitized

    def _append_fragment(self, ctx, frag_fileobj):
        try:
            copyfileobj(frag_fileobj, ctx['dest_stream'])
            ctx['dest_stream'].flush()
        finally:
            pass
            #if self.__do_ytdl_file(ctx):
            #    self._write_ytdl_file(ctx)
            
    def _start_frag_download(self, ctx):
        total_frags = ctx['total_frags']
        # This dict stores the download progress, it's updated by the progress
        # hook
        state = {
            'status': 'downloading',
            'downloaded_bytes': ctx['complete_frags_downloaded_bytes'],
            'fragment_index': ctx['fragment_index'],
            'fragment_count': total_frags,
            'filename': ctx['filename'],
            'tmpfilename': ctx['tmpfilename'],
        }

        start = time.time()
        ctx.update({
            'started': start,
            # Amount of fragment's bytes downloaded by the time of the previous
            # frag progress hook invocation
            'prev_frag_downloaded_bytes': 0,
        })
        def frag_progress_hook(s):
            if s['status'] not in ('finished'):
                return
            state['total_bytes'] = ctx['total_frags']
            state['downloaded_bytes'] = ctx['fragment_filename_sanitized'].qsize()
            state['status'] = 'downloading'
            if state['total_bytes'] <= state['downloaded_bytes']:
                state['status'] = 'finished'
            self._hook_progress(state)

        ctx['dl'].add_progress_hook(frag_progress_hook)

        return start