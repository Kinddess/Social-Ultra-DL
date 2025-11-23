// script.js
// Plausible tracking function
function track(event, props = {}) {
    if (window.plausible) {
        window.plausible(event, { props });
    }
}

let currentInfo = null;
const statusEl = document.getElementById('status');
const progressEl = document.getElementById('progress');
const logEl = document.getElementById('log');

function log(msg) {
    const t = new Date().toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
    logEl.innerHTML += `<br>${t} • ${msg}`;
    logEl.scrollTop = logEl.scrollHeight;
}

function saveBlob(blob, filename) {
    const downloadUrl = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = downloadUrl;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(downloadUrl);
}

async function fetchWithProgress(url, mimeType = null) {
    return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open('GET', url, true);
        xhr.responseType = 'blob';
        xhr.onprogress = (e) => {
            if (e.lengthComputable) {
                progressEl.value = (e.loaded / e.total) * 100;
            }
        };
        xhr.onload = () => {
            if (xhr.status === 200) {
                let blob = xhr.response;
                if (mimeType && blob.type !== mimeType) {
                    blob = new Blob([blob], { type: mimeType });
                }
                resolve(blob);
            } else {
                reject(new Error(`HTTP error! status: ${xhr.status}`));
            }
        };
        xhr.onerror = () => reject(new Error('Fetch error'));
        xhr.send();
    });
}

async function preview() {
    const url = document.getElementById('url').value.trim();
    if (!url) return alert("Paste a valid link");
    statusEl.textContent = "Analyzing...";
    track('Preview');
    try {
        const response = await fetch(`/info?url=${encodeURIComponent(url)}`);
        if (!response.ok) throw new Error(await response.text());
        const info = await response.json();
        currentInfo = info;
        const container = document.getElementById('preview-container');
        const title = (info.title || 'Media').slice(0,45) + ((info.title || '').length > 45 ? '...' : '');
        const uploader = info.author || 'Unknown';
        let thumbnail = info.thumbnail || '';
        if (!thumbnail && info.entries?.length) {
            thumbnail = info.entries[0].thumbnail || '';
        }
        const duration = info.duration ? ' • ' + Math.floor(info.duration/60) + ':' + String(info.duration%60).padStart(2,'0') : '';
        const entries = info.entries?.length ? ' • Album with ' + info.entries.length + ' items' : '';
        container.innerHTML = `
            <img src="${thumbnail}" alt="Media thumbnail" onerror="this.style.display='none'">
            <div class="preview-meta">
                <div style="font-weight:bold;">${title}</div>
                <div style="opacity:0.8;">
                    by ${uploader}${duration}${entries}
                </div>
            </div>
        `;
        statusEl.textContent = "Ready to download ✓";
        log("Preview loaded");
    } catch (e) {
        alert("Failed: " + e.message);
        statusEl.textContent = "Error";
        log("✗ Preview failed: " + e.message);
    }
}

async function downloadMedia(url, typ) {
    const mediaUrl = `/download?url=${encodeURIComponent(url)}&type=${typ}`;
    const ext = typ === 'audio' ? 'mp3' : typ === 'video' ? 'mp4' : 'jpg';
    const mimeType = typ === 'audio' ? 'audio/mp3' : typ === 'video' ? 'video/mp4' : 'image/jpeg';
    const blob = await fetchWithProgress(mediaUrl, mimeType);
    const filename = `media.${ext}`; // Better to get from headers, but for simplicity
    saveBlob(blob, filename);
    return filename;
}

async function download(isVideo) {
    if (!currentInfo) return alert("Preview first");
    progressEl.value = 0;
    const typ = isVideo ? 'video' : 'audio';
    try {
        if (currentInfo.entries?.length) {
            for (let i = 0; i < currentInfo.entries.length; i++) {
                const entry = currentInfo.entries[i];
                statusEl.textContent = `Downloading item ${i+1}/${currentInfo.entries.length}...`;
                const filename = await downloadMedia(entry.url || document.getElementById('url').value, typ);
                log(`✓ Saved: ${filename} (${i+1})`);
            }
        } else {
            statusEl.textContent = "Downloading...";
            const filename = await downloadMedia(document.getElementById('url').value, typ);
            log(`✓ Saved: ${filename}`);
        }
        statusEl.textContent = "Download complete! ✅";
        track(isVideo ? 'Download Video' : 'Download Audio');
    } catch (e) {
        alert("Download failed: " + e.message);
        log("✗ Download failed: " + e.message);
        statusEl.textContent = "Error";
    } finally {
        progressEl.value = 0;
    }
}

async function downloadImage() {
    if (!currentInfo) return alert("Preview first");
    progressEl.value = 0;
    try {
        let images = [];
        if (currentInfo.type?.includes('image') && currentInfo.images?.length) {
            images = currentInfo.images.map(img => img.url || img);
        } else if (currentInfo.entries?.length) {
            currentInfo.entries.forEach(entry => {
                if (entry.type?.includes('image') && entry.url) {
                    images.push(entry.url);
                } else if (entry.thumbnail) {
                    images.push(entry.thumbnail);
                }
            });
        } else if (currentInfo.thumbnail) {
            images = [currentInfo.thumbnail];
        }
        if (!images.length) return alert("No image available");

        for (let i = 0; i < images.length; i++) {
            const imageUrl = images[i];
            if (imageUrl.startsWith('http')) {
                // Direct download for thumbnails
                statusEl.textContent = images.length > 1 ? `Downloading image ${i+1}/${images.length}...` : "Downloading image...";
                const blob = await fetchWithProgress(imageUrl, 'image/jpeg');
                const baseName = (currentInfo.title || 'image').replace(/[^a-z0-9]/gi, '_');
                const filename = images.length > 1 ? `${baseName}_${i+1}.jpg` : `${baseName}.jpg`;
                saveBlob(blob, filename);
                log(`✓ Saved: ${filename}`);
            } else {
                // Use server for thumbnail if needed
                const mediaUrl = `/download?url=${encodeURIComponent(document.getElementById('url').value)}&type=thumbnail`;
                const blob = await fetchWithProgress(mediaUrl, 'image/jpeg');
                const baseName = (currentInfo.title || 'image').replace(/[^a-z0-9]/gi, '_');
                const filename = `${baseName}.jpg`;
                saveBlob(blob, filename);
                log(`✓ Saved: ${filename}`);
            }
        }
        statusEl.textContent = "Download complete! ✅";
        track('Download Image');
    } catch (e) {
        alert("Image download failed: " + e.message);
        log("✗ Image download failed: " + e.message);
        statusEl.textContent = "Error";
    } finally {
        progressEl.value = 0;
    }
}

function openDonateModal() {
    document.getElementById('donateModal').classList.add('active');
    track('Donate Modal Opened');
}

function closeModal() {
    document.getElementById('donateModal').classList.remove('active');
}

function copyAddress(addr, coin) {
    navigator.clipboard.writeText(addr);
    const btn = event.target;
    btn.textContent = "Copied!";
    btn.classList.add('copied');
    track('Donation Address Copied', { coin });
    setTimeout(() => {
        btn.textContent = `Copy ${coin} Address`;
        btn.classList.remove('copied');
    }, 2000);
}

// Close modal on backdrop click
document.getElementById('donateModal').addEventListener('click', (e) => {
    if (e.target === document.getElementById('donateModal')) closeModal();
});

window.onload = async () => {
    track('Page View');
    try {
        const clip = await navigator.clipboard.readText();
        if (clip.startsWith('http')) document.getElementById('url').value = clip;
    } catch(e) {}
    log("Social Ultra DL ready • Thank you for using!");
};