from .base import *

DEBUG = config('DEBUG', cast=bool, default=True)

INTERNAL_IPS = ['127.0.0.1']
