import re
import logging
import time
import math
import random

from streamlink import StreamError
from streamlink.compat import urlparse
from streamlink.plugin import Plugin
from streamlink.stream import HLSStream
from streamlink.stream.hls import HLSStreamReader, HLSStreamWriter
from streamlink.plugin.plugin import parse_url_params
from streamlink.utils import update_scheme
from streamlink.stream.ffmpegmux import FFMPEGMuxer, MuxedStream
from streamlink.stream import hls_playlist

log = logging.getLogger(__name__)

class KTCityHLSStreamWriter(HLSStreamWriter):
    """docstring for KTCityHLSStreamWorker"""

    def makeToken(self, code):
        token = ''
        salt = '123456780ABCDEFGHKLMNOPYTRQW'
        for i in range(len(code)):
            if i % 2 == 0:
                token += code[i]
            else:
                token += salt[math.floor((random.random() * len(salt)))]
                token += code[i]
        return token

    def requestToken(self):
        
        url = "https://stream.kt.city/video/touch.php"
        r = self.session.http.get(url,
                            timeout=self.timeout,
                            exception=StreamError,
                            retries=self.retries,
                            )
        return self.makeToken(r.text)

    def fetch(self, sequence, retries=None):
        if self.closed or not retries:
            return

        try:
            request_params = self.create_request_params(sequence)
            # skip ignored segment names
            if self.ignore_names and self.ignore_names_re.search(sequence.segment.uri):
                log.debug("Skipping segment {0}".format(sequence.num))
                return
            params = request_params.pop('params', {})
            params["token"] = self.requestToken()
            request_params["params"] = params
            return self.session.http.get(sequence.segment.uri,
                                         timeout=self.timeout,
                                         exception=StreamError,
                                         retries=self.retries,
                                         **request_params)
        except StreamError as err:
            log.error("Failed to open segment {0}: {1}", sequence.num, err)
            return

class KTCityHLSStreamReader(HLSStreamReader):
    """docstring for KTCityHLSStreamReader"""
    __writer__ = KTCityHLSStreamWriter

class KTCityMuxedHLSStream(MuxedStream):
    __shortname__ = "hls-multi"

    def __init__(self, session, video, audio, force_restart=False, ffmpeg_options=None, **args):
        tracks = [video]
        maps = ["0:v?", "0:a?"]
        if audio:
            if isinstance(audio, list):
                tracks.extend(audio)
            else:
                tracks.append(audio)
        for i in range(1, len(tracks)):
            maps.append("{0}:a".format(i))
        substreams = map(lambda url: KTCityHLS(session, url, force_restart=force_restart, **args), tracks)
        ffmpeg_options = ffmpeg_options or {}

        super(KTCityMuxedHLSStream, self).__init__(session, *substreams, format="mpegts", maps=maps, **ffmpeg_options)
        
class KTCityHLS(HLSStream):
    """docstring for KTCityHLS"""
    _shortname__ = "KTCityHLS"

    def open(self):
        reader = KTCityHLSStreamReader(self)
        reader.open()
        return reader

    @classmethod
    def parse_variant_playlist(cls, session_, url, name_key="name",
                               name_prefix="", check_streams=False,
                               force_restart=False, name_fmt=None,
                               start_offset=0, duration=None,
                               **request_params):
        """Attempts to parse a variant playlist and return its streams.

        :param url: The URL of the variant playlist.
        :param name_key: Prefer to use this key as stream name, valid keys are:
                         name, pixels, bitrate.
        :param name_prefix: Add this prefix to the stream names.
        :param check_streams: Only allow streams that are accessible.
        :param force_restart: Start at the first segment even for a live stream
        :param name_fmt: A format string for the name, allowed format keys are
                         name, pixels, bitrate.
        """
        locale = session_.localization
        # Backwards compatibility with "namekey" and "nameprefix" params.
        name_key = request_params.pop("namekey", name_key)
        name_prefix = request_params.pop("nameprefix", name_prefix)
        audio_select = session_.options.get("hls-audio-select") or []

        res = session_.http.get(url, exception=IOError, **request_params)

        try:
            parser = hls_playlist.load(res.text, base_uri=res.url)
        except ValueError as err:
            raise IOError("Failed to parse playlist: {0}".format(err))

        streams = {}
        for playlist in filter(lambda p: not p.is_iframe, parser.playlists):
            names = dict(name=None, pixels=None, bitrate=None)
            audio_streams = []
            fallback_audio = []
            default_audio = []
            preferred_audio = []
            for media in playlist.media:
                if media.type == "VIDEO" and media.name:
                    names["name"] = media.name
                elif media.type == "AUDIO":
                    audio_streams.append(media)
            for media in audio_streams:
                # Media without a uri is not relevant as external audio
                if not media.uri:
                    continue

                if not fallback_audio and media.default:
                    fallback_audio = [media]

                # if the media is "audoselect" and it better matches the users preferences, use that
                # instead of default
                if not default_audio and (media.autoselect and locale.equivalent(language=media.language)):
                    default_audio = [media]

                # select the first audio stream that matches the users explict language selection
                if (('*' in audio_select or media.language in audio_select or media.name in audio_select) or
                        ((not preferred_audio or media.default) and locale.explicit and locale.equivalent(
                            language=media.language))):
                    preferred_audio.append(media)

            # final fallback on the first audio stream listed
            fallback_audio = fallback_audio or (len(audio_streams) and
                                                audio_streams[0].uri and [audio_streams[0]])

            if playlist.stream_info.resolution:
                width, height = playlist.stream_info.resolution
                names["pixels"] = "{0}p".format(height)

            if playlist.stream_info.bandwidth:
                bw = playlist.stream_info.bandwidth

                if bw >= 1000:
                    names["bitrate"] = "{0}k".format(int(bw / 1000.0))
                else:
                    names["bitrate"] = "{0}k".format(bw / 1000.0)

            if name_fmt:
                stream_name = name_fmt.format(**names)
            else:
                stream_name = (names.get(name_key) or names.get("name") or
                               names.get("pixels") or names.get("bitrate"))

            if not stream_name:
                continue
            if stream_name in streams:  # rename duplicate streams
                stream_name = "{0}_alt".format(stream_name)
                num_alts = len(list(filter(lambda n: n.startswith(stream_name), streams.keys())))

                # We shouldn't need more than 2 alt streams
                if num_alts >= 2:
                    continue
                elif num_alts > 0:
                    stream_name = "{0}{1}".format(stream_name, num_alts + 1)

            if check_streams:
                try:
                    session_.http.get(playlist.uri, **request_params)
                except KeyboardInterrupt:
                    raise
                except Exception:
                    continue

            external_audio = preferred_audio or default_audio or fallback_audio

            if external_audio and FFMPEGMuxer.is_usable(session_):
                external_audio_msg = ", ".join([
                    "(language={0}, name={1})".format(x.language, (x.name or "N/A"))
                    for x in external_audio
                ])
                log.debug("Using external audio tracks for stream {0} {1}", name_prefix + stream_name,
                          external_audio_msg)

                stream = KTCityMuxedHLSStream(session_,
                                        video=playlist.uri,
                                        audio=[x.uri for x in external_audio if x.uri],
                                        force_restart=force_restart,
                                        start_offset=start_offset,
                                        duration=duration,
                                        **request_params)
            else:
                stream = KTCityHLS(session_, playlist.uri, force_restart=force_restart,
                                   start_offset=start_offset, duration=duration, **request_params)
            streams[name_prefix + stream_name] = stream

        return streams

class KTCity(Plugin):
    """docstring for KTCity"""
    
    url_re = re.compile(r'(?x)https?://stream\d*\.kt\.city/')

    @classmethod
    def can_handle_url(cls, url):
        return cls.url_re.match(url) is not None

    def _get_streams(self):
        streams = KTCityHLS.parse_variant_playlist(self.session, self.url)
        return streams

__plugin__ = KTCity