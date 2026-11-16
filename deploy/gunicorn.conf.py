"""One model copy with bounded simultaneous inference."""
import os

bind = '0.0.0.0:' + str(int(os.environ.get('PORT', '8080')))
workers = 1
worker_class = 'gthread'
threads = 2
timeout = 180
graceful_timeout = 30
accesslog = '-'
errorlog = '-'
