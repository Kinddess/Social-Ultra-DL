# app.py
from flask import Flask, request, jsonify, send_file
import yt_dlp
import os
import tempfile
import zipfile
import shutil
import requests

app = Flask(__name__, static_folder='.')

@app.route('/')
def index():
    return app.send_static_file('index.html')

@app.route('/css/<path:path>')
def send_css(path):
    return app.send_static_file(f'css/{path}')

@app.route('/script.js')
def send_js():
    return app.send_static_file('script.js')

@app.route('/info', methods=['GET'])
def get_info():
    url = request.args.get('url')
    if not url:
        return jsonify({'error': 'No URL provided'}), 400
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Referer': 'https://www.tiktok.com/',
        },
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
            # Normalize info
            normalized = {
                'title': info.get('title'),
                'author': info.get('uploader') or info.get('channel') or info.get('uploader_id'),
                'thumbnail': info.get('thumbnail'),
                'duration': info.get('duration'),
                'entries': None,
                'type': 'image' if 'images' in info else 'video',
                'images': [img['url'] for img in info.get('images', [])] if 'images' in info else None
            }
            if 'entries' in info and info['entries']:
                normalized['entries'] = []
                for entry in info['entries']:
                    entry_norm = {
                        'title': entry.get('title'),
                        'author': entry.get('uploader') or entry.get('channel') or entry.get('uploader_id'),
                        'thumbnail': entry.get('thumbnail'),
                        'duration': entry.get('duration'),
                        'url': entry.get('url') or entry.get('webpage_url'),
                        'type': 'image' if 'images' in entry else 'video',
                        'images': [img['url'] for img in entry.get('images', [])] if 'images' in entry else None
                    }
                    normalized['entries'].append(entry_norm)
            return jsonify(normalized)
        except Exception as e:
            return jsonify({'error': str(e)}), 500

@app.route('/download', methods=['GET'])
def download_file():
    url = request.args.get('url')
    typ = request.args.get('type', 'video')  # video, audio, thumbnail, image
    if not url:
        return 'No URL provided', 400
    with tempfile.TemporaryDirectory() as tmpdir:
        ydl_opts = {
            'outtmpl': os.path.join(tmpdir, '%(title)s.%(ext)s'),
            'quiet': True,
            'no_warnings': True,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Referer': 'https://www.tiktok.com/',
            },
        }
        if typ == 'video':
            ydl_opts['format'] = 'bestvideo+bestaudio/best'
        elif typ == 'audio':
            ydl_opts['format'] = 'bestaudio'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
        elif typ in ['thumbnail', 'image']:
            ydl_opts['skip_download'] = True
            if typ == 'thumbnail':
                ydl_opts['writethumbnail'] = True
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(url, download=typ not in ['thumbnail', 'image'])
                filename = ydl.prepare_filename(info)
                if typ == 'audio':
                    filename = f"{os.path.splitext(filename)[0]}.mp3"
                elif typ == 'thumbnail':
                    for file in os.listdir(tmpdir):
                        if file.endswith(('.jpg', '.webp', '.png')):
                            filename = os.path.join(tmpdir, file)
                            break
                    else:
                        return 'Thumbnail not found', 404
                elif typ == 'image':
                    images = info.get('images', [])
                    if not images:
                        return 'No images found', 404
                    if len(images) == 1:
                        img_url = images[0]['url']
                        response = requests.get(img_url, stream=True)
                        if response.status_code != 200:
                            return 'Failed to fetch image', 500
                        filename = os.path.join(tmpdir, f"{info.get('id', 'image')}.jpg")
                        with open(filename, 'wb') as f:
                            shutil.copyfileobj(response.raw, f)
                    else:
                        zip_path = os.path.join(tmpdir, 'images.zip')
                        with zipfile.ZipFile(zip_path, 'w') as zipf:
                            for i, img in enumerate(images):
                                img_url = img['url']
                                resp = requests.get(img_url, stream=True)
                                if resp.status_code == 200:
                                    img_filename = f"image_{i+1}.jpg"
                                    img_path = os.path.join(tmpdir, img_filename)
                                    with open(img_path, 'wb') as f:
                                        shutil.copyfileobj(resp.raw, f)
                                    zipf.write(img_path, img_filename)
                        return send_file(zip_path, as_attachment=True, download_name='images.zip')
                if os.path.exists(filename):
                    return send_file(filename, as_attachment=True, download_name=os.path.basename(filename))
                else:
                    return 'File not found', 404
            except Exception as e:
                return str(e), 500

@app.route('/download_album', methods=['GET'])
def download_album():
    urls = request.args.getlist('urls')
    typ = request.args.get('type', 'video')
    if not urls:
        return 'No URLs provided', 400
    with tempfile.TemporaryDirectory() as tmpdir:
        files = []
        for idx, url in enumerate(urls):
            ydl_opts = {
                'outtmpl': os.path.join(tmpdir, f'item_{idx+1}.%(ext)s'),
                'quiet': True,
                'no_warnings': True,
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.5',
                    'Referer': 'https://www.tiktok.com/',
                },
            }
            if typ == 'video':
                ydl_opts['format'] = 'bestvideo+bestaudio/best'
            elif typ == 'audio':
                ydl_opts['format'] = 'bestaudio'
                ydl_opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }]
            elif typ == 'image':
                # For image, assume url is direct image url
                response = requests.get(url, stream=True)
                if response.status_code == 200:
                    filename = os.path.join(tmpdir, f'image_{idx+1}.jpg')
                    with open(filename, 'wb') as f:
                        shutil.copyfileobj(response.raw, f)
                    files.append(filename)
                continue
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                if typ == 'audio':
                    filename = f"{os.path.splitext(filename)[0]}.mp3"
                if os.path.exists(filename):
                    files.append(filename)
        if len(files) > 1:
            zip_path = os.path.join(tmpdir, 'album.zip')
            with zipfile.ZipFile(zip_path, 'w') as zipf:
                for file in files:
                    zipf.write(file, os.path.basename(file))
            return send_file(zip_path, as_attachment=True, download_name='album.zip')
        elif files:
            return send_file(files[0], as_attachment=True, download_name=os.path.basename(files[0]))
        else:
            return 'No files downloaded', 404

if __name__ == '__main__':
    app.run(debug=True)