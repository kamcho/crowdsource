"""Gunicorn config for CrowdSource (WSGI).

Run with:  gunicorn -c deploy/gunicorn.conf.py config.wsgi:application
"""
import multiprocessing
import os

bind = os.environ.get('GUNICORN_BIND', 'unix:/run/crowdsource/crowdsource.sock')
workers = int(os.environ.get('GUNICORN_WORKERS', (multiprocessing.cpu_count() * 2) + 1))
timeout = int(os.environ.get('GUNICORN_TIMEOUT', '120'))
graceful_timeout = 30
keepalive = 5

max_requests = 1000
max_requests_jitter = 100

accesslog = '-'
errorlog = '-'
loglevel = os.environ.get('GUNICORN_LOGLEVEL', 'info')
