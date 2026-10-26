import base64

from pyDes import ECB, PAD_PKCS5, des

from . import client as jiosaavn


def format_song(data, lyrics):
    try:
        data['media_url'] = decrypt_url(data['encrypted_media_url'])
        if data['320kbps'] != "true":
            data['media_url'] = data['media_url'].replace(
                "_320.mp4", "_160.mp4")
        data['media_preview_url'] = data['media_url'].replace(
            "_320.mp4", "_96_p.mp4").replace("_160.mp4", "_96_p.mp4").replace("//aac.", "//preview.")
    except (KeyError, TypeError):
        url = data.get('media_preview_url', '')
        url = url.replace("preview", "aac")
        if data.get('320kbps') == "true":
            url = url.replace("_96_p.mp4", "_320.mp4")
        else:
            url = url.replace("_96_p.mp4", "_160.mp4")
        data['media_url'] = url

    # Ensure singers and primary_artists fall back to each other if one is empty
    if not data.get('singers') and data.get('primary_artists'):
        data['singers'] = data.get('primary_artists', '')
    elif not data.get('primary_artists') and data.get('singers'):
        data['primary_artists'] = data.get('singers', '')

    data['song'] = format(data.get('song', ''))
    data['music'] = format(data.get('music', ''))
    data['singers'] = format(data.get('singers', ''))
    data['starring'] = format(data.get('starring', ''))
    data['album'] = format(data.get('album', ''))
    data["primary_artists"] = format(data.get("primary_artists", ''))
    if 'image' in data and data['image']:
        data['image'] = data['image'].replace("150x150", "500x500")

    if lyrics:
        if data.get('has_lyrics') == 'true':
            data['lyrics'] = jiosaavn.get_lyrics(data['id'])
        else:
            data['lyrics'] = None

    try:
        data['copyright_text'] = data['copyright_text'].replace("&copy;", "©")
    except KeyError:
        pass
    return data


def format_album(data, lyrics):
    if 'image' in data and data['image']:
        data['image'] = data['image'].replace("150x150", "500x500")
    data['name'] = format(data.get('name', ''))
    data['primary_artists'] = format(data.get('primary_artists', ''))
    data['title'] = format(data.get('title', ''))
    for song in data.get('songs', []):
        song = format_song(song, lyrics)
    return data


def format_playlist(data, lyrics):
    data['firstname'] = format(data.get('firstname', ''))
    data['listname'] = format(data.get('listname', ''))
    for song in data.get('songs', []):
        song = format_song(song, lyrics)
    return data


def format(string):
    if not string:
        return ""
    return str(string).encode().decode().replace("&quot;", "'").replace("&amp;", "&").replace("&#039;", "'")


def decrypt_url(url):
    des_cipher = des(b"38346591", ECB, b"\0\0\0\0\0\0\0\0",
                     pad=None, padmode=PAD_PKCS5)
    enc_url = base64.b64decode(url.strip())
    dec_url = des_cipher.decrypt(enc_url, padmode=PAD_PKCS5).decode('utf-8')
    dec_url = dec_url.replace("_96.mp4", "_320.mp4")
    return dec_url
