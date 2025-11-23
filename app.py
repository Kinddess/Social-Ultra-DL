from flask import Flask, request, jsonify, send_file, Response
import yt_dlp
import os
import tempfile
import zipfile
import shutil
import requests
import time
import json
import threading
from collections import defaultdict

app = Flask(__name__, static_folder='.', static_url_path='')

# Global progress tracker (thread-safe)
progress_data = defaultdict(dict)
progress_lock = threading.Lock()

def update_progress(d):
    """yt-dlp progress hook"""
    with progress_lock:
        if d['status'] == 'downloading':
            progress_data[d['info_dict']['id']]['percent'] = d.get('downloaded_bytes', 0) / d.get('total_bytes', 1) * 100
            progress_data[d['info_dict']['id']]['status'] = 'downloading'
        elif d['status'] == 'finished':
            progress_data[d['info_dict']['id']]['status'] = 'finished'

@app.route('/')
def index():
    return app.send_static_file('index.html')

@app.route('/css/<path:path>')
def send_css(path):
    return app.send_static_file(f'css/{path}')

@app.route('/script.js')
def send_js():
    return app.send_static_file('script.js')

@app.route('/progress/<video_id>')
def get_progress(video_id):
    with progress_lock:
        return jsonify(progress_data.get(video_id, {'percent': 0, 'status': 'idle'}))

@app.route('/info', methods=['GET'])
def get_info():
    url = request.args.get('url', '').strip()
    if not url:
        return jsonify({'error': 'No URL provided'}), 400

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,  # Full extraction for info
        'cookiefile': 'cookies.txt' if os.path.exists('cookies.txt') else None,  # Rename to generic; populate with TikTok cookies
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
        },
        'sleep_interval': 1,  # Rate limit simulation
        'max_sleep_interval': 5,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
            if not info:
                raise ValueError('No info extracted')

            # Normalize for frontend (handle TikTok-specific fields)
            normalized = {
                'title': info.get('title', 'Unknown Title'),
                'author': info.get('uploader') or info.get('channel') or info.get('uploader_id', 'Unknown'),
                'thumbnail': info.get('thumbnail'),
                'duration': info.get('duration'),
                'entries': None,
                'type': info.get('_type', 'video'),
                'images': info.get('thumbnails') or []  # TikTok may have multiple thumbs
            }

            if info.get('_type') == 'playlist' and 'entries' in info:
                normalized['entries'] = []
                for entry in info['entries'][:10]:  # Limit to 10 for preview
                    if entry:
                        normalized['entries'].append({
                            'title': entry.get('title'),
                            'author': entry.get('uploader') or entry.get('channel'),
                            'thumbnail': entry.get('thumbnail'),
                            'duration': entry.get('duration'),
                            'url': entry.get('url') or entry.get('webpage_url'),
                            'type': entry.get('_type', 'video'),
                            'images': entry.get('thumbnails') or []
                        })

            app.logger.info(f"Extracted info for {url}: {normalized['title']}")
            return jsonify(normalized)

        except yt_dlp.utils.ExtractorError as e:
            app.logger.error(f"Extractor error for {url}: {str(e)}")
            return jsonify({'error': f'Extraction failed (likely TikTok protection): {str(e)}'}), 500
        except Exception as e:
            app.logger.error(f"Unexpected error for {url}: {str(e)}")
            return jsonify({'error': str(e)}), 500

@app.route('/download', methods=['GET'])
def download_file():
    url = request.args.get('url', '').strip()
    typ = request.args.get('type', 'video')
    video_id = request.args.get('video_id', 'default')

    if not url:
        return 'No URL provided', 400

    with tempfile.TemporaryDirectory() as tmpdir:
        ydl_opts = {
            'outtmpl': os.path.join(tmpdir, '%(title)s.%(ext)s'),
            'progress_hooks': [update_progress],
            'cookiefile': 'cookies.txt' if os.path.exists('cookies.txt') else None,
            'http_headers': {  # Same as info endpoint
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
                # ... (include all headers from get_info)
            },
            'sleep_interval': 1,
            'max_sleep_interval': 5,
        }

        download = True
        if typ in ['thumbnail', 'image']:
            download = False
            ydl_opts['skip_download'] = True
            if typ == 'thumbnail':
                ydl_opts['writethumbnail'] = True

        if typ == 'video':
            ydl_opts['format'] = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'  # TikTok-friendly
        elif typ == 'audio':
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(url, download=download)
                filename = ydl.prepare_filename(info)

                if typ == 'audio':
                    filename = f"{os.path.splitext(filename)[0]}.mp3"

                elif typ == 'thumbnail':
                    # Find thumbnail file
                    for ext in ['.webp', '.jpg', '.png']:
                        thumb_file = filename.rsplit('.', 1)[0] + ext
                        if os.path.exists(thumb_file):
                            filename = thumb_file
                            break
                    else:
                        return 'Thumbnail not found', 404

                elif typ == 'image':
                    # Handle TikTok images/stories
                    thumbs = info.get('thumbnails', [])
                    if not thumbs:
                        return 'No images found', 404
                    img_url = thumbs[-1]['url']  # Highest res
                    resp = requests.get(img_url, headers=ydl_opts['http_headers'], stream=True)
                    if resp.status_code != 200:
                        return 'Failed to fetch image', 500
                    filename = os.path.join(tmpdir, f"{info.get('id', 'image')}.jpg")
                    with open(filename, 'wb') as f:
                        shutil.copyfileobj(resp.raw, f)

                if os.path.exists(filename):
                    # Poll progress briefly for small files
                    time.sleep(0.5)
                    app.logger.info(f"Download complete: {filename}")
                    return send_file(filename, as_attachment=True, download_name=os.path.basename(filename))
                else:
                    return 'File not found', 404

            except Exception as e:
                app.logger.error(f"Download error for {url}: {str(e)}")
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
            time.sleep(1)  # Rate limit
            ydl_opts = {  # Same base opts as download_file
                'outtmpl': os.path.join(tmpdir, f'{info.get("title", "item")}_{idx+1}.%(ext)s') if 'info' in locals() else os.path.join(tmpdir, f'item_{idx+1}.%(ext)s'),
                'progress_hooks': [update_progress],
                'cookiefile': 'cookies.txt' if os.path.exists('cookies.txt') else None,
                # ... headers
            }
            # Set format/postprocessors based on typ (same as download_file)
            if typ == 'video':
                ydl_opts['format'] = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
            elif typ == 'audio':
                ydl_opts['format'] = 'bestaudio/best'
                ydl_opts['postprocessors'] = [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}]
            elif typ == 'image':
                # Direct fetch for images
                resp = requests.get(url, stream=True)  # Assume direct URL
                if resp.status_code == 200:
                    filename = os.path.join(tmpdir, f'image_{idx+1}.jpg')
                    with open(filename, 'wb') as f:
                        shutil.copyfileobj(resp.raw, f)
                    files.append(filename)
                continue

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                if typ == 'audio':
                    filename = f"{os.path.splitext(filename)[0]}.mp3"
                if os.path.exists(filename):
                    files.append(filename)

        if not files:
            return 'No files downloaded', 404

        if len(files) > 1:
            zip_path = os.path.join(tmpdir, 'album.zip')
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for file in files:
                    zipf.write(file, os.path.basename(file))
            return send_file(zip_path, as_attachment=True, download_name='album.zip')

        return send_file(files[0], as_attachment=True, download_name=os.path.basename(files[0]))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)