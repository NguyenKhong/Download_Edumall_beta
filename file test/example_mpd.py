from dash_tools import mpdparser
from mpegdash.parser import MPEGDASHParser
from var_dump import var_dump

data = open('manifest.mpd').read()

mpd = MPEGDASHParser.parse('manifest.mpd')

print mpd.base_urls



def urlForMaxBandwith(adaptation_set):
    bandwidth = []
    for rep in adapt_set.representations:
        bandwidth.append(int(rep.bandwidth))
    
    urls = []
    seg = adapt_set.representations[bandwidth.index(max(bandwidth))].segment_lists[0]
    if seg.initializations[0].source_url:
        urls.append(seg.initializations[0].source_url)
    for seg_url in seg.segment_urls:
        urls.append(seg_url.media)
    return urls

def extractInfoMedia(url):
    headers = { 'Origin': 'https://sdk.uiza.io',
                'Referer': 'https://sdk.uiza.io/v3/index.html'
            }
    r = Request(url, headers = headers)
    infoVideo = {}
    infoAudio = {}
    mpd = MPEGDASHParser.parse(r.content)
    period = mpd.periods[0]

    for adapt_set in period.adaptation_sets:
        if 'video' in adapt_set.mime_type:
            infoVideo['url'] = urlForMaxBandwith(adapt_set)
        if 'audio' in adapt_set.mime_type:
            infoAudio['url'] = urlForMaxBandwith(adapt_set)
    return {'video' : infoVideo, 'audio' : infoAudio}

var_dump(infoMedia)



