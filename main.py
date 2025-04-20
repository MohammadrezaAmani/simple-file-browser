from fastapi import FastAPI, HTTPException, Response, Depends, UploadFile, File
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel
import os
import mimetypes
import aiofiles
import humanize
from pathlib import Path
import asyncio
from typing import List
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Async File Manager")

# Mount static files for serving media
app.mount("/static", StaticFiles(directory="/"), name="static")

# Basic authentication
security = HTTPBasic()


class FileInfo(BaseModel):
    name: str
    path: str
    is_dir: bool
    size: str
    size_bytes: int
    mime_type: str | None

class DirectoryResponse(BaseModel):
    current_path: str
    files: List[FileInfo]
    parent_path: str | None
    breadcrumbs: List[dict]

def get_file_info(file_path: Path) -> FileInfo:
    """Get information about a file or directory with improved mime type detection."""
    is_dir = file_path.is_dir()
    size_bytes = file_path.stat().st_size if not is_dir else 0
    mime_type = mimetypes.guess_type(file_path)[0] if not is_dir else None
    # Fallback for common file types
    if not mime_type and not is_dir:
        extension = file_path.suffix.lower()
        mime_map = {
            '.txt': 'text/plain',
            '.log': 'text/plain',
            '.conf': 'text/plain',
            '.sh': 'text/x-shellscript',
            '.bashrc': 'text/plain',
            '.profile': 'text/plain',
            '.pdf': 'application/pdf',
            '.json': 'application/json',
            '.xml': 'application/xml',
            '.html': 'text/html',
            '.css': 'text/css',
            '.js': 'application/javascript',
            '.mp4': 'video/mp4',
            '.mkv': 'video/x-matroska',
            '.avi': 'video/x-msvideo',
            '.mov': 'video/quicktime',
            '.webm': 'video/webm',
            '.mp3': 'audio/mpeg',
            '.wav': 'audio/wav',
            '.ogg': 'audio/ogg'
        }
        mime_type = mime_map.get(extension, 'application/octet-stream')
    return FileInfo(
        name=file_path.name,
        path=str(file_path),
        is_dir=is_dir,
        size=humanize.naturalsize(size_bytes),
        size_bytes=size_bytes,
        mime_type=mime_type
    )

def get_breadcrumbs(full_path: Path) -> List[dict]:
    """Generate breadcrumbs for navigation."""
    parts = full_path.relative_to("/").parts if str(full_path) != "/" else []
    breadcrumbs = [{"name": "Root", "path": "/"}]
    current_path = "/"
    for part in parts:
        current_path = os.path.join(current_path, part)
        breadcrumbs.append({"name": part, "path": current_path})
    return breadcrumbs

async def async_iterate_file_chunks(file_path: str, start: int = 0, chunk_size: int = 1024 * 1024):
    """Asynchronously iterate over file chunks for streaming."""
    async with aiofiles.open(file_path, 'rb') as f:
        await f.seek(start)
        while True:
            chunk = await f.read(chunk_size)
            if not chunk:
                break
            yield chunk

def get_range_header(range_header: str, file_size: int) -> tuple[int, int, bool]:
    """Parse Range header for partial content streaming."""
    try:
        range_str = range_header.replace("bytes=", "")
        start, end = range_str.split("-")
        start = int(start)
        end = int(end) if end else file_size - 1
        if start >= file_size or end >= file_size or start > end:
            raise HTTPException(status_code=416, detail="Invalid range")
        return start, end, True
    except Exception:
        return 0, file_size - 1, False

@app.get("/api/list/{path:path}", response_model=DirectoryResponse)
async def list_directory(path: str = ""):
    """List contents of a directory."""
    try:
        full_path = Path("/") / path
        full_path = full_path.resolve()

        if not full_path.exists():
            raise HTTPException(status_code=404, detail="Path not found")
        if not full_path.is_dir():
            raise HTTPException(status_code=400, detail="Not a directory")

        files = []
        for item in await asyncio.to_thread(list, full_path.iterdir()):
            files.append(get_file_info(item))

        parent_path = str(full_path.parent) if full_path != Path("/") else None
        return DirectoryResponse(
            current_path=str(full_path),
            files=sorted(files, key=lambda x: (not x.is_dir, x.name.lower())),
            parent_path=parent_path,
            breadcrumbs=get_breadcrumbs(full_path)
        )
    except Exception as e:
        logger.error(f"Error listing directory {path}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/view/{path:path}")
async def view_file(path: str, range: str | None = None):
    """Stream file content with support for range requests."""
    try:
        full_path = Path("/") / path
        full_path = full_path.resolve()

        if not full_path.exists() or full_path.is_dir():
            raise HTTPException(status_code=404, detail="File not found")

        file_size = full_path.stat().st_size
        mime_type, _ = mimetypes.guess_type(full_path)
        mime_type = mime_type or "application/octet-stream"

        start, end, is_partial = get_range_header(range, file_size) if range else (0, file_size - 1, False)
        content_length = end - start + 1

        headers = {
            "Content-Type": mime_type,
            "Accept-Ranges": "bytes",
            "Content-Length": str(content_length),
        }
        status_code = 206 if is_partial else 200

        if is_partial:
            headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"

        return StreamingResponse(
            async_iterate_file_chunks(str(full_path), start),
            status_code=status_code,
            headers=headers
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error streaming file {path}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/download/{path:path}")
async def download_file(path: str):
    """Download a file."""
    try:
        full_path = Path("/") / path
        full_path = full_path.resolve()

        if not full_path.exists() or full_path.is_dir():
            raise HTTPException(status_code=404, detail="File not found")

        return FileResponse(
            path=str(full_path),
            filename=full_path.name,
            media_type=mimetypes.guess_type(full_path)[0] or "application/octet-stream"
        )
    except Exception as e:
        logger.error(f"Error downloading file {path}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/upload/{path:path}")
async def upload_file(path: str, file: UploadFile = File(...)):
    """Upload a file to the specified directory."""
    try:
        full_path = Path("/") / path
        full_path = full_path.resolve()

        if not full_path.exists() or not full_path.is_dir():
            raise HTTPException(status_code=400, detail="Invalid directory")

        file_path = full_path / file.filename
        async with aiofiles.open(file_path, 'wb') as f:
            while content := await file.read(1024 * 1024):  # 1MB chunks
                await f.write(content)

        return {"message": f"File {file.filename} uploaded successfully"}
    except Exception as e:
        logger.error(f"Error uploading file to {path}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/{path:path}")
async def serve_frontend(path: str = ""):
    """Serve the HTML frontend with support for direct URL navigation."""
    return Response(content=f"""
<!DOCTYPE html>
<html lang="en" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>File Manager</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://unpkg.com/htmx.org@1.9.6"></script>
    <style>
        /* Custom animations */
        @keyframes fadeIn {{
            from {{ opacity: 0; transform: translateY(10px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}
        .fade-in {{
            animation: fadeIn 0.3s ease-out;
        }}
        /* Glassmorphism effect */
        .glass {{
            background: rgba(255, 255, 255, 0.1);
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255, 255, 255, 0.2);
        }}
        /* Modal styles */
        .modal {{
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.7);
            z-index: 50;
            align-items: center;
            justify-content: center;
            transition: opacity 0.3s ease;
        }}
        .modal.open {{
            display: flex;
            opacity: 1;
        }}
        .modal-content {{
            max-width: 90%;
            max-height: 90%;
            overflow: auto;
            border-radius: 0.5rem;
            padding: 1rem;
            transform: scale(0.95);
            transition: transform 0.3s ease;
        }}
        .modal.open .modal-content {{
            transform: scale(1);
        }}
        video {{
            width: 100%;
            max-height: 70vh;
            object-fit: contain;
            background: black;
        }}
    </style>
</head>
<body class="bg-gray-900 text-gray-100 min-h-screen font-sans">
    <div class="container mx-auto p-4 sm:p-6 lg:p-8">
        <!-- Header -->
        <header class="glass rounded-lg p-4 mb-6">
            <h1 class="text-3xl font-bold text-cyan-400">File Manager</h1>
            <div id="breadcrumbs" class="flex flex-wrap gap-2 text-cyan-300 mt-2"></div>
        </header>

        <!-- Upload Form -->
        <div class="mb-6">
            <form hx-post="/api/upload/{path}" hx-target="#file-list" hx-swap="innerHTML" enctype="multipart/form-data" class="flex flex-col sm:flex-row gap-4">
                <input type="file" name="file" class="file:bg-gray-800 file:text-cyan-400 file:border-none file:rounded-lg file:px-4 file:py-2 bg-gray-800 rounded-lg text-gray-100">
                <button type="submit" class="bg-cyan-500 hover:bg-cyan-600 text-white px-6 py-2 rounded-lg transition-all duration-200 shadow-lg">Upload</button>
            </form>
        </div>

        <!-- File List -->
        <div id="file-list" hx-get="/api/list/{path}" hx-trigger="load" hx-swap="innerHTML" class="glass rounded-lg p-4"></div>

        <!-- Error -->
        <div id="error" class="text-red-400 mt-2"></div>
    </div>

    <!-- Modal for Preview -->
    <div id="preview-modal" class="modal">
        <div class="modal-content glass">
            <div class="flex justify-between items-center mb-4">
                <h2 id="modal-title" class="text-xl text-cyan-400"></h2>
                <button id="close-modal" class="text-gray-100 hover:text-cyan-400 text-2xl">×</button>
            </div>
            <div id="preview-content" class="max-h-[70vh] overflow-auto"></div>
        </div>
    </div>

    <script>
        function formatPath(path) {{
            // Remove leading slashes and encode the path, preserve empty path for root
            if (path === '/' || path === '') return '';
            return encodeURIComponent(path.replace(/^\\/+/, ''));
        }}

        // Modal handling
        const modal = document.getElementById('preview-modal');
        const modalContent = document.getElementById('preview-content');
        const modalTitle = document.getElementById('modal-title');
        const closeModal = document.getElementById('close-modal');

        function openModal(title, content) {{
            modalTitle.textContent = title;
            modalContent.innerHTML = content;
            modal.classList.add('open');
            console.log('Modal opened for:', title);
        }}

        function closeModalFunc() {{
            modal.classList.remove('open');
            modalContent.innerHTML = '';
            console.log('Modal closed');
        }}

        closeModal.onclick = closeModalFunc;
        modal.onclick = function(e) {{
            if (e.target === modal) closeModalFunc();
        }};

        // Handle dynamic event binding for HTMX-loaded content
        document.body.addEventListener('htmx:afterSwap', function() {{
            // Directory navigation
            document.querySelectorAll('.file-link').forEach(link => {{
                link.onclick = function(e) {{
                    e.preventDefault();
                    const path = this.getAttribute('data-path');
                    const encodedPath = formatPath(path);
                    const errorDiv = document.getElementById('error');
                    errorDiv.textContent = '';
                    console.log('Navigating to:', `/api/list/${{encodedPath}}`);
                    htmx.ajax('GET', `/api/list/${{encodedPath}}`, {{
                        target: '#file-list',
                        swap: 'innerHTML',
                        onError: (err) => {{
                            errorDiv.textContent = `Error loading directory: ${{err}}`;
                            console.error('HTMX Error:', err);
                        }}
                    }});
                    history.pushState({{}}, '', `/${{encodedPath}}`);
                }};
            }});

            // Breadcrumb navigation
            document.querySelectorAll('.breadcrumb-link').forEach(link => {{
                link.onclick = function(e) {{
                    e.preventDefault();
                    const path = this.getAttribute('data-path');
                    const encodedPath = formatPath(path);
                    const errorDiv = document.getElementById('error');
                    errorDiv.textContent = '';
                    console.log('Breadcrumb to:', `/api/list/${{encodedPath}}`);
                    htmx.ajax('GET', `/api/list/${{encodedPath}}`, {{
                        target: '#file-list',
                        swap: 'innerHTML',
                        onError: (err) => {{
                            errorDiv.textContent = `Error loading directory: ${{err}}`;
                            console.error('HTMX Error:', err);
                        }}
                    }});
                    history.pushState({{}}, '', `/${{encodedPath}}`);
                }};
            }});

            // File preview
            document.querySelectorAll('.view-link').forEach(link => {{
                link.onclick = function(e) {{
                    e.preventDefault();
                    const path = this.getAttribute('data-path');
                    const mime = this.getAttribute('data-mime') || 'application/octet-stream';
                    const fileName = this.getAttribute('data-name');
                    const encodedPath = formatPath(path);
                    console.log('Previewing:', path, 'MIME:', mime);

                    const fileUrl = `/api/view/${{encodedPath}}`;
                    if (mime.startsWith('video/')) {{
                        openModal(fileName, `
                            <video controls class="max-w-full rounded-lg" preload="metadata">
                                <source src="${{fileUrl}}" type="${{mime}}">
                                Your browser does not support the video tag.
                            </video>
                            <p id="video-error" class="text-red-400 mt-2 hidden">Failed to load video. <a href="/api/download/${{encodedPath}}" class="text-cyan-400 hover:underline">Download</a> instead.</p>
                        `);
                        const video = modalContent.querySelector('video');
                        video.onerror = () => {{
                            modalContent.querySelector('#video-error').classList.remove('hidden');
                            console.error('Video load error:', video.error);
                        }};
                        video.onloadeddata = () => {{
                            console.log('Video loaded successfully');
                        }};
                    }} else if (mime.startsWith('audio/')) {{
                        openModal(fileName, `
                            <audio controls class="w-full">
                                <source src="${{fileUrl}}" type="${{mime}}">
                                Your browser does not support the audio tag.
                            </audio>
                            <p id="audio-error" class="text-red-400 mt-2 hidden">Failed to load audio. <a href="/api/download/${{encodedPath}}" class="text-cyan-400 hover:underline">Download</a> instead.</p>
                        `);
                        const audio = modalContent.querySelector('audio');
                        audio.onerror = () => {{
                            modalContent.querySelector('#audio-error').classList.remove('hidden');
                            console.error('Audio load error:', audio.error);
                        }};
                        audio.onloadeddata = () => {{
                            console.log('Audio loaded successfully');
                        }};
                    }} else if (mime.startsWith('image/')) {{
                        openModal(fileName, `<img src="${{fileUrl}}" class="max-w-full h-auto rounded-lg" />`);
                    }} else if (mime.startsWith('text/') || mime === 'application/json' || mime === 'application/xml' || mime === 'text/html' || mime === 'text/css' || mime === 'application/javascript') {{
                        fetch(fileUrl)
                            .then(res => {{
                                if (!res.ok) throw new Error(`HTTP error! status: ${{res.status}}`);
                                return res.text();
                            }})
                            .then(text => {{
                                const escapedText = text.replace(/</g, '<').replace(/>/g, '>');
                                openModal(fileName, `<pre class="bg-gray-800 text-gray-100 p-4 rounded-lg overflow-auto max-h-[70vh]">${{escapedText.slice(0, 10000)}}</pre>`);
                            }})
                            .catch(err => {{
                                openModal(fileName, `<p class="text-red-400">Error loading preview: ${{err}}. <a href="/api/download/${{encodedPath}}" class="text-cyan-400 hover:underline">Download</a></p>`);
                                console.error('Fetch Error:', err);
                            }});
                    }} else if (mime === 'application/pdf') {{
                        openModal(fileName, `<iframe src="${{fileUrl}}#toolbar=0" class="w-full h-[70vh] rounded-lg"></iframe>`);
                    }} else {{
                        openModal(fileName, `<p class="text-gray-400">Preview not available for this file type. <a href="/api/download/${{encodedPath}}" class="text-cyan-400 hover:underline">Download</a></p>`);
                    }}
                }};
            }});

            // Sorting
            document.querySelectorAll('.sort-link').forEach(link => {{
                link.onclick = function(e) {{
                    e.preventDefault();
                    const sortBy = this.getAttribute('data-sort');
                    const tbody = document.querySelector('#file-table');
                    const cardContainer = document.querySelector('#card-container');
                    const rows = Array.from(tbody.querySelectorAll('tr'));
                    const cards = Array.from(cardContainer.querySelectorAll('.file-card'));
                    
                    const sortItems = (a, b) => {{
                        const aValue = a.querySelector(`td:nth-child(${{sortBy === 'name' ? 1 : sortBy === 'size' ? 2 : 3}})` || a.querySelector('.file-name')).textContent;
                        const bValue = b.querySelector(`td:nth-child(${{sortBy === 'name' ? 1 : sortBy === 'size' ? 2 : 3}})` || a.querySelector('.file-name')).textContent;
                        return aValue.localeCompare(bValue);
                    }};

                    rows.sort(sortItems);
                    cards.sort(sortItems);

                    tbody.innerHTML = '';
                    rows.forEach(row => tbody.appendChild(row));
                    cardContainer.innerHTML = '';
                    cards.forEach(card => cardContainer.appendChild(card));
                }};
            }});
        }});

        // Debug HTMX requests
        htmx.on('htmx:configRequest', (evt) => {{
            console.log('HTMX Request:', evt.detail.path);
        }});

        // Handle browser back/forward navigation
        window.onpopstate = function(event) {{
            const path = window.location.pathname.replace(/^\\/+/, '');
            console.log('Popstate navigating to:', `/api/list/${{path}}`);
            htmx.ajax('GET', `/api/list/${{path}}`, {{
                target: '#file-list',
                swap: 'innerHTML',
                onError: (err) => {{
                    document.getElementById('error').textContent = `Error loading directory: ${{err}}`;
                    console.error('Popstate Error:', err);
                }}
            }});
        }};

        // Render file list
        htmx.on('htmx:afterSwap', function(evt) {{
            const response = evt.detail.xhr.response;
            if (!response) return;

            try {{
                const data = JSON.parse(response);
                const fileList = document.querySelector('#file-list');
                const template = document.querySelector('#file-template').content.cloneNode(true);

                // Update current path
                template.querySelector('#current-path').textContent = data.current_path;

                // Render breadcrumbs
                const breadcrumbs = document.querySelector('#breadcrumbs');
                breadcrumbs.innerHTML = data.breadcrumbs.map(crumb => 
                    `<a href="/${{formatPath(crumb.path)}}" class="breadcrumb-link hover:text-cyan-400 transition-colors" data-path="${{crumb.path}}" hx-get="/api/list/${{formatPath(crumb.path)}}" hx-target="#file-list">${{crumb.name}}</a>`
                ).join(' <span class="text-gray-400">/</span> ');

                // Update parent link
                const parentLink = template.querySelector('#parent-link');
                if (data.parent_path) {{
                    parentLink.setAttribute('hx-get', `/api/list/${{formatPath(data.parent_path)}}`);
                }} else {{
                    parentLink.remove();
                }}

                // Render file list
                const tbody = template.querySelector('#file-table');
                const cardContainer = template.querySelector('#card-container');
                tbody.innerHTML = '';
                cardContainer.innerHTML = '';

                data.files.forEach(file => {{
                    // Table row for desktop
                    const row = document.createElement('tr');
                    row.className = 'hover:bg-gray-700 transition-colors';
                    row.innerHTML = `
                        <td class="border-b border-gray-700 px-4 py-2">
                            ${{file.is_dir 
                                ? `<a class="file-link text-cyan-300 hover:text-cyan-400 transition-colors" href="/${{formatPath(file.path)}}" data-path="${{file.path}}" hx-get="/api/list/${{formatPath(file.path)}}" hx-target="#file-list">${{file.name}}</a>`
                                : file.name}}
                        </td>
                        <td class="border-b border-gray-700 px-4 py-2">${{file.size}}</td>
                        <td class="border-b border-gray-700 px-4 py-2">${{file.mime_type || 'Directory'}}</td>
                        <td class="border-b border-gray-700 px-4 py-2">
                            ${{file.is_dir ? '' : `
                                <a class="text-cyan-300 hover:text-cyan-400 transition-colors" target="_blank" href="/api/view/${{formatPath(file.path)}}">Download</a>
                            `}}
                        </td>
                    `;
                    tbody.appendChild(row);

                    // Card for mobile
                    const card = document.createElement('div');
                    card.className = 'file-card glass rounded-lg p-4';
                    card.innerHTML = `
                        <div class="flex justify-between items-center">
                            <span class="file-name text-gray-100 truncate">
                                ${{file.is_dir 
                                    ? `<a class="file-link text-cyan-300 hover:text-cyan-400 transition-colors" href="/${{formatPath(file.path)}}" data-path="${{file.path}}" hx-get="/api/list/${{formatPath(file.path)}}" hx-target="#file-list">${{file.name}}</a>`
                                    : file.name}}
                            </span>
                            <span class="text-gray-400 text-sm">${{file.size}}</span>
                        </div>
                        <div class="text-gray-400 text-sm">${{file.mime_type || 'Directory'}}</div>
                        ${{file.is_dir ? '' : `
                            <div class="mt-2 flex gap-2">
                                <a class="text-cyan-300 hover:text-cyan-400 transition-colors" target="_blank" href="/api/view/${{formatPath(file.path)}}">Download</a>
                            </div>
                        `}}
                    `;
                    cardContainer.appendChild(card);
                }});

                fileList.innerHTML = '';
                fileList.appendChild(template);
            }} catch (e) {{
                document.getElementById('error').textContent = `Error rendering directory: ${{e.message}}`;
                console.error('Rendering Error:', e);
            }}
        }});
    </script>

    <template id="file-template">
        <div class="fade-in">
            <div class="mb-4">
                <h2 class="text-xl font-semibold text-cyan-400">Path: <span id="current-path"></span></h2>
                <a id="parent-link" class="text-cyan-300 hover:text-cyan-400 transition-colors" href="#" hx-target="#file-list">Parent Directory</a>
            </div>
            <div id="card-container" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 md:hidden"></div>
            <table class="w-full table-auto hidden md:table bg-gray-800 rounded-lg overflow-hidden">
                <thead class="bg-gray-700">
                    <tr>
                        <th class="px-4 py-2 text-left text-cyan-400">
                            <a href="#" class="sort-link" data-sort="name">Name</a>
                        </th>
                        <th class="px-4 py-2 text-left text-cyan-400">
                            <a href="#" class="sort-link" data-sort="size">Size</a>
                        </th>
                        <th class="px-4 py-2 text-left text-cyan-400">
                            <a href="#" class="sort-link" data-sort="type">Type</a>
                        </th>
                        <th class="px-4 py-2 text-left text-cyan-400">Actions</th>
                    </tr>
                </thead>
                <tbody id="file-table"></tbody>
            </table>
        </div>
    </template>
</body>
</html>
""", media_type="text/html")