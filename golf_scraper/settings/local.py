from .base import *

DEBUG = config('DEBUG', cast=bool, default=False)

INTERNAL_IPS = ['127.0.0.1']
