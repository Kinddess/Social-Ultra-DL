# app.py
from flask import Flask, request, jsonify, send_file
import yt_dlp
import os
import tempfile
import zipfile
import shutil

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
                'type': info.get('media_type') or 'video',
                'images': info.get('thumbnails') if info.get('media_type') == 'image' else None
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
                        'type': entry.get('media_type') or 'video',
                        'images': entry.get('thumbnails') if entry.get('media_type') == 'image' else None
                    }
                    normalized['entries'].append(entry_norm)
            return jsonify(normalized)
        except Exception as e:
            return jsonify({'error': str(e)}), 500

@app.route('/download', methods=['GET'])
def download_file():
    url = request.args.get('url')
    typ = request.args.get('type', 'video')  # video, audio, thumbnail
    if not url:
        return 'No URL provided', 400
    with tempfile.TemporaryDirectory() as tmpdir:
        ydl_opts = {
            'outtmpl': os.path.join(tmpdir, '%(title)s.%(ext)s'),
            'quiet': True,
            'no_warnings': True,
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
        elif typ == 'thumbnail':
            ydl_opts['skip_download'] = True
            ydl_opts['writethumbnail'] = True
            ydl_opts['outtmpl'] = os.path.join(tmpdir, '%(title)s.%(ext)s')
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                if typ == 'audio':
                    filename = f"{os.path.splitext(filename)[0]}.mp3"
                elif typ == 'thumbnail':
                    # yt-dlp saves thumbnail as .jpg or similar
                    for file in os.listdir(tmpdir):
                        if file.endswith(('.jpg', '.webp', '.png')):
                            filename = os.path.join(tmpdir, file)
                            break
                    else:
                        return 'Thumbnail not found', 404
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
                ydl_opts['format'] = 'bestimage'
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