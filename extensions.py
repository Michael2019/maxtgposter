from flask_caching import Cache
from flask_jwt_extended import JWTManager
from flask_wtf.csrf import CSRFProtect

cache = Cache()
jwt = JWTManager()
csrf = CSRFProtect()
