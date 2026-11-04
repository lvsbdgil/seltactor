import base64
import io
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend import app as api
from backend import pipeline


def png():
    out = io.BytesIO()
    Image.new('RGB', (100, 80), '#6d8a4f').save(out, format='PNG')
    return out.getvalue()


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    api.jobs.clear()


def test_no_key_and_health():
    with TestClient(api.app) as client:
        assert client.get('/api/health').json()['configured'] is False
        res = client.post('/api/analyses', data={'field': 'Поле', 'crop': 'Пшеница', 'date': '2026-05-18'},
                          files={'files': ('test.png', png(), 'image/png')})
        assert res.status_code == 503
        assert 'OPENAI_API_KEY' in res.json()['detail']


def test_upload_process_poll_and_cleanup(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key-not-real')
    observed = []
    def analyze(images, **context):
        assert images[0].jpeg.startswith(b'\xff\xd8')
        observed.append(context)
        return {'summary': 'Наблюдение', 'observations': [], 'limitations': [], 'mode': 'openai'}
    with patch.object(api, 'analyze_images', side_effect=analyze), patch.object(api.shutil, 'rmtree', wraps=api.shutil.rmtree) as cleanup:
        with TestClient(api.app) as client:
            res = client.post('/api/analyses', data={'field': 'Поле №12', 'crop': 'Пшеница', 'date': '2026-05-18'},
                              files={'files': ('../../test.png', png(), 'image/png')})
            assert res.status_code == 202
            job = client.get('/api/analyses/' + res.json()['id']).json()
            assert job['status'] == 'completed'
            assert job['progress'] == 100
            assert job['report']['files_processed'] == 1
            assert observed[0]['field'] == 'Поле №12'
            directory = cleanup.call_args.args[0]
            assert not directory.exists()


def test_invalid_images_and_unknown_job(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key-not-real')
    with TestClient(api.app) as client:
        data = {'field': 'Поле', 'crop': 'Пшеница', 'date': '2026-05-18'}
        assert client.post('/api/analyses', data=data, files={'files': ('bad.jpg', b'not-an-image', 'image/jpeg')}).status_code == 415
        assert client.post('/api/analyses', data=data, files={'files': ('bad.png', b'', 'image/png')}).status_code == 422
        assert client.post('/api/analyses', data=data, files={'files': ('x.txt', b'x', 'text/plain')}).status_code == 415
        assert client.get('/api/analyses/unknown').status_code == 404


def test_failed_job_is_safe(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key-not-real')
    with patch.object(api, 'analyze_images', side_effect=RuntimeError('secret-key-never-expose')):
        with TestClient(api.app) as client:
            res = client.post('/api/analyses', data={'field': 'P', 'crop': 'C', 'date': '2026-05-18'}, files={'files': ('x.png', png())})
            job = client.get('/api/analyses/' + res.json()['id']).json()
            assert job['status'] == 'failed'
            assert 'secret' not in json.dumps(job)


def test_real_video_frames_and_invalid_video(tmp_path):
    video = tmp_path / 'tiny.mp4'
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i',
                    'color=c=green:s=160x120:d=1', '-c:v', 'mpeg4', str(video)], check=True)
    images = pipeline.prepare_media([pipeline.MediaFile(video, 'flight.mp4', True)], lambda *_: None)
    assert len(images) == 6
    assert all(i.jpeg.startswith(b'\xff\xd8') for i in images)
    assert images[0].source_label.startswith('flight.mp4 · ')
    broken = tmp_path / 'broken.mp4'
    broken.write_bytes(b'not-a-video')
    with pytest.raises(pipeline.PipelineError):
        pipeline.prepare_media([pipeline.MediaFile(broken, 'broken.mp4', True)], lambda *_: None)


def test_real_sdk_payload_structured_response(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key-not-real')
    captured = {}
    report = {'summary': 'Видны растения.', 'observations': [{'id': 'a', 'label': 'Окраска',
        'severity': 'low', 'description': 'Изменение окраски', 'recommendation': 'Наземный осмотр', 'source': 'S01'}],
        'limitations': ['Недостаточное разрешение']}
    def handler(request):
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={
            'id': 'resp_mock', 'object': 'response', 'created_at': 1, 'status': 'completed',
            'model': 'gpt-5.6-terra', 'error': None, 'incomplete_details': None,
            'instructions': None, 'metadata': {}, 'parallel_tool_calls': False, 'tools': [],
            'output': [{'id': 'msg_mock', 'type': 'message', 'role': 'assistant', 'status': 'completed',
                        'content': [{'type': 'output_text', 'text': json.dumps(report), 'annotations': []}]}],
            'tool_choice': 'auto', 'temperature': 1, 'top_p': 1,
        })
    real_openai = pipeline.OpenAI
    def factory(**kwargs):
        return real_openai(**kwargs, http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    with patch.object(pipeline, 'OpenAI', side_effect=factory):
        result = pipeline.analyze_images([pipeline.PreparedImage('S01', 'field.png', pipeline.normalize_image(png()))],
                                        field='Поле', crop='Пшеница', date='2026-05-18', model='gpt-5.6-terra')
    assert result['observations'][0]['source'] == 'field.png'
    assert captured['store'] is False
    assert captured['reasoning'] == {'effort': 'low'}
    assert captured['text']['format']['type'] == 'json_schema'
    assert captured['text']['format']['strict'] is True
    content = captured['input'][1]['content']
    image = next(c for c in content if c['type'] == 'input_image')
    assert image['image_url'].startswith('data:image/jpeg;base64,')
    assert base64.b64decode(image['image_url'].split(',')[1]).startswith(b'\xff\xd8')
    assert 'недоверенные' in captured['input'][0]['content']


def test_limits_and_cors(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key-not-real')
    data = {'field': 'Поле', 'crop': 'Пшеница', 'date': '2026-05-18'}
    with TestClient(api.app) as client:
        assert client.post('/api/analyses', data=data,
            files=[('files', (f'{i}.png', png(), 'image/png')) for i in range(13)]).status_code == 413
        monkeypatch.setattr(api, 'MAX_PHOTO_BYTES', 10)
        assert client.post('/api/analyses', data=data, files={'files': ('x.png', png())}).status_code == 413
        cors = client.options('/api/analyses', headers={'Origin': 'http://localhost:5173', 'Access-Control-Request-Method': 'POST'})
        assert cors.headers['access-control-allow-origin'] == 'http://localhost:5173'
