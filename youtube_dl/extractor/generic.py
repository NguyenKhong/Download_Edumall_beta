# coding: utf-8

from __future__ import unicode_literals

import os
import re
import sys

from .common import InfoExtractor
from ..compat import (
    compat_etree_fromstring,
    compat_str,
    compat_urllib_parse_unquote,
    compat_urlparse,
    compat_xml_parse_error,
)
from ..utils import (
    determine_ext,
    ExtractorError,
    float_or_none,
    HEADRequest,
    is_html,
    js_to_json,
    KNOWN_EXTENSIONS,
    merge_dicts,
    mimetype2ext,
    orderedSet,
    sanitized_Request,
    smuggle_url,
    unescapeHTML,
    unified_strdate,
    unsmuggle_url,
    UnsupportedError,
    xpath_text,
)

class GenericIE(InfoExtractor):
    IE_DESC = 'Generic downloader that works on some sites'
    _VALID_URL = r'.*'
    IE_NAME = 'generic'
    _TESTS = []

    def report_following_redirect(self, new_url):
        """Report information extraction."""
        self._downloader.to_screen('[redirect] Following redirect to %s' % new_url)

    def _extract_rss(self, url, video_id, doc):
        playlist_title = doc.find('./channel/title').text
        playlist_desc_el = doc.find('./channel/description')
        playlist_desc = None if playlist_desc_el is None else playlist_desc_el.text

        entries = []
        for it in doc.findall('./channel/item'):
            next_url = None
            enclosure_nodes = it.findall('./enclosure')
            for e in enclosure_nodes:
                next_url = e.attrib.get('url')
                if next_url:
                    break

            if not next_url:
                next_url = xpath_text(it, 'link', fatal=False)

            if not next_url:
                continue

            entries.append({
                '_type': 'url_transparent',
                'url': next_url,
                'title': it.find('title').text,
            })

        return {
            '_type': 'playlist',
            'id': url,
            'title': playlist_title,
            'description': playlist_desc,
            'entries': entries,
        }

    def _real_extract(self, url):
        if url.startswith('//'):
            return self.url_result(self.http_scheme() + url)

        parsed_url = compat_urlparse.urlparse(url)
        if not parsed_url.scheme:
            default_search = self._downloader.params.get('default_search')
            if default_search is None:
                default_search = 'fixup_error'

            if default_search in ('auto', 'auto_warning', 'fixup_error'):
                if '/' in url:
                    self._downloader.report_warning('The url doesn\'t specify the protocol, trying with http')
                    return self.url_result('http://' + url)
                elif default_search != 'fixup_error':
                    if default_search == 'auto_warning':
                        if re.match(r'^(?:url|URL)$', url):
                            raise ExtractorError(
                                'Invalid URL:  %r . Call youtube-dl like this:  youtube-dl -v "https://www.youtube.com/watch?v=BaW_jenozKc"  ' % url,
                                expected=True)
                        else:
                            self._downloader.report_warning(
                                'Falling back to youtube search for  %s . Set --default-search "auto" to suppress this warning.' % url)
                    return self.url_result('ytsearch:' + url)

            if default_search in ('error', 'fixup_error'):
                raise ExtractorError(
                    '%r is not a valid URL. '
                    'Set --default-search "ytsearch" (or run  youtube-dl "ytsearch:%s" ) to search YouTube'
                    % (url, url), expected=True)
            else:
                if ':' not in default_search:
                    default_search += ':'
                return self.url_result(default_search + url)

        url, smuggled_data = unsmuggle_url(url)
        force_videoid = None
        is_intentional = smuggled_data and smuggled_data.get('to_generic')
        if smuggled_data and 'force_videoid' in smuggled_data:
            force_videoid = smuggled_data['force_videoid']
            video_id = force_videoid
        else:
            video_id = self._generic_id(url)

        self.to_screen('%s: Requesting header' % video_id)

        head_req = HEADRequest(url)
        head_response = self._request_webpage(
            head_req, video_id,
            note=False, errnote='Could not send HEAD request to %s' % url,
            fatal=False)

        if head_response is not False:
            # Check for redirect
            new_url = compat_str(head_response.geturl())
            if url != new_url:
                self.report_following_redirect(new_url)
                if force_videoid:
                    new_url = smuggle_url(
                        new_url, {'force_videoid': force_videoid})
                return self.url_result(new_url)

        full_response = None
        if head_response is False:
            request = sanitized_Request(url)
            request.add_header('Accept-Encoding', '*')
            full_response = self._request_webpage(request, video_id)
            head_response = full_response

        info_dict = {
            'id': video_id,
            'title': self._generic_title(url),
            'upload_date': unified_strdate(head_response.headers.get('Last-Modified'))
        }

        # Check for direct link to a video
        content_type = head_response.headers.get('Content-Type', '').lower()
        m = re.match(r'^(?P<type>audio|video|application(?=/(?:ogg$|(?:vnd\.apple\.|x-)?mpegurl)))/(?P<format_id>[^;\s]+)', content_type)
        if m:
            format_id = compat_str(m.group('format_id'))
            if format_id.endswith('mpegurl'):
                formats = self._extract_m3u8_formats(url, video_id, 'mp4')
            elif format_id == 'f4m':
                formats = self._extract_f4m_formats(url, video_id)
            else:
                formats = [{
                    'format_id': format_id,
                    'url': url,
                    'vcodec': 'none' if m.group('type') == 'audio' else None
                }]
                info_dict['direct'] = True
            self._sort_formats(formats)
            info_dict['formats'] = formats
            return info_dict

        if not self._downloader.params.get('test', False) and not is_intentional:
            force = self._downloader.params.get('force_generic_extractor', False)
            self._downloader.report_warning(
                '%s on generic information extractor.' % ('Forcing' if force else 'Falling back'))

        if not full_response:
            request = sanitized_Request(url)
            # Some webservers may serve compressed content of rather big size (e.g. gzipped flac)
            # making it impossible to download only chunk of the file (yet we need only 512kB to
            # test whether it's HTML or not). According to youtube-dl default Accept-Encoding
            # that will always result in downloading the whole file that is not desirable.
            # Therefore for extraction pass we have to override Accept-Encoding to any in order
            # to accept raw bytes and being able to download only a chunk.
            # It may probably better to solve this by checking Content-Type for application/octet-stream
            # after HEAD request finishes, but not sure if we can rely on this.
            request.add_header('Accept-Encoding', '*')
            full_response = self._request_webpage(request, video_id)

        first_bytes = full_response.read(512)

        # Is it an M3U playlist?
        if first_bytes.startswith(b'#EXTM3U'):
            info_dict['formats'] = self._extract_m3u8_formats(url, video_id, 'mp4')
            self._sort_formats(info_dict['formats'])
            return info_dict

        # Maybe it's a direct link to a video?
        # Be careful not to download the whole thing!
        if not is_html(first_bytes):
            self._downloader.report_warning(
                'URL could be a direct video link, returning it as such.')
            info_dict.update({
                'direct': True,
                'url': url,
            })
            return info_dict

        webpage = self._webpage_read_content(
            full_response, url, video_id, prefix=first_bytes)

        self.report_extraction(video_id)

        # Is it an RSS feed, a SMIL file, an XSPF playlist or a MPD manifest?
        try:
            doc = compat_etree_fromstring(webpage.encode('utf-8'))
            if doc.tag == 'rss':
                return self._extract_rss(url, video_id, doc)
            elif doc.tag == 'SmoothStreamingMedia':
                info_dict['formats'] = self._parse_ism_formats(doc, url)
                self._sort_formats(info_dict['formats'])
                return info_dict
            elif re.match(r'^(?:{[^}]+})?smil$', doc.tag):
                smil = self._parse_smil(doc, url, video_id)
                self._sort_formats(smil['formats'])
                return smil
            elif doc.tag == '{http://xspf.org/ns/0/}playlist':
                return self.playlist_result(
                    self._parse_xspf(
                        doc, video_id, xspf_url=url,
                        xspf_base_url=compat_str(full_response.geturl())),
                    video_id)
            elif re.match(r'(?i)^(?:{[^}]+})?MPD$', doc.tag):
                info_dict['formats'] = self._parse_mpd_formats(
                    doc,
                    mpd_base_url=compat_str(full_response.geturl()).rpartition('/')[0],
                    mpd_url=url)
                self._sort_formats(info_dict['formats'])
                return info_dict
            elif re.match(r'^{http://ns\.adobe\.com/f4m/[12]\.0}manifest$', doc.tag):
                info_dict['formats'] = self._parse_f4m_formats(doc, url, video_id)
                self._sort_formats(info_dict['formats'])
                return info_dict
        except compat_xml_parse_error:
            pass
