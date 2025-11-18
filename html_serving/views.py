from django.http import HttpResponse, FileResponse
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
import os
import shutil
import zipfile
from bs4 import BeautifulSoup
from urllib.parse import unquote, quote
from django.shortcuts import render, redirect
from django.contrib import messages
from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required

@extend_schema(
    tags=["Notion"],
    summary="Serve Notion HTML",
    description="Serves Notion HTML files. If no 'file' query parameter is provided, it serves the main 'JBIG 교안' file.",
    parameters=[
        {
            'name': 'file',
            'in': 'query',
            'description': 'The name of the HTML file to serve.',
            'schema': {'type': 'string'}
        }
    ],
    responses={200: {"description": "HTML content of the notion page.", "content": {"text/html": {"schema": {"type": "string"}}}}}
)
@api_view(['GET'])
def notion_view(request):
    notion_dir = os.path.join(settings.MEDIA_ROOT, settings.CONTENT_NOTION_SUBDIR)
    requested_file = request.query_params.get('file', None)

    file_to_serve = None

    if requested_file:
        # Ensure the requested file is safe to access
        if '..' in requested_file or requested_file.startswith('/'):
            return Response({"detail": "Invalid file path."}, status=status.HTTP_400_BAD_REQUEST)
        potential_path = os.path.join(notion_dir, requested_file)
        if os.path.exists(potential_path) and potential_path.endswith('.html'):
            file_to_serve = potential_path
    else:
        # Default behavior: find the main file
        try:
            for f in os.listdir(notion_dir):
                if f.startswith('JBIG 교안') and f.endswith('.html'):
                    file_to_serve = os.path.join(notion_dir, f)
                    break
        except FileNotFoundError:
            return Response({"detail": "Notion directory not found."}, status=status.HTTP_404_NOT_FOUND)

    if not file_to_serve:
        return Response({"detail": "Notion file not found."}, status=status.HTTP_404_NOT_FOUND)

    try:
        with open(file_to_serve, 'r', encoding='utf-8') as file:
            content = file.read()
    except FileNotFoundError:
        return Response({"detail": "Notion file not found."}, status=status.HTTP_404_NOT_FOUND)

    soup = BeautifulSoup(content, 'html.parser')

    # Update image sources
    for img in soup.find_all('img'):
        src = img.get('src')
        if src and not src.startswith(('http://', 'https://', '/')):
            decoded_src = unquote(src)
            img['src'] = settings.MEDIA_URL.rstrip('/') + '/' + settings.CONTENT_NOTION_SUBDIR.strip('/') + '/' + quote(decoded_src)

    # Update anchor hrefs pointing to images and other assets
    for a in soup.find_all('a', href=True):
        href = a.get('href')
        if href and not href.startswith(('http://', 'https://', '#', '/')):
            if any(href.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.svg', '.webp']):
                decoded_href = unquote(href)
                a['href'] = settings.MEDIA_URL.rstrip('/') + '/' + settings.CONTENT_NOTION_SUBDIR.strip('/') + '/' + quote(decoded_href)
            elif href.lower().endswith('.html'):
                decoded_href = unquote(href)
                a['href'] = '/api/html/notion/?file=' + quote(decoded_href)

    return HttpResponse(str(soup), content_type='text/html; charset=utf-8')

@extend_schema(
    tags=["Award"],
    summary="Serve Award HTML",
    description="Serves the Award HTML file.",
    responses={200: {"description": "HTML content of the award page.", "content": {"text/html": {"schema": {"type": "string"}}}}}
)
@api_view(['GET'])
def award_view(request):
    file_path = os.path.join(
        settings.MEDIA_ROOT,
        settings.CONTENT_AWARDS_SUBDIR,
        settings.CONTENT_AWARD_HTML_FILENAME,
    )
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Awards HTML 내 링크 보정: 내부 .html은 노션 라우트로, 에셋은 미디어로
        try:
            soup = BeautifulSoup(content, 'html.parser')

            # 이미지/미디어 src가 상대경로이면 MEDIA_URL로 보정
            for tag in soup.find_all(src=True):
                src = tag.get('src')
                if src and not src.startswith(('http://', 'https://', '/', 'data:')):
                    decoded_src = unquote(src)
                    tag['src'] = (
                        settings.MEDIA_URL.rstrip('/')
                        + '/'
                        + settings.CONTENT_AWARDS_SUBDIR.strip('/')
                        + '/'
                        + quote(decoded_src)
                    )

            # 앵커: 내부 .html은 /api/html/notion/?file=... 로 연결
            for a in soup.find_all('a', href=True):
                href = a.get('href')
                if not href or href.startswith(('http://', 'https://', '#', '/')):
                    continue
                if href.lower().endswith('.html'):
                    decoded_href = unquote(href)
                    a['href'] = '/api/html/notion/?file=' + quote(decoded_href)

            content = str(soup)
        except Exception:
            # 파싱 실패 시 원본 그대로 반환
            pass

        return HttpResponse(content, content_type='text/html; charset=utf-8')
    return Response({"detail": "Award file not found."}, status=status.HTTP_404_NOT_FOUND)


@extend_schema(
    tags=["Award"],
    summary="Upload Award HTML",
    description="Upload a new HTML file for the award page. This will overwrite the existing file.",
    request={
        'multipart/form-data': {
            'type': 'object',
            'properties': {
                'file': {
                    'type': 'string',
                    'format': 'binary'
                }
            }
        }
    }
)
@api_view(['POST'])
def award_upload_view(request):
    if 'file' not in request.FILES:
        return Response({'error': 'No file provided'}, status=status.HTTP_400_BAD_REQUEST)

    file = request.FILES['file']
    
    if not file.name.endswith('.html'):
        return Response({'error': 'Invalid file type. Please upload an HTML file.'}, status=status.HTTP_400_BAD_REQUEST)

    upload_dir = os.path.join(settings.MEDIA_ROOT, settings.CONTENT_AWARDS_SUBDIR)
    os.makedirs(upload_dir, exist_ok=True)
        
    # For simplicity, we'll overwrite the existing file with a fixed name.
    file_path = os.path.join(upload_dir, settings.CONTENT_AWARD_HTML_FILENAME)
    
    with open(file_path, 'wb+') as destination:
        for chunk in file.chunks():
            destination.write(chunk)
            
    return Response({'message': 'Award HTML file uploaded successfully'}, status=status.HTTP_201_CREATED)


@extend_schema(
    tags=["Notion"],
    summary="Upload Notion Content (ZIP)",
    description="Upload a ZIP file containing the notion content. This will replace the entire content of the notion directory.",
    request={
        'multipart/form-data': {
            'type': 'object',
            'properties': {
                'file': {
                    'type': 'string',
                    'format': 'binary'
                }
            }
        }
    }
)
@api_view(['POST'])
def notion_upload_view(request):
    if 'file' not in request.FILES:
        return Response({'error': 'No file provided'}, status=status.HTTP_400_BAD_REQUEST)

    file = request.FILES['file']

    if not file.name.endswith('.zip'):
        return Response({'error': 'Invalid file type. Please upload a ZIP file.'}, status=status.HTTP_400_BAD_REQUEST)

    upload_dir = os.path.join(settings.MEDIA_ROOT, settings.CONTENT_NOTION_SUBDIR)

    # Clear the directory first
    if os.path.exists(upload_dir):
        shutil.rmtree(upload_dir)
    os.makedirs(upload_dir, exist_ok=True)

    zip_path = os.path.join(upload_dir, file.name)
    with open(zip_path, 'wb+') as destination:
        for chunk in file.chunks():
            destination.write(chunk)

    # Unzip the file
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(upload_dir)
    except zipfile.BadZipFile:
        return Response({'error': 'Invalid ZIP file.'}, status=status.HTTP_400_BAD_REQUEST)
    finally:
        # Clean up the uploaded zip file
        os.remove(zip_path)

    return Response({'message': 'Notion content uploaded and extracted successfully'}, status=status.HTTP_201_CREATED)

@extend_schema(
    tags=["Banner"],
    summary="Serve Banner Image",
    description="Serves the banner.jpg image from the media/banner/ directory.",
    responses={
        200: {"description": "The banner image.", "content": {"image/jpeg": {"schema": {"type": "string", "format": "binary"}}}},
        404: {"description": "Image not found."}
    }
)
@api_view(['GET'])
def banner_view(request):
    file_path = os.path.join(settings.MEDIA_ROOT, settings.CONTENT_BANNER_SUBPATH)

    if os.path.exists(file_path):
        return FileResponse(open(file_path, 'rb'))
    else:
        return Response({"detail": "Image not found."}, status=status.HTTP_404_NOT_FOUND)

@staff_member_required
def notion_admin_upload_view(request):
    upload_dir = os.path.join(settings.MEDIA_ROOT, 'notion')

    if request.method == 'POST':
        if 'zip_file' not in request.FILES:
            messages.error(request, "No file provided.")
            return redirect('notion-admin-upload')

        zip_file = request.FILES['zip_file']

        if not zip_file.name.endswith('.zip'):
            messages.error(request, "Invalid file type. Please upload a ZIP file.")
            return redirect('notion-admin-upload')

        # Clear the directory first
        if os.path.exists(upload_dir):
            shutil.rmtree(upload_dir)
        os.makedirs(upload_dir)

        zip_path = os.path.join(upload_dir, zip_file.name)
        with open(zip_path, 'wb+') as destination:
            for chunk in zip_file.chunks():
                destination.write(chunk)

        # Unzip the file
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(upload_dir)
            messages.success(request, 'Notion content uploaded and extracted successfully.')
        except zipfile.BadZipFile:
            messages.error(request, 'Invalid ZIP file.')
        except Exception as e:
            messages.error(request, f'An error occurred during extraction: {e}')
        finally:
            # Clean up the uploaded zip file
            if os.path.exists(zip_path):
                os.remove(zip_path)

        return redirect('notion-admin-upload')

    return render(request, 'html_serving/notion_admin_upload.html', {'notion_dir': upload_dir})
