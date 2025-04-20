# Async File Manager

A FastAPI-based asynchronous file management system with a modern, responsive frontend for browsing, uploading, downloading, and previewing files.

## Features
- **Directory Navigation**: List and navigate through directories with breadcrumbs.
- **File Operations**: Upload, download, and stream files with range request support.
- **File Previews**: Preview images, videos, audio, text, PDFs, and more in a modal.
- **Responsive UI**: Tailwind CSS and HTMX for a dynamic, mobile-friendly interface with glassmorphism design.
- **MIME Type Detection**: Enhanced MIME type detection for various file formats.
- **Streaming Support**: Efficient file streaming for large files with partial content delivery.
- **Error Handling**: Robust logging and error responses for invalid paths or operations.

## Requirements
- Python 3.8+
- FastAPI
- aiofiles
- humanize
- pydantic
- uvicorn

## Installation
1. Clone the repository:
   ```bash
   git clone https://github.com/MohammadrezaAmani/simple-file-browser
   cd simple-file-browser
   ```
2. Install dependencies:
   ```bash
   pip install fastapi uvicorn aiofiles humanize pydantic
   ```
   or
   ```bash
   pip install uv
   ```
   ```bash
   uv sync
   ```
3. Run the application:
   ```bash
   uvicorn main:app --reload
   ```
   or
   ```bash
   uv uvicorn main:app --reload
   ```

## Usage
- Access the file manager at `http://localhost:8000`.
- Navigate directories, upload files, download files, or preview supported file types.
- API endpoints:
  - `GET /api/list/{path}`: List directory contents.
  - `GET /api/view/{path}`: Stream file content with range support.
  - `GET /api/download/{path}`: Download a file.
  - `POST /api/upload/{path}`: Upload a file to the specified directory.

## Frontend
- Built with **Tailwind CSS** for styling and **HTMX** for dynamic updates.
- Features a modal for file previews and a sortable file table for desktop users.
- Mobile-friendly card layout for smaller screens.

## Notes
- The application serves files from the root directory (`/`). Ensure proper permissions.
- Add authentication by uncommenting the `Depends(security)` in endpoints if needed.
- Large file uploads and downloads are handled efficiently with async I/O.

## License
MIT License
