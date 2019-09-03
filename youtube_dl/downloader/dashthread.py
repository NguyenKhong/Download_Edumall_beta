from __future__ import unicode_literals

from threading import Thread
from Queue import Queue
from shutil import copyfileobj
import time
import os

from .fragment import FragmentFD
from ..compat import compat_urllib_error
from ..utils import (
    DownloadError,
    urljoin,
    encodeFilename
)
from natsort import natsort


class DashSegmentsFDThread(FragmentFD):
    """
    Download segments in a DASH manifest
    """

    FD_NAME = 'dashsegmentsthread'

    def real_download(self, filename, info_dict):

        fragment_base_url = info_dict.get('fragment_base_url')
        fragments = info_dict['fragments'][:1] if self.params.get(
            'test', False) else info_dict['fragments']

        ctx = {
            'filename': filename,
            'total_frags': len(fragments),
        }

        ctx['fragment_filename_sanitized'] = Queue()

        self._prepare_and_start_frag_download(ctx)
        

        frags_info = Queue()
        threads = []
        num_of_thread = int(self.params.get('num_of_thread', 5))
        
        for _ in xrange(num_of_thread):
            t = Thread(target = self._download_thread, args = (frags_info, ctx, info_dict))
            t.setDaemon(True)
            t.start()
            threads.append(t)

        for i, fragment in enumerate(fragments):
            frags_info.put((i, fragment))

        for _ in xrange(num_of_thread):
            frags_info.put(None)

        for t in threads:
            t.join()
        # frags_info.join()

        fragments_filename = list(ctx['fragment_filename_sanitized'].queue)
        #while True:
        #    fragments_filename.append(ctx['fragment_filename_sanitized'].get())
        #    ctx['fragment_filename_sanitized'].task_done()

        fragments_filename = natsort(fragments_filename)
      
        #ctx['fragment_filename_sanitized'] = sorted(ctx['fragment_filename_sanitized'])
        for filename in fragments_filename:
            with open(filename, 'rb') as f:
                self._append_fragment(ctx, f)
            os.remove(encodeFilename(filename))
        
        del ctx['fragment_filename_sanitized']
        self._finish_frag_download(ctx)
        
        return True

    def _download_thread(self, frags_info, ctx, info_dict):
        fragment_base_url = info_dict.get('fragment_base_url')
        
        fragment_retries = self.params.get('fragment_retries', 0)
        skip_unavailable_fragments = self.params.get('skip_unavailable_fragments', True)
        
        while True:
            try:
                item = frags_info.get()
                if item is None:
                    break
                i, fragment = item
                fatal = i == 0 or not skip_unavailable_fragments
                count = 0
                while count <= fragment_retries:
                    
                    try:
                        fragment_url = fragment.get('url')
                        if not fragment_url:
                            assert fragment_base_url
                            fragment_url = urljoin(fragment_base_url, fragment['path'])
                        success = self._download_fragment(ctx, fragment_url, info_dict, i)

                        if not success:
                            return False
                        break
                    except compat_urllib_error.HTTPError as err:
                        # YouTube may often return 404 HTTP error for a fragment causing the
                        # whole download to fail. However if the same fragment is immediately
                        # retried with the same request data this usually succeeds (1-2 attemps
                        # is usually enough) thus allowing to download the whole file successfully.
                        # To be future-proof we will retry all fragments that fail with any
                        # HTTP error.
                        count += 1
                        if count <= fragment_retries:
                            self.report_retry_fragment(err, frag_index, count, fragment_retries)
                    except DownloadError:
                        # Don't retry fragment if error occurred during HTTP downloading
                        # itself since it has own retry settings
                        if not fatal:
                            self.report_skip_fragment(frag_index)
                            break
                        raise

                if count > fragment_retries:
                    if not fatal:
                        self.report_skip_fragment(frag_index)
                        continue
                    self.report_error('giving up after %s fragment retries' % fragment_retries)
                    return False
            finally:
                frags_info.task_done()

    def _download_fragment(self, ctx, frag_url, info_dict, fragment_index, headers=None):
        fragment_filename = '%s-Frag%d' % (ctx['tmpfilename'], fragment_index)
        success = ctx['dl'].download(fragment_filename, {
            'url': frag_url,
            'http_headers': headers or info_dict.get('http_headers'),
        })
        if not success:
            return False
        ctx['fragment_filename_sanitized'].put(fragment_filename)
        return True

    #def __do_ytdl_file(self, ctx):
    #    return not ctx['live'] and not ctx['tmpfilename'] == '-'

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